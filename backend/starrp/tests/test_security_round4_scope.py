"""Rodada 4: escopo, estoque, acesso e cupom."""
from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from starrp.core.errors import InsufficientStock, StateConflict
from starrp.models import (
    Customer, FiscalConfig, InboundNFe, LogisticsRule, ProductBarcode, ProductVariant,
    StockDocument, StockDocumentItem, StockLot, StockMovement, Store,
    UserProfile,
)
from starrp.serializers.finance import FinancialTitleSerializer
from starrp.serializers.stock import StockDocumentSerializer, StockLotSerializer
from starrp.services import cash, checkout, returns, sales, stock, stock_documents
from starrp.services.provisioning import create_store
from starrp.tests.nfe_fixture import UNIT_EAN, nfe_xml


def _mods(ctx, *names):
    ctx.account.extra_modules = list(names)
    ctx.account.save()


def _doc(ctx, kind, lines, wh=None, **kw):
    wh = wh or stock.default_warehouse(ctx.store)
    n = StockDocument.all_objects.count() + 900
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind=kind, number=n, warehouse=wh,
                                           effective_date="2026-11-24", **kw)
    for line in lines:
        StockDocumentItem.all_objects.create(account=ctx.account, document=doc, **line)
    return doc


def _lot(ctx, qty=10):
    v = ctx.product(name="Iogurte", sku="IOG", track_lots=True)
    doc = _doc(ctx, "entry", [{"variant": v, "quantity": Decimal(qty), "unit_cost": Decimal("1"), "lot_number": "L1"}])
    stock_documents.post(doc, ctx.admin)
    return v, StockLot.all_objects.get(variant=v)


def test_t07_mesmo_lote_em_duas_linhas(ctx):
    v, lot = _lot(ctx)
    doc = _doc(ctx, "exit", [{"variant": v, "quantity": Decimal("4"), "lot": lot}, {"variant": v, "quantity": Decimal("4"), "lot": lot}])
    stock_documents.post(doc, ctx.admin)
    lot.refresh_from_db()
    assert lot.quantity == 2


def test_t07b_saida_maior_que_o_lote(ctx):
    v, lot = _lot(ctx)
    other = _doc(ctx, "entry", [{"variant": v, "quantity": Decimal("10"), "unit_cost": Decimal("1"), "lot_number": "L2"}])
    stock_documents.post(other, ctx.admin)
    doc = _doc(ctx, "exit", [{"variant": v, "quantity": Decimal("15"), "lot": lot}])
    with pytest.raises(InsufficientStock):
        stock_documents.post(doc, ctx.admin)
    lot.refresh_from_db()
    assert lot.quantity >= 0


