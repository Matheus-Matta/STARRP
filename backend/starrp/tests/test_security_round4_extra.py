"""Rodada 4: certificado, canal, sessão do suporte, comissão e comandos de demonstração."""
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import timezone

from starrp.core.secrets import encrypt_bytes
from starrp.models import Commission, Coupon, FiscalConfig
from starrp.services.provisioning import create_store


def test_t08c_certificado_de_outra_filial_sai_pelo_emissor(ctx):
    create_store(ctx.account, name="B")
    cfg = FiscalConfig.all_objects.create(
        account=ctx.account, name="B", legal_name="B", cnpj="11222333000181", environment="1", csc_id="1",
        csc_token="segredo-de-B", provider="acbrlib", local_fiscal_enabled=True, state_registration="1", street="r",
        district="d", city="c", city_ibge="1", state="SP", zip_code="01001000", certificate_password="senha-de-B")
    cfg.certificate_file.save("certificado.pfx", ContentFile(encrypt_bytes(b"PFX-DE-B")))
    u = ctx.user("ti", "it")
    u.profile.extra_roles.add(ctx.user_role("fiscal"))  # settings.* + fiscal.*, so na filial A
    api = ctx.client(u)
    api.patch(f"/api/v1/stores/{ctx.store.pk}/", {"fiscal_config": str(cfg.pk)}, format="json")
    r = api.get("/api/v1/pdv/fiscal-emitter/")
    assert b"senha-de-B" not in r.content


def test_t34_canal_escolhido_pelo_cliente_libera_cupom_do_site(ctx):
    Coupon.all_objects.create(account=ctx.account, code="SITE", value=Decimal("50"), channels=["ecommerce"])
    api = ctx.client(ctx.user("caixa", "cashier"))
    v = ctx.product(track_stock=False)
    out = []
    for channel in ("pos", "ecommerce"):
        sale = api.post("/api/v1/sales/", {"channel": channel}, format="json")
        if sale.status_code != 201:
            out.append((channel, sale.content[:200]))
            continue
        sid = sale.json()["id"]
        api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
        out.append((channel, api.post(f"/api/v1/sales/{sid}/coupon/", {"code": "SITE"}, format="json").status_code))
    assert all(code != 200 for _c, code in out)


def test_t35_sessao_do_superusuario_com_header_de_conta_sobrevive_a_troca_de_senha(ctx):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    from starrp.services import sessions
    su = get_user_model().objects.create_superuser("root", password="x")
    token = RefreshToken.for_user(su).access_token
    token["iat"] = int((timezone.now() - timedelta(minutes=5)).timestamp())
    sessions.revoke_all(su)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_ACCOUNT_ID=str(ctx.account.pk), HTTP_X_STORE_ID=str(ctx.store.pk))
    r = api.get("/api/v1/users/")
    assert r.status_code == 401


def test_t36_pagamento_de_comissao_soma_as_linhas_que_travou(ctx):
    """O total vinha de um `aggregate` (que descarta o FOR UPDATE) e as linhas, da consulta seguinte."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from starrp.models import FinancialAccount
    from starrp.services import commissions, sales
    seller = ctx.user("v", "seller", is_seller=True)
    sale = sales.create(ctx.store, ctx.admin)
    item = sales.add_item(sale, ctx.product(track_stock=False), Decimal("1"), ctx.admin)
    for value in (Decimal("100"), Decimal("10")):
        Commission.all_objects.create(account=ctx.account, store=ctx.store, seller=seller, sale=sale, sale_item=item,
                                      base_amount=value, rate=1, amount=value)
    bank = FinancialAccount.all_objects.filter(account=ctx.account, kind="bank").first()
    with CaptureQueriesContext(connection) as queries:
        paid = commissions.pay(ctx.account, seller, bank, ctx.admin)
    reads = [q["sql"] for q in queries if q["sql"].startswith("SELECT") and 'FROM "starrp_commission"' in q["sql"]]
    assert paid["total"] == 110 and len(reads) == 1


def test_comandos_de_demonstracao_nao_rodam_em_producao(settings):
    import pytest
    from django.core.management import CommandError, call_command

    settings.DEBUG, settings.ENVIRONMENT = False, "production"
    for name in ("seed_demo", "seed_extras", "seed_promotions", "seed_real_products", "seed_reviews"):
        with pytest.raises(CommandError, match="produção"):
            call_command(name)


def test_health_ready_confere_o_banco(client, db, monkeypatch):
    assert client.get("/health/ready/").status_code == 200
    from config import urls

    def broken():
        raise OSError("banco fora")

    with monkeypatch.context() as patch:
        patch.setattr(urls.connection, "cursor", broken)
        response = client.get("/health/ready/")
    assert response.status_code == 503
