"""Segurança dos segredos (docs/SEGURANCA.md S-01, S-02, S-11).

S-01: o certificado A1 nunca fica no MEDIA_ROOT (servido por /media), não tem o CNPJ no nome e é cifrado.
S-02: senha do A1, CSC e senha de ações do caixa nunca aparecem no histórico/auditoria.
S-11: segredos ficam cifrados no banco (o código continua lendo em claro).
"""
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from starrp.core.secrets import FILE_MAGIC, PREFIX
from starrp.models import FiscalConfig, Integration, Store
from starrp.services import fiscal_data

from .test_dfe import CNPJ, pfx


def _fiscal(ctx):
    ctx.account.extra_modules = ["fiscal"]
    ctx.account.save()
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj=CNPJ, state="SP", legal_name="Loja Teste LTDA")
    ctx.store.refresh_from_db()
    return fiscal_data.from_store(ctx.store)


def _raw(table, column, pk):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT "{column}" FROM "{table}" WHERE id = %s', [str(pk).replace("-", "")])
        row = cursor.fetchone()
        if row is None:
            cursor.execute(f'SELECT "{column}" FROM "{table}" WHERE id = %s', [str(pk)])
            row = cursor.fetchone()
    return row[0]


def test_certificado_fica_na_pasta_privada_cifrado_e_sem_cnpj_no_nome(ctx):
    config = _fiscal(ctx)
    original = pfx()
    fiscal_data.save_certificate(config, SimpleUploadedFile("a1.pfx", original), "1234")
    config = FiscalConfig.all_objects.get(pk=config.pk)

    path = Path(config.certificate_file.path).resolve()
    assert Path(settings.PRIVATE_MEDIA_ROOT).resolve() in path.parents
    assert Path(settings.MEDIA_ROOT).resolve() not in path.parents
    assert CNPJ not in config.certificate_file.name
    assert path.read_bytes().startswith(FILE_MAGIC) and original not in path.read_bytes()
    assert config.certificate_bytes() == original
    # Assina com o certificado guardado (o caminho real de uso).
    key, cert = fiscal_data.load_certificate(config)
    assert key is not None and cert is not None


def test_certificado_nao_tem_endereco_publico(ctx):
    config = _fiscal(ctx)
    fiscal_data.save_certificate(config, SimpleUploadedFile("a1.pfx", pfx()), "1234")
    config = FiscalConfig.all_objects.get(pk=config.pk)
    with pytest.raises(ValueError):
        _ = config.certificate_file.url  # sem endereço público


def test_segredos_ficam_cifrados_no_banco(ctx):
    config = _fiscal(ctx)
    FiscalConfig.all_objects.filter(pk=config.pk).update()  # garante a linha
    config.csc_token, config.certificate_password = "CSC-SECRETO-123", "senha-do-a1"
    config.save()
    integration = Integration.all_objects.create(account=ctx.account, kind="asaas", name="Asaas",
                                                 fields={"api_key": "chave-secreta"})

    raw_csc = _raw(FiscalConfig._meta.db_table, "csc_token", config.pk)
    raw_fields = _raw(Integration._meta.db_table, "fields", integration.pk)
    assert raw_csc.startswith(PREFIX) and "CSC-SECRETO" not in raw_csc
    assert raw_fields.startswith(PREFIX) and "chave-secreta" not in raw_fields
    assert FiscalConfig.all_objects.get(pk=config.pk).csc_token == "CSC-SECRETO-123"
    assert Integration.all_objects.get(pk=integration.pk).fields == {"api_key": "chave-secreta"}


def test_historico_nunca_mostra_segredo_fiscal_nem_senha_do_caixa(ctx):
    config = _fiscal(ctx)
    api = ctx.client()
    fiscal_data.save_certificate(config, SimpleUploadedFile("a1.pfx", pfx()), "1234")
    api.patch(f"/api/v1/fiscal/configs/{config.pk}/", {"csc_id": "000001", "csc_token": "CSC-SECRETO-XYZ"},
              format="json")
    api.patch(f"/api/v1/stores/{ctx.store.pk}/", {"cash_action_password": "4321"}, format="json")
    ctx.store.refresh_from_db()
    ctx.store.set_cash_action_password("9876")
    ctx.store.save()

    auditor = ctx.client(ctx.user("aud", "auditor"))
    texts = []
    for url in (f"/api/v1/fiscal/configs/{config.pk}/history/", f"/api/v1/stores/{ctx.store.pk}/history/"):
        for client in (api, auditor):
            response = client.get(url)
            if response.status_code == 200:
                texts.append(str(response.json()))
    dump = " ".join(texts)
    assert texts, "nenhum histórico consultado"
    for secret in ("CSC-SECRETO-XYZ", "1234", "4321", "9876", "pbkdf2_", "argon2", "md5$"):
        assert secret not in dump, secret
    # As tabelas do histórico nem têm as colunas dos segredos.
    historical = {f.name for f in FiscalConfig.history.model._meta.fields}
    assert not historical & {"csc_token", "certificate_password"}
    assert "cash_action_password" not in {f.name for f in Store.history.model._meta.fields}


def test_segredo_da_integracao_nao_vai_decifrado_para_a_auditoria(ctx):
    """Rodada 1 (S-11 por outro caminho): o campo cifrado com nome comum (`fields`) ia em claro para o AuditLog."""
    from starrp.models import AuditLog
    from starrp.services import history

    integration = Integration.all_objects.create(account=ctx.account, kind="asaas", name="Asaas",
                                                 fields={"api_key": "chave-antiga"})
    before = history.snapshot(integration)
    integration.fields = {"api_key": "chave-NOVA-secreta"}
    integration.save()
    changes = history.diff(before, integration)

    assert "chave-NOVA-secreta" not in str(changes) and "chave-antiga" not in str(before)
    assert any(c["key"] == "fields" and c["to"] == "(alterado)" for c in changes)
    assert not AuditLog.all_objects.filter(changes__icontains="chave-NOVA").exists()