def test_t06_patch_do_lote_com_leitura_velha(ctx, rf):
    """PATCH do lote le, uma venda baixa, o PATCH grava tudo: a baixa some."""
    v, lot = _lot(ctx)
    stale = StockLot.all_objects.get(pk=lot.pk)
    stock.move(v, lot.warehouse, Decimal("-6"), StockMovement.Kind.SALE, source_key="x")
    with ctx.tenant():
        s = StockLotSerializer(stale, data={"lot_number": "L1-A"}, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
    lot.refresh_from_db()
    assert lot.quantity == 4


def test_t06b_patch_do_documento_com_leitura_velha_reabre_o_confirmado(ctx):
    v = ctx.product(name="Cafe", sku="CAF")
    doc = _doc(ctx, "entry", [{"variant": v, "quantity": Decimal("10"), "unit_cost": Decimal("1")}])
    stale = StockDocument.all_objects.get(pk=doc.pk)
    stock_documents.post(doc, ctx.admin)  # confirmou no meio do PATCH
    with ctx.tenant():
        s = StockDocumentSerializer(stale, data={"reason": "x", "items": [
            {"variant": str(v.pk), "quantity": "10", "unit_cost": "1"}]}, partial=True)
        s.is_valid(raise_exception=True)
        with pytest.raises(StateConflict):
            s.save()
    doc.refresh_from_db()
    assert doc.status == "posted" and stock.available(v) == 10


def test_t06c_editar_produto_com_leitura_velha_apaga_o_custo_medio(ctx):
    from starrp.models import Product
    from starrp.services import catalog
    v = ctx.product(name="Cafe", sku="CAF")
    wh = stock.default_warehouse(ctx.store)
    stock.move(v, wh, Decimal("10"), StockMovement.Kind.PURCHASE, unit_cost=Decimal("5"), source_key="a")
    real = ProductVariant.save
    product = Product.all_objects.get(pk=v.product_id)

    def racing(self, *a, **k):  # entre ler as variantes e gravar, outra entrada chega
        if "price" in (k.get("update_fields") or ["price"]) and not racing.done:
            racing.done = True
            stock.move(ProductVariant.all_objects.get(pk=v.pk), wh, Decimal("10"), StockMovement.Kind.PURCHASE,
                       unit_cost=Decimal("15"), source_key="b")
        return real(self, *a, **k)
    racing.done = False
    ProductVariant.save = racing
    try:
        catalog.save_variants(product, [{"id": v.pk, "name": "", "price": Decimal("60")}], ctx.admin)
    finally:
        ProductVariant.save = real
    v.refresh_from_db()
    assert v.average_cost == 10


def test_t08_fiscal_compartilhado_pela_rota_da_filial(ctx):
    b = create_store(ctx.account, name="B")
    cfg = FiscalConfig.all_objects.create(account=ctx.account, name="X", legal_name="X", cnpj="11222333000181",
                                          environment="1", csc_id="1", csc_token="segredo-da-rede")
    Store.all_objects.filter(pk__in=[ctx.store.pk, b.pk]).update(fiscal_config=cfg)
    api = ctx.client(ctx.user("ger", "manager"))  # so a filial A
    api.patch(f"/api/v1/fiscal/configs/{cfg.pk}/", {"environment": "2"}, format="json")
    api.post(f"/api/v1/stores/{ctx.store.pk}/fiscal/", {"environment": "2", "csc_token": "trocado",
                 "local_fiscal_enabled": False}, format="json")
    cfg.refresh_from_db()
    assert cfg.environment == "1"


def test_t08b_filial_aponta_para_dados_fiscais_de_outra(ctx):
    create_store(ctx.account, name="B")
    cfg = FiscalConfig.all_objects.create(account=ctx.account, name="B", legal_name="B", cnpj="11222333000181",
                                          environment="1", csc_id="1", csc_token="segredo-de-B")
    u = ctx.user("ti", "it")
    u.profile.extra_roles.add(ctx.user_role("fiscal"))
    api = ctx.client(u)
    api.patch(f"/api/v1/stores/{ctx.store.pk}/", {"fiscal_config": str(cfg.pk)}, format="json")
    api.post(f"/api/v1/stores/{ctx.store.pk}/fiscal/", {"environment": "2"}, format="json")
    cfg.refresh_from_db()
    assert cfg.environment == "1"


def test_t09_propria_comissao(ctx):
    m = ctx.user("ger", "manager")
    p = UserProfile.all_objects.get(user=m)
    ctx.client(m).patch(f"/api/v1/users/{p.pk}/", {"commission_percent": "100", "is_seller": True}, format="json")
    p.refresh_from_db()
    assert p.commission_percent == 0


def test_t11_fechamento_cego(ctx):
    ctx.require_cash()
    cashier = ctx.user("caixa", "cashier")
    ctx.link(cashier)
    api = ctx.client(cashier)
    s = cash.open_session(ctx.register, cashier, Decimal("100"))
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    sid = api.post("/api/v1/sales/", {}, format="json").json()["id"]
    api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
    api.post(f"/api/v1/sales/{sid}/checkout/", {"payments": [{"method": str(ctx.methods["cash"].pk), "amount": "1000", "tendered": "1000"}]}, format="json")
    moves = api.get(f"/api/v1/cash/movements/?session={s.pk}").json()
    rows = moves.get("results", moves)
    Decimal("100") + sum(Decimal(m["amount"]) for m in rows if m["kind"] == "sale")
    cash.close_session(s, cashier, Decimal("900"))
    hist = api.get(f"/api/v1/cash/sessions/{s.pk}/history/")
    assert b"expected" not in hist.content and b"difference" not in hist.content


def test_t12_link_de_redefinicao_sobrevive_a_troca_de_senha_e_de_email(ctx):
    u = ctx.user("vend", "seller")
    u.email = "velho@x.com"
    u.save()
    APIClient(SERVER_NAME="localhost").post("/api/v1/auth/password-reset/", {"email": "velho@x.com"}, format="json")
    token = mail.outbox[-1].body.split("#token=")[1].split()[0]
    p = UserProfile.all_objects.get(user=u)
    r = ctx.client().patch(f"/api/v1/users/{p.pk}/", {"email": "novo@x.com", "password": "Senha-Do-Admin-99"}, format="json")
    assert r.status_code == 200, r.json()
    r = APIClient(SERVER_NAME="localhost").post("/api/v1/auth/password-reset/confirm/", {"token": token, "password": "Do-Invasor-12345"}, format="json")
    u.refresh_from_db()
    assert r.status_code == 400


def test_t12b_bombardeio_de_links(ctx):
    u = ctx.user("vend", "seller")
    u.email = "v@x.com"
    u.save()
    for _ in range(30):
        APIClient(SERVER_NAME="localhost").post("/api/v1/auth/password-reset/", {"email": "v@x.com"}, format="json")
    from starrp.models import PasswordResetRequest
    assert PasswordResetRequest.objects.filter(used_at=None).count() <= 1


def test_t13_custo_no_audit_log(ctx):
    from starrp.models import Supplier, SupplierProduct
    v = ctx.product()
    sup = Supplier.all_objects.create(account=ctx.account, name="F")
    sp = SupplierProduct.all_objects.create(account=ctx.account, supplier=sup, variant=v, supplier_code="1", last_cost=Decimal("3"))
    ctx.client().patch(f"/api/v1/catalog/supplier-products/{sp.pk}/", {"last_cost": "7.77"}, format="json")
    it = ctx.user("ti", "it", all_stores=True)
    out = ctx.client(it, store=None).get("/api/v1/audit-logs/")
    assert b"7.77" not in out.content


def test_t18_vendedor_ve_devolucoes_dos_colegas(ctx):
    a, b = ctx.user("va", "seller", is_seller=True), ctx.user("vb", "seller", is_seller=True)
    c = Customer.all_objects.create(account=ctx.account, name="Cliente de A")
    sale = sales.create(ctx.store, a, customer=c, seller=a)
    sales.add_item(sale, ctx.product(track_stock=False), Decimal("1"), a)
    sale.refresh_from_db()
    checkout.add_payment(sale, ctx.methods["pix"], sale.total, ctx.admin, nsu="1")
    sale.refresh_from_db()
    checkout.complete(sale, ctx.admin)
    sale.refresh_from_db()
    returns.create(sale, ctx.admin, [{"sale_item": sale.items.get(), "quantity": Decimal("1")}], reason="x")
    api = ctx.client(b)
    rows = api.get("/api/v1/returns/").json()
    rows = rows.get("results", rows)
    assert not rows


@pytest.fixture
def nfe(ctx):
    _mods(ctx, "stock", "inbound_nfe", "finance")
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj="11222333000181")
    LogisticsRule.all_objects.filter(pk=ctx.store.logistics_rule_id).update(allow_manual_conference=True)
    soda = ctx.product(name="Refri", sku="REFRI", price="5.00")
    ProductBarcode.all_objects.create(account=ctx.account, variant=soda, code=UNIT_EAN)
    yog = ctx.product(name="Iogurte Natural", sku="IOG2", price="6.00", track_lots=False)
    api = ctx.client()
    body = api.post("/api/v1/inbound-nfe/import/", {"file": SimpleUploadedFile("n.xml", nfe_xml(), content_type="text/xml")}, format="multipart").json()
    return ctx, soda, yog, body


