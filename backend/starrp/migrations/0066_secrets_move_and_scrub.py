"""S-01/S-02/S-11 (docs/SEGURANCA.md): o que já estava gravado antes da cifra.

1. Cifra os segredos que estavam em texto (regravar passa pelo EncryptedTextField/EncryptedJSONField).
2. Move cada certificado A1 de MEDIA_ROOT/certificates/<CNPJ>.pfx (servido por /media!) para a pasta privada,
   cifrado e com nome aleatório, e apaga o arquivo antigo.
3. Limpa da auditoria (AuditLog.changes) os valores de campos secretos já registrados.

Depois de aplicar em produção: ROTACIONE os certificados, o CSC e a senha de ações do caixa (podem ter vazado).
"""
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import migrations

from starrp.core.secrets import FILE_MAGIC, SECRET_FIELDS, encrypt_bytes, private_storage

HIDDEN = "(oculto)"


def resave(apps, model, fields):
    Model = apps.get_model("starrp", model)
    rows = list(Model._base_manager.all())
    for row in rows:
        row.save(update_fields=fields)  # get_prep_value cifra o que estava em claro


def move_certificates(apps, connection):
    FiscalConfig = apps.get_model("starrp", "FiscalConfig")
    private = private_storage()
    for config in FiscalConfig._base_manager.exclude(certificate_file="").exclude(certificate_file__isnull=True):
        name = config.certificate_file.name
        if private.exists(name):
            with private.open(name, "rb") as handle:
                data = handle.read()
            if data.startswith(FILE_MAGIC):
                continue  # já movido e cifrado
            source = private
        elif default_storage.exists(name):
            with default_storage.open(name, "rb") as handle:
                data = handle.read()
            source = default_storage
        else:
            continue  # arquivo sumiu: o registro aponta para nada (envie de novo pela tela)
        new_name = private.save(f"certificates/{uuid.uuid4().hex}.pfx.enc", ContentFile(encrypt_bytes(data)))
        FiscalConfig._base_manager.filter(pk=config.pk).update(certificate_file=new_name)
        # Apaga o original só DEPOIS do commit: se algo falhar antes, o banco volta a apontar para ele, que
        # continua lá (rodada 1, P-12).
        connection.on_commit(lambda source=source, name=name: source.delete(name))


def scrub_audit(apps):
    AuditLog = apps.get_model("starrp", "AuditLog")
    for log in AuditLog._base_manager.exclude(changes={}).iterator():
        changes = log.changes or {}
        fields = changes.get("fields") if isinstance(changes, dict) else None
        if not isinstance(fields, list):
            continue
        dirty = False
        for item in fields:
            if isinstance(item, dict) and item.get("key") in SECRET_FIELDS and (item.get("from"), item.get("to")) != ("—", HIDDEN):
                item["from"], item["to"] = "—", HIDDEN
                dirty = True
        if dirty:
            AuditLog._base_manager.filter(pk=log.pk).update(changes=changes)


def forwards(apps, schema_editor):
    resave(apps, "FiscalConfig", ["csc_token", "certificate_password", "provider_token_production",
                                  "provider_token_homologation"])
    resave(apps, "PriceSourceToken", ["token"])
    resave(apps, "SeoCredential", ["client_secret", "refresh_token", "developer_token"])
    resave(apps, "Integration", ["fields"])
    move_certificates(apps, schema_editor.connection)
    scrub_audit(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("starrp", "0065_secrets_encrypted"),
    ]

    # Sem volta: decifrar e expor de novo não é uma operação que se queira.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
