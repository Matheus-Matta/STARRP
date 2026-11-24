"""Rodada 1 de verificação (docs/SEGURANCA.md, S-02/S-11): campo cifrado com nome comum — `Integration.fields`,
com a chave da API dentro — ia DECIFRADO para a auditoria (o filtro era só por nome). O código já não grava;
isto apaga das auditorias antigas o valor desses campos, em qualquer model.
"""
from django.db import migrations

from starrp.core.secrets import SECRET_FIELDS, EncryptedJSONField, EncryptedTextField

HIDDEN = "(oculto)"


def secret_keys(apps):
    out = {}
    for model in apps.get_app_config("starrp").get_models():
        keys = {f.attname for f in model._meta.concrete_fields
                if f.name in SECRET_FIELDS or isinstance(f, (EncryptedTextField, EncryptedJSONField))}
        if keys:
            out[model._meta.model_name] = keys
    return out


def forwards(apps, schema_editor):
    AuditLog = apps.get_model("starrp", "AuditLog")
    secrets = secret_keys(apps)
    for log in AuditLog._base_manager.filter(entity__in=list(secrets)).exclude(changes={}).iterator():
        keys, changes, dirty = secrets[log.entity], log.changes or {}, False
        if not isinstance(changes, dict):
            continue
        for item in changes.get("fields") or []:
            if isinstance(item, dict) and item.get("key") in keys and (item.get("from"), item.get("to")) != ("—", HIDDEN):
                item["from"], item["to"], dirty = "—", HIDDEN, True
        for key in keys & set(changes):  # ação em massa grava {campo: valor}
            if changes[key] != HIDDEN:
                changes[key], dirty = HIDDEN, True
        if dirty:
            AuditLog._base_manager.filter(pk=log.pk).update(changes=changes)


class Migration(migrations.Migration):

    dependencies = [
        ("starrp", "0068_account_cosmos_voice_enabled"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