def test_t30_entrada_da_nota_vira_inventario(nfe):
    ctx, soda, yog, body = nfe
    stockist = ctx.client(ctx.user("est", "stockist"))
    item2 = next(i for i in body["items"] if i["item_number"] == 2)
    stockist.post(f"/api/v1/inbound-nfe/{body['id']}/map-item/", {"item": item2["id"], "variant": str(yog.pk)}, format="json")
    doc = StockDocument.all_objects.get(inbound_nfe_id=body["id"], status="draft")
    stockist.patch(f"/api/v1/stock/documents/{doc.pk}/", {"kind": "exit", "exit_reason": "consumption"}, format="json")
    wh = stock.default_warehouse(ctx.store)
    for v in (soda, yog):
        stock.move(v, wh, Decimal("100"), StockMovement.Kind.INITIAL, unit_cost=Decimal("1"), source_key=f"i{v.pk}")
    stockist.post(f"/api/v1/stock/documents/{doc.pk}/check/", {}, format="json")
    stockist.post(f"/api/v1/stock/documents/{doc.pk}/post/", {}, format="json")
    n = InboundNFe.all_objects.get(pk=body["id"])
    assert not (n.receiving == "received" and stock.available(soda) <= 100)


def test_t19_preco_negativo_pelo_item_da_nota(nfe):
    ctx, soda, yog, body = nfe
    item2 = next(i for i in body["items"] if i["item_number"] == 2)
    ctx.client(ctx.user("est", "stockist")).post(f"/api/v1/inbound-nfe/items/{item2['id']}/create-product/", {"price": "-50"}, format="json")
    v = ProductVariant.all_objects.filter(price__lt=0).first()
    assert v is None


