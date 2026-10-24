"""Isolamento abaixo do tenant: usuários e dados separados por loja/filial."""
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.models import CashRegister, Coupon, Sale, StockMovement
from starrp.services import sales, stock
from starrp.services.provisioning import create_store


@pytest.fixture
def branches(ctx):
    """Loja A (a do contexto) e loja B na mesma conta, com um caixa em cada."""
    store_b = create_store(ctx.account, "Filial B")
    return ctx.store, store_b


def _sale(ctx, store):
    return sales.create(store, ctx.admin)


def test_caixa_da_loja_a_nao_ve_nem_abre_venda_da_loja_b(ctx, branches):
    """Listagem, detalhe e header de outra filial: nada da loja B chega a quem é só da A."""
    store_a, store_b = branches
    cashier = ctx.user("caixa_a", "cashier")
    own, foreign = _sale(ctx, store_a), _sale(ctx, store_b)

    api = ctx.client(cashier, store=None)
    listing = api.get("/api/v1/sales/").json()
    detail = api.get(f"/api/v1/sales/{foreign.pk}/")
    forced = ctx.client(cashier, store=store_b).get("/api/v1/sales/")

    assert [row["id"] for row in listing["results"]] == [str(own.pk)]
    assert detail.status_code == 404
    assert forced.status_code == 403
    assert forced.json()["error"]["code"] == "store_forbidden"


def test_gerente_de_duas_filiais_ve_as_duas_e_filtra_pelo_header(ctx, branches):
    """Sem header vê a rede permitida; com X-Store-ID, só a loja escolhida."""
    store_a, store_b = branches
    manager = ctx.user("gerente_ab", "manager", stores=[store_a, store_b])
    _sale(ctx, store_a), _sale(ctx, store_b)

    both = ctx.client(manager, store=None).get("/api/v1/sales/").json()
    only_b = ctx.client(manager, store=store_b).get("/api/v1/sales/").json()

    assert both["count"] == 2
    assert only_b["count"] == 1 and only_b["results"][0]["store"] == str(store_b.pk)


def test_asterisco_pede_todas_as_lojas_mesmo_com_loja_padrao(ctx, branches):
    """Com loja padrão, sem header vale a padrão; `X-Store-ID: *` mostra a rede permitida."""
    store_a, store_b = branches
    manager = ctx.user("gerente_pad", "manager", stores=[store_a, store_b], default_store=store_a)
    _sale(ctx, store_a), _sale(ctx, store_b)
    api = ctx.client(manager, store=None)

    default_only = api.get("/api/v1/sales/").json()
    everything = api.get("/api/v1/sales/", HTTP_X_STORE_ID="*").json()

    assert default_only["count"] == 1
    assert everything["count"] == 2


def test_nao_abre_turno_no_caixa_de_outra_filial(ctx, branches):
    """O id do caixa da loja B é recusado na validação: o FK sozinho aceitaria."""
    _store_a, store_b = branches
    cashier = ctx.user("caixa_a2", "cashier")
    register_b = CashRegister.all_objects.get(store=store_b)

    response = ctx.client(cashier).post("/api/v1/cash/sessions/", {"register": str(register_b.pk)}, format="json")

    assert response.status_code == 400


def test_tabelas_filhas_tambem_sao_isoladas(ctx, branches):
    """Saldo de estoque não tem campo loja; chega a ela pelo depósito, e mesmo assim é isolado."""
    store_a, store_b = branches
    product = ctx.product(price="10.00")
    stock.move(product, stock.default_warehouse(store_a), Decimal("5"), StockMovement.Kind.PURCHASE)
    stock.move(product, stock.default_warehouse(store_b), Decimal("7"), StockMovement.Kind.PURCHASE)
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    stockist = ctx.user("estoque_a", "stockist")

    rows = ctx.client(stockist, store=None).get("/api/v1/stock/balances/").json()["results"]

    assert [Decimal(row["quantity"]) for row in rows] == [Decimal("5.000")]


def test_relatorio_sem_loja_soma_so_as_lojas_do_usuario(ctx, branches):
    """O resumo da "rede" de quem é de filial é a rede DELE, não a conta inteira."""
    store_a, store_b = branches
    Sale.all_objects.bulk_create([
        Sale(account=ctx.account, store=store, number=n, status=Sale.Status.COMPLETED, total=Decimal(total),
             completed_at=timezone.now())
        for n, (store, total) in enumerate([(store_a, "100.00"), (store_b, "900.00")], start=1)
    ])
    manager = ctx.user("gerente_a", "manager")

    summary = ctx.client(manager, store=None).get("/api/v1/reports/summary/").json()

    assert Decimal(summary["revenue"]) == Decimal("100.00")


def test_usuario_de_filial_nao_cria_nem_altera_cadastro_da_rede(ctx, branches):
    """Cupom criado por gerente de filial nasce da filial; o cupom da rede ele vê, mas não altera."""
    store_a, _store_b = branches
    network = Coupon.all_objects.create(account=ctx.account, code="REDE10", value=Decimal("10"))
    manager = ctx.user("gerente_a2", "manager")
    api = ctx.client(manager)

    created = api.post("/api/v1/promotions/coupons/", {"code": "LOJA5", "value": "5"}, format="json")
    edit = api.patch(f"/api/v1/promotions/coupons/{network.pk}/", {"value": "50"}, format="json")

    assert created.status_code == 201 and created.json()["store"] == str(store_a.pk)
    assert edit.status_code == 403


def test_gerente_de_filial_nao_escala_acesso(ctx, branches):
    """Não concede "todas as lojas", não dá acesso a loja que não tem e não cria administrador."""
    store_a, store_b = branches
    manager = ctx.user("gerente_a3", "manager")
    api = ctx.client(manager)
    base = {"username": "novo", "password": "senha123", "role": str(ctx.user_role("cashier").pk)}

    all_stores = api.post("/api/v1/users/", {**base, "all_stores": True}, format="json")
    other = api.post("/api/v1/users/", {**base, "stores": [str(store_b.pk)]}, format="json")
    admin = api.post("/api/v1/users/", {**base, "role": str(ctx.user_role("admin").pk),
                                        "stores": [str(store_a.pk)]}, format="json")
    ok = api.post("/api/v1/users/", {**base, "stores": [str(store_a.pk)]}, format="json")

    assert all_stores.status_code == other.status_code == admin.status_code == 400
    assert ok.status_code == 201, ok.json()


def test_usuario_sem_loja_nenhuma_e_barrado(ctx):
    """Perfil sem loja e sem "todas as lojas" não entra: nunca cai na rede inteira por omissão."""
    orphan = ctx.user("orfao", "cashier", stores=[])

    response = ctx.client(orphan, store=None).get("/api/v1/sales/")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "no_store_access"
