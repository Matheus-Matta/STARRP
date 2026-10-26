"""Dados fiscais (emitente): criar a partir das lojas e ler o certificado A1.

A loja tem o cadastro dela (nome, CNPJ, endereço); "Dados fiscais" é o emitente
que a SEFAZ conhece. Para não digitar duas vezes, `from_store` copia o que a
loja já tem e vincula: mesmo CNPJ → mesmos dados fiscais (filial com o mesmo
CNPJ da matriz reaproveita).
"""
from datetime import timezone as dt_timezone

from cryptography import x509
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from django.db import transaction

from starrp.core.errors import BusinessError
from starrp.core.text import only_digits
from starrp.models import FiscalConfig, FiscalSeries, Store
from starrp.models.fiscal import DocumentModel

COPIED = ("legal_name", "state_registration", "municipal_registration", "phone", "email", "street", "number",
          "complement", "district", "city", "city_ibge", "state", "zip_code")


@transaction.atomic
def from_store(store, user=None):
    """Dados fiscais da loja: acha pelo CNPJ ou cria com o cadastro dela, e vincula."""
    cnpj = only_digits(store.cnpj)
    if len(cnpj) != 14:
        raise BusinessError(f"A filial {store.name} não tem CNPJ válido para os dados fiscais.", code="store_no_cnpj")
    config = FiscalConfig.all_objects.filter(account_id=store.account_id, cnpj=cnpj, deleted_at__isnull=True).first()
    if config is None:
        config = FiscalConfig.all_objects.create(
            account_id=store.account_id, name=store.name, trade_name=store.name, cnpj=cnpj, created_by=user,
            **{field: getattr(store, field) or "" for field in COPIED},
        )
        if not config.legal_name:
            config.legal_name = store.name
            config.save(update_fields=["legal_name"])
        for model in DocumentModel.values:
            FiscalSeries.all_objects.create(account_id=store.account_id, config=config, document_model=model)
    if store.fiscal_config_id != config.pk:
        Store.all_objects.filter(pk=store.pk).update(fiscal_config=config)
        store.fiscal_config = config
    return config


def from_all_stores(account_id, user=None):
    """Cria/vincula os dados fiscais de toda loja com CNPJ ainda sem vínculo."""
    done, skipped = [], []
    for store in Store.all_objects.filter(account_id=account_id, deleted_at__isnull=True, fiscal_config__isnull=True):
        if len(only_digits(store.cnpj)) == 14:
            done.append(from_store(store, user))
        else:
            skipped.append(store.name)
    return done, skipped


def read_certificate(content: bytes, password: str):
    """Abre o .pfx com a senha. Devolve (chave, certificado, cadeia) ou explica o erro."""
    try:
        key, cert, chain = load_key_and_certificates(content, password.encode() if password else None)
    except ValueError:
        raise BusinessError("Senha errada ou arquivo não é um certificado A1 (.pfx).", code="certificate_invalid") from None
    if key is None or cert is None:
        raise BusinessError("O arquivo não tem a chave privada do certificado.", code="certificate_invalid")
    return key, cert, chain or []


def certificate_info(cert):
    """Titular, CNPJ (vem no CN: "EMPRESA LTDA:12345678000199") e validade."""
    names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    common = names[0].value if names else ""
    holder, _, digits = str(common).rpartition(":")
    cnpj = only_digits(digits) if len(only_digits(digits)) == 14 else ""
    return {"name": (holder or common)[:255], "cnpj": cnpj,
            "valid_until": cert.not_valid_after_utc.astimezone(dt_timezone.utc)}


@transaction.atomic
def save_certificate(config, upload, password):
    """Guarda o .pfx nos dados fiscais depois de conferir senha, titular e validade."""
    content = upload.read()
    _, cert, _ = read_certificate(content, password)
    info = certificate_info(cert)
    if info["cnpj"] and info["cnpj"][:8] != only_digits(config.cnpj)[:8]:
        raise BusinessError(f"O certificado é do CNPJ {info['cnpj']}, de outra empresa.", code="certificate_other_cnpj")
    upload.seek(0)
    config.certificate_file.save(f"{only_digits(config.cnpj)}.pfx", upload, save=False)
    config.certificate_password = password
    config.certificate_name, config.certificate_cnpj = info["name"], info["cnpj"]
    config.certificate_valid_until = info["valid_until"]
    config.save()
    return config


def load_certificate(config):
    """(chave, certificado) para assinar e para o TLS mútuo com a SEFAZ."""
    if not config.certificate_file:
        raise BusinessError(f"Envie o certificado digital A1 nos dados fiscais de {config.name}.",
                            code="certificate_missing")
    with config.certificate_file.open("rb") as handle:
        content = handle.read()
    key, cert, _ = read_certificate(content, config.certificate_password)
    return key, cert
