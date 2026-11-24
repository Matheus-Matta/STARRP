"""Correções da revisão do backend: pagamento em venda quitada, estoque por filial e consultas por requisição."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from starrp.models import Payment, StockMovement
from starrp.services import stock
from starrp.services.provisioning import create_store


def _stock(ctx, variant, quantity, store=None):
    warehouse = stock.default_warehouse(store or ctx.store)
    stock.move(variant, warehouse, Decimal(quantity), StockMovement.Kind.PURCHASE, unit_cost=Decimal("5.00"))


def test_dinheiro_em_venda_ja_quitada_e_recusado(ctx):
    """Antes: nascia um pagamento de R$ 0 e o valor entregue inteiro virava "troco" da venda."""
    product = ctx.product(price="10.00")
    _stock(ctx, product, 5)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    cash = str(ctx.methods["cash"].pk)
    first = api.post(f"/api/v1/sales/{sale['id']}/payments/", {"method": cash, "amount": "10.00"}, format="json")
    assert first.status_code == 201, first.json()

    again = api.post(f"/api/v1/sales/{sale['id']}/payments/",
                     {"method": cash, "amount": "5.00", "tendered": "5.00"}, format="json")

    assert again.status_code == 422, again.json()
    assert Payment.all_objects.filter(sale_id=sale["id"]).count() == 1
    assert Decimal(api.get(f"/api/v1/sales/{sale['id']}/").json()["change_amount"]) == 0


def test_estoque_da_lista_e_o_da_filial_ativa(ctx):
    """Antes: `with_stock` somava os depósitos de TODAS as filiais (o PDV via o estoque da rede)."""
    other = create_store(ctx.account, "Filial B")
    product = ctx.product(price="10.00")
    _stock(ctx, product, 3)
    _stock(ctx, product, 100, store=other)

    here = ctx.client().get("/api/v1/catalog/variants/", {"with_stock": 1, "product": str(product.product_id)}).json()
    there = ctx.client(store=other).get("/api/v1/catalog/variants/",
                                        {"with_stock": 1, "product": str(product.product_id)}).json()
    every = ctx.client(store=None).get("/api/v1/catalog/products/", {"with_stock": 1}).json()

    assert Decimal(here["results"][0]["stock_quantity"]) == 3
    assert Decimal(there["results"][0]["stock_quantity"]) == 100
    # Sem filial ativa (admin vê todas): a soma das filiais permitidas.
    row = next(r for r in every["results"] if r["id"] == str(product.product_id))
    assert Decimal(row["stock_quantity"]) == 103


def test_restrito_a_uma_filial_nao_soma_o_estoque_das_outras(ctx):
    other = create_store(ctx.account, "Filial B")
    product = ctx.product(price="10.00")
    _stock(ctx, product, 3)
    _stock(ctx, product, 100, store=other)
    cashier = ctx.user("caixa_a", "cashier")

    rows = ctx.client(cashier, store=None).get("/api/v1/catalog/variants/",
                                               {"with_stock": 1, "product": str(product.product_id)}).json()

    assert Decimal(rows["results"][0]["stock_quantity"]) == 3


def test_permissoes_calculadas_uma_vez_por_requisicao(ctx):
    """Antes: cada checagem de permissão (middleware, view, cada linha) refazia 3-4 consultas."""
    manager = ctx.user("gerente", "manager")
    api = ctx.client(manager)
    api.get("/api/v1/me/")  # aquece caches de processo
    with CaptureQueriesContext(connection) as queries:
        response = api.get("/api/v1/me/")
    assert response.status_code == 200
    permission_queries = [q for q in queries.captured_queries if '"starrp_permission"' in q["sql"]]
    assert len(permission_queries) <= 2, [q["sql"][:120] for q in permission_queries]


def test_cupom_esgotado_depois_de_aplicado_nao_conclui(ctx):
    """Antes: o limite só era conferido ao APLICAR. Duas vendas com o último uso concluíam as duas."""
    from starrp.models import Coupon, CouponRedemption

    Coupon.all_objects.create(account=ctx.account, code="ULTIMO", kind="amount", value=Decimal("5"), usage_limit=1)
    product = ctx.product(price="20.00", track_stock=False)
    api = ctx.client()
    pix = str(ctx.methods["pix"].pk)

    def sale_with_coupon():
        sale = api.post("/api/v1/sales/", {}, format="json").json()
        api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
        applied = api.post(f"/api/v1/sales/{sale['id']}/coupon/", {"code": "ULTIMO"}, format="json")
        assert applied.status_code == 200, applied.json()
        return sale

    first, second = sale_with_coupon(), sale_with_coupon()  # as duas aplicam: ainda não há uso gravado
    done = api.post(f"/api/v1/sales/{first['id']}/checkout/",
                    {"payments": [{"nsu": "1", "method": pix, "amount": "15.00"}]}, format="json")
    late = api.post(f"/api/v1/sales/{second['id']}/checkout/",
                    {"payments": [{"nsu": "2", "method": pix, "amount": "15.00"}]}, format="json")

    assert done.status_code == 200, done.json()
    assert late.status_code == 422 and late.json()["error"]["code"] == "coupon_exhausted"
    assert CouponRedemption.all_objects.filter(coupon__code="ULTIMO").count() == 1


def test_desconto_maior_que_o_saldo_e_recusado(ctx):
    """Antes: o saldo ficava negativo e, com "pago a mais", virava lançamento de valor negativo na conta."""
    from starrp.models import FinancialAccount, FinancialTransaction, Supplier

    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    bank = FinancialAccount.all_objects.get(account=ctx.account, name="Banco principal")
    supplier = Supplier.all_objects.create(account=ctx.account, name="Fornecedor X")
    api = ctx.client()
    title = api.post("/api/v1/finance/titles/", {"kind": "payable", "description": "Compra", "total": "100.00",
                                                  "installment_count": 1, "first_due": "2026-11-10",
                                                  "supplier": str(supplier.pk)}, format="json").json()
    part = title["installments"][0]

    response = api.post(f"/api/v1/finance/installments/{part['id']}/settle/", {
        "financial_account": str(bank.pk), "amount": "10.00", "discount": "150.00", "allow_excess": True}, format="json")

    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "discount_exceeds_balance"
    assert not FinancialTransaction.all_objects.filter(installment_id=part["id"]).exists()


def test_dinheiro_em_turno_ja_fechado_e_recusado(ctx):
    """Antes: o pagamento entrava num turno fechado (o esperado do fechamento ficava sem ele)."""
    from starrp.models import CashSession
    from starrp.services import cash, sales

    session = cash.open_session(ctx.register, ctx.admin, Decimal("50"))
    product = ctx.product(price="10.00", track_stock=False)
    sale = sales.create(ctx.store, ctx.admin, cash_session=session)
    sales.add_item(sale, product, Decimal("1"), ctx.admin)
    CashSession.all_objects.filter(pk=session.pk).update(status=CashSession.Status.CLOSED)  # fechou no meio

    response = ctx.client().post(f"/api/v1/sales/{sale.pk}/payments/",
                                 {"method": str(ctx.methods["cash"].pk), "amount": "10.00"}, format="json")

    assert response.status_code == 409, response.json()
    assert response.json()["error"]["code"] == "session_not_open"


def test_resposta_da_api_nao_vai_para_cache(ctx):
    """Dado privado (e o certificado A1 em /pdv/fiscal-emitter/) não fica em cache de navegador/proxy."""
    ok = ctx.client().get("/api/v1/me/")
    error = ctx.client().get("/api/v1/sales/00000000-0000-0000-0000-000000000000/")
    assert ok["Cache-Control"] == "no-store" and error["Cache-Control"] == "no-store"
