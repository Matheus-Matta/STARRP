"""Aba "Nota fiscal" da filial: o que a emissão precisa, ajustado no cadastro da filial e usado pelos dois
PDVs (web pelo comunicador em nuvem, desktop pelo kit + segredos gravados no comunicador local)."""
from django.core.files.base import ContentFile

from starrp.models import FiscalConfig


def _address(store):
    store.cnpj, store.legal_name, store.state_registration = "11222333000181", "Loja Teste LTDA", "123456789"
    store.street, store.number, store.district, store.city = "Rua A", "10", "Centro", "São Paulo"
    store.city_ibge, store.state, store.zip_code = "3550308", "SP", "01001000"
    store.save()


def test_filial_sem_dados_fiscais_cria_pelo_cnpj_e_liga_a_emissao(ctx):
    _address(ctx.store)
    api = ctx.client()
    url = f"/api/v1/stores/{ctx.store.pk}/fiscal/"

    empty = api.get(url).json()
    saved = api.post(url, {"environment": "2", "local_fiscal_enabled": True, "local_fiscal_contingency": True,
                           "csc_id": "000001", "csc_token": "SEGREDO"}, format="json")

    assert empty["config"] is None and empty["ready"] is False
    assert saved.status_code == 200, saved.json()
    data = saved.json()
    config = FiscalConfig.all_objects.get(pk=data["config"]["id"])
    assert config.provider == "acbrlib" and config.local_fiscal_enabled and config.local_fiscal_contingency
    assert config.csc_token == "SEGREDO" and data["config"]["has_csc_token"] and "csc_token" not in data["config"]
    checks = {c["key"]: c for c in data["checks"]}
    assert checks["issuer"]["ok"] and checks["csc"]["ok"] and checks["enabled"]["ok"]
    assert not checks["certificate"]["ok"] and data["ready"] is False  # falta só o A1

    # com o certificado a filial fica pronta (o PDV web ainda depende do comunicador no servidor)
    config.certificate_file.save("cert.pfx", ContentFile(b"pfx"), save=True)
    ready = api.get(url).json()
    assert ready["ready"] is True
    # CSC em branco mantém o atual; desligar a emissão desliga a contingência
    api.post(url, {"csc_token": "", "local_fiscal_enabled": False}, format="json")
    config.refresh_from_db()
    assert config.csc_token == "SEGREDO" and not config.local_fiscal_contingency


def test_conferencia_aponta_o_que_falta_no_emitente(ctx):
    ctx.store.cnpj = "11222333000181"
    ctx.store.save()
    data = ctx.client().post(f"/api/v1/stores/{ctx.store.pk}/fiscal/", {"local_fiscal_enabled": True},
                             format="json").json()
    issuer = next(c for c in data["checks"] if c["key"] == "issuer")
    assert not issuer["ok"] and "Código IBGE" in issuer["message"]


def test_certificado_pela_filial_confere_a_senha(ctx):
    _address(ctx.store)
    upload = ContentFile(b"nao e um pfx", name="cert.pfx")
    refused = ctx.client().post(f"/api/v1/stores/{ctx.store.pk}/fiscal/certificate/",
                                {"file": upload, "password": "x"}, format="multipart")
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "certificate_invalid"