def test_t20_limites(ctx):
    class R:
        account, user, store, allowed_store_ids = ctx.account, ctx.admin, ctx.store, None
        method = "POST"
    with ctx.tenant():
        s = FinancialTitleSerializer(data={"kind": "payable", "description": "x", "total": "10", "installment_count": 5_000_000},
                                     context={"request": R()})
        assert not s.is_valid()


def test_t23_cupom_por_cliente_com_cpf_inventado(ctx):
    from starrp.models import Coupon
    c = Customer.all_objects.create(account=ctx.account, name="Ze", document="52998224725")
    coupon = Coupon.all_objects.create(account=ctx.account, code="UM", value=Decimal("50"), usage_limit_per_customer=1)
    coupon.customers.add(c)
    api = ctx.client(ctx.user("caixa", "cashier"))
    v = ctx.product(track_stock=False)
    ok = 0
    for doc in ("52998224725", "-", "-", "-"):
        sid = api.post("/api/v1/sales/", {"customer": str(c.pk), "customer_document": doc}, format="json").json()["id"]
        api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
        r = api.post(f"/api/v1/sales/{sid}/coupon/", {"code": "UM"}, format="json")
        if r.status_code != 200:
            continue
        r = api.post(f"/api/v1/sales/{sid}/checkout/", {"payments": [{"method": str(ctx.methods["pix"].pk), "amount": r.json()["total"], "nsu": "1"}]}, format="json")
        ok += r.status_code == 200
    assert ok == 1


def test_t25_remove_pagamento_de_turno_fechado(ctx):
    ctx.require_cash()
    cashier = ctx.user("caixa", "cashier")
    ctx.link(cashier)
    api = ctx.client(cashier)
    s = cash.open_session(ctx.register, cashier, Decimal("0"))
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    sid = api.post("/api/v1/sales/", {}, format="json").json()["id"]
    api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
    r = api.post(f"/api/v1/sales/{sid}/payments/", {"method": str(ctx.methods["cash"].pk), "amount": "1000", "tendered": "1000"}, format="json")
    cash.close_session(s, cashier, Decimal("1000"))
    pid = r.json()["payments"][0]["id"]
    r = api.delete(f"/api/v1/sales/{sid}/payments/{pid}/")
    assert r.status_code >= 400
