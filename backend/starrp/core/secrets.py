"""Segredos: cifrados em repouso, nunca no histórico/auditoria, nunca servidos por /media.

- `SECRET_FIELDS`: nomes de campo que são segredo em QUALQUER model (CSC, senha do certificado, tokens,
  hash de senha). O histórico (simple_history) não guarda a coluna; a auditoria e a linha do tempo mostram
  só "alterado".
- `EncryptedTextField`: o valor vai cifrado (Fernet/AES) para o banco e volta em claro para o código. Valor
  antigo, gravado antes da cifra, ainda é lido (e sai cifrado na próxima gravação).
- `encrypt_bytes`/`decrypt_bytes`: o mesmo para arquivos (certificado A1).
- `private_storage`: pasta fora do MEDIA_ROOT que nenhum proxy serve (nginx/Caddy só servem /media).

A chave é `FIELD_ENCRYPTION_KEY` (obrigatória em produção, ver production.py). Em desenvolvimento, sem ela,
deriva do SECRET_KEY. Trocar a chave exige recifrar os dados (`manage.py rotate_field_key`, se criado):
guarde-a junto do backup do banco.
"""
import base64
import logging
import json
import os
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django import forms
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.functional import LazyObject

SECRET_FIELDS = frozenset({
    "csc_token", "certificate_password", "provider_token_production", "provider_token_homologation",
    "cash_action_password", "password", "token", "token_hash", "client_secret", "refresh_token",
    "developer_token", "webhook_secret", "api_key", "access_token", "secret",
})
logger = logging.getLogger(__name__)
PREFIX = "enc1:"
FILE_MAGIC = b"STARRP-ENC1\n"


def _keys():
    configured = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    keys = [k.strip() for k in configured.split(",") if k.strip()]  # várias = rotação (a 1ª cifra)
    if not keys:
        digest = hashlib.sha256(f"starrp-field-key:{settings.SECRET_KEY}".encode()).digest()
        keys = [base64.urlsafe_b64encode(digest).decode()]
    return keys


class _Cipher(LazyObject):
    def _setup(self):
        self._wrapped = MultiFernet([Fernet(k) for k in _keys()])


cipher = _Cipher()


def reset_cipher():
    """Testes que trocam a chave nas settings."""
    global cipher
    cipher = _Cipher()


def _is_encrypted(value: str) -> bool:
    """Já cifrado = tem o prefixo E decifra. Um segredo digitado que só COMEÇA com "enc1:" ainda é texto em claro
    (rodada 1, P-14: antes ia para o banco sem cifra e a leitura quebrava)."""
    if not value.startswith(PREFIX):
        return False
    try:
        cipher.decrypt(value[len(PREFIX):].encode())
        return True
    except InvalidToken:
        return False


def encrypt_text(value: str) -> str:
    if not value or _is_encrypted(value):
        return value
    return PREFIX + cipher.encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value  # vazio ou gravado antes da cifra
    try:
        return cipher.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        # Ou é um texto em claro que só começa com "enc1:" (gravado antes desta correção), ou a chave é outra.
        # Devolver o próprio valor não vaza nada além do que está no banco e não derruba a tela com 500; o log
        # avisa (chave errada em produção quebra a emissão fiscal e precisa ser vista).
        logger.error("Segredo com prefixo de cifra que não decifra (FIELD_ENCRYPTION_KEY errada ou valor antigo).")
        return value


def encrypt_bytes(data: bytes) -> bytes:
    return FILE_MAGIC + cipher.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    if not data.startswith(FILE_MAGIC):
        return data  # arquivo antigo, gravado antes da cifra
    try:
        return cipher.decrypt(data[len(FILE_MAGIC):])
    except InvalidToken as error:
        raise ValueError("Arquivo cifrado com outra chave (FIELD_ENCRYPTION_KEY).") from error


def fingerprint(value) -> str:
    """Marca para o histórico perceber que o segredo mudou sem guardar o valor (HMAC com o SECRET_KEY:
    não dá para testar senhas contra ela fora do servidor)."""
    if value in (None, ""):
        return ""
    return hmac.new(settings.SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:16]


class EncryptedTextField(models.TextField):
    """Texto cifrado no banco. Não serve para filtro/ordenação (o banco só vê o texto cifrado)."""

    description = "Texto cifrado (Fernet)"

    def from_db_value(self, value, expression, connection):
        return decrypt_text(value) if isinstance(value, str) else value

    def to_python(self, value):
        value = super().to_python(value)
        return decrypt_text(value) if isinstance(value, str) else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_text(value) if isinstance(value, str) else value

    def formfield(self, **kwargs):
        # Uma linha (não textarea). Mostra o valor: com campo de senha vazio, salvar outro campo no admin
        # apagaria o segredo (o admin é só do superusuário).
        kwargs.setdefault("widget", forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}))
        return super().formfield(**{"form_class": forms.CharField, **kwargs})


class EncryptedJSONField(models.TextField):
    """JSON cifrado (ex.: configurações de uma integração, com chave da API e tokens dentro).

    No banco é texto cifrado; no código, dict/list. Valor antigo (JSON em claro) ainda é lido."""

    description = "JSON cifrado (Fernet)"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default", dict)
        super().__init__(*args, **kwargs)

    @staticmethod
    def _load(value):
        if value is None or isinstance(value, (dict, list)):
            return value
        text = decrypt_text(value)
        return json.loads(text) if text else {}

    def from_db_value(self, value, expression, connection):
        return self._load(value)

    def to_python(self, value):
        return self._load(value) if isinstance(value, str) else value

    def get_prep_value(self, value):
        if value is None:
            return None
        return encrypt_text(json.dumps(value, ensure_ascii=False, sort_keys=True))

    def value_to_string(self, obj):
        return json.dumps(self.value_from_object(obj))

    def formfield(self, **kwargs):
        return forms.JSONField(**kwargs)


def is_secret_field(field):
    """Campo que é segredo: pelo nome (SECRET_FIELDS) ou por ser cifrado (o valor decifrado nunca vai para
    histórico/auditoria). Ex.: `Integration.fields` tem nome comum, mas guarda a chave da API."""
    return field.name in SECRET_FIELDS or getattr(field, "attname", "") in SECRET_FIELDS or isinstance(
        field, (EncryptedTextField, EncryptedJSONField))


def _private_location():
    return str(getattr(settings, "PRIVATE_MEDIA_ROOT", settings.BASE_DIR / "private"))


class PrivateStorage(FileSystemStorage):
    """Arquivos que NUNCA são servidos por URL (certificado A1). Sem `base_url`: `.url()` não existe.

    A pasta é lida das settings a cada uso (não na importação): testes e deploy trocam PRIVATE_MEDIA_ROOT."""

    @property
    def base_location(self):
        return _private_location()

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Arquivo privado: não tem endereço público.")


def private_storage():
    return PrivateStorage()
