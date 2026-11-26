# ruff: noqa: F403, F405, E702, E741
from decimal import Decimal as D
from io import BytesIO

import pytest
from django.utils import timezone

from starrp.models import *  # noqa
from starrp.services import stock, pricing, media
from starrp.tests.test_pdv_offline_fiscal import _fiscal, valid_key, nfe_proc

V = "/api/v1"
AP = {"username": "admin-lojateste", "password": "senha123"}


def sold(ctx, api, variant, method="cash", q="1", **kw):
    s = api.post(V + "/sales/", kw, format="json").json()
    s = api.post(f"{V}/sales/{s['id']}/items/", {"variant": str(variant.pk), "quantity": q}, format="json").json()
    r = api.post(f"{V}/sales/{s['id']}/checkout/", {"payments": [{"method": str(ctx.methods[method].pk), "amount": s["total"]}]}, format="json")
    assert r.status_code == 200, r.json()
    return r.json()


def mods(ctx, *m):
    ctx.account.extra_modules = list(m)
    ctx.account.save()


# 1. o caixa com a senha do gerente conclui a devolucao que o gerente autorizou
def test_caixa_com_autorizacao_conclui(ctx):
    op = ctx.user("op", "cashier")
    api = ctx.client(op)
    s = sold(ctx, ctx.client(), ctx.product(track_stock=False), customer=str(Customer.all_objects.create(account=ctx.account, name="A").pk))
    r = api.post(f"{V}/sales/{s['id']}/returns/", {"items": [{"sale_item": s["items"][0]["id"], "quantity": "1"}],
                                                   "refund_method": "store_credit", "reason": "x", "approval": AP}, format="json")
    assert r.status_code == 201, r.json()
    c = api.post(f"{V}/returns/{r.json()['id']}/complete/", {}, format="json")
    assert c.status_code == 200, c.json()


def lots(ctx):
    mods(ctx, "stock")
    v = ctx.product("Iog", track_lots=True)
    w = stock.default_warehouse(ctx.store)
    api = ctx.client()

    def doc(kind, items, post=True):
        d = api.post(V + "/stock/documents/", {"kind": kind, "warehouse": str(w.pk), "effective_date": str(timezone.localdate()), "items": items}, format="json")
        assert d.status_code == 201, d.json()
        p = api.post(f"{V}/stock/documents/{d.json()['id']}/post/", {}, format="json")
        return p
    assert doc("entry", [{"variant": str(v.pk), "quantity": "5", "unit_cost": "1", "lot_number": "A"},
                         {"variant": str(v.pk), "quantity": "10", "unit_cost": "1", "lot_number": "B"}]).status_code == 200
    la, lb = StockLot.all_objects.get(lot_number="A"), StockLot.all_objects.get(lot_number="B")
    return api, v, w, doc, la, lb


# 2. inventario por lote (sem WMS): contei 5 e 10, que eh o que tem -> nada muda
def test_inventario_por_lote(ctx):
    api, v, w, doc, la, lb = lots(ctx)
    r = doc("inventory", [{"variant": str(v.pk), "quantity": "5", "lot": str(la.pk)}, {"variant": str(v.pk), "quantity": "10", "lot": str(lb.pk)}])
    la.refresh_from_db(), lb.refresh_from_db()
    assert (r.status_code, la.quantity, lb.quantity, stock.available(v, w)) == (200, 5, 10, 15)


def test_inventario_duas_linhas_mesmo_produto(ctx):
    api, v, w, doc, la, lb = lots(ctx)
    p = ctx.product("Caneca")
    doc("entry", [{"variant": str(p.pk), "quantity": "15", "unit_cost": "1"}])
    r = doc("inventory", [{"variant": str(p.pk), "quantity": "5"}, {"variant": str(p.pk), "quantity": "10"}])
    assert r.status_code >= 400 or stock.available(p, w) == 15, stock.available(p, w)


# 3. sobra de contagem em produto com lote continua vendavel
def test_sobra_lote_vende(ctx):
    api, v, w, doc, la, lb = lots(ctx)
    r = doc("inventory", [{"variant": str(v.pk), "quantity": "17"}])
    assert r.status_code >= 400 or sum(StockLot.all_objects.filter(variant=v).values_list("quantity", flat=True)) == 17
    if r.status_code == 200:
        sold(ctx, api, v, q="17")


def test_ajuste_respeita_lote(ctx):
    api, v, w, doc, la, lb = lots(ctx)
    r = doc("adjustment", [{"variant": str(v.pk), "quantity": "-2", "lot": str(lb.pk)}])
    la.refresh_from_db(), lb.refresh_from_db()
    assert (r.status_code, la.quantity, lb.quantity) == (200, 5, 8)


def test_inventario_lote_estoque_cancelado_duas_vezes(ctx):
    api, v, w, doc, la, lb = lots(ctx)
    r = doc("inventory", [{"variant": str(v.pk), "quantity": "0"}])
    api.post(f"{V}/stock/documents/{r.json()['id']}/cancel/", {}, format="json")
    la.refresh_from_db(), lb.refresh_from_db()
    assert (la.quantity, lb.quantity, stock.available(v, w)) == (5, 10, 15)


# 4. nota
def note(ctx, api, sale, number, situ="autorizada", total=None, series=77, **kw):
    total = total or sale["total"]
    key = valid_key("11222333000181", "65", series, number)
    res = {"situacao": situ, "chave": key, "protocolo": "135", "xml": nfe_proc(key, "11222333000181", total)}
    return api.post(f"{V}/sales/{sale['id']}/invoices/register/", {
        "document_model": "65", "series": series, "number": number, "environment": "2",
        "totals": {"products": total, "total": total}, "items": [], "result": res, **kw}, format="json")


def test_nota_cancelada_nao_ressuscita(ctx):
    _fiscal(ctx)
    api = ctx.client()
    s = sold(ctx, api, ctx.product(track_stock=False))
    assert note(ctx, api, s, 1).status_code == 200
    inv = Invoice.all_objects.get(sale_id=s["id"])
    assert inv.status == "authorized"
    Invoice.all_objects.filter(pk=inv.pk).update(authorized_at=timezone.now())
    r = api.post(f"{V}/fiscal/invoices/{inv.pk}/cancel/", {"reason": "cliente desistiu da compra toda"}, format="json")
    assert r.status_code == 200, r.json()
    note(ctx, api, s, 1)  # reenvio da fila do desktop
    inv.refresh_from_db()
    assert inv.status == "cancelled", inv.status


def test_cancelar_venda_com_nota_em_contingencia(ctx):
    _fiscal(ctx)
    api = ctx.client()
    s = sold(ctx, api, ctx.product(track_stock=False), method="pix")
    assert note(ctx, api, s, 2, situ="contingencia", emission_type="9").status_code == 200
    assert Invoice.all_objects.get(sale_id=s["id"]).status == "processing"
    r = api.post(f"{V}/sales/{s['id']}/cancel/", {"reason": "cliente desistiu da compra toda"}, format="json")
    note(ctx, api, s, 2)
    inv, sale = Invoice.all_objects.get(sale_id=s["id"]), Sale.all_objects.get(pk=s["id"])
    assert not (inv.status == "authorized" and sale.status == "cancelled"), (r.status_code, inv.status, sale.status)


@pytest.mark.parametrize("bad", [{"totals": {"total": "abc"}}, {"totals": [1]}, {"items": [1]}, {"items": [{"n": "x"}]},
                                 {"items": [{"quantity": "abc"}]}, {"recipient": "x"}, {"items": [{"variant": "zzz"}]}])
def test_register_lixo(ctx, bad):
    _fiscal(ctx)
    api = ctx.client()
    api.raise_request_exception = False
    s = sold(ctx, api, ctx.product(track_stock=False))
    r = note(ctx, api, s, 3, situ="rejeitada", **bad)
    assert r.status_code < 500


def test_register_variante_outra_conta(ctx, other):
    _fiscal(ctx)
    api = ctx.client()
    s = sold(ctx, api, ctx.product(track_stock=False))
    v = other.product("Segredo", sku="SEG")
    r = note(ctx, api, s, 4, items=[{"n": 1, "variant": str(v.pk), "quantity": "1"}])
    it = InvoiceItem.all_objects.filter(variant=v)
    assert r.status_code >= 400 or not it.exists()


# 5. comissao: estornar o lancamento do pagamento devolve a comissao a pagar
def test_estorno_do_pagamento_da_comissao(ctx):
    mods(ctx, "finance")
    sl = ctx.user("ven", "seller", is_seller=True, commission_percent=D(10))
    api = ctx.client()
    sold(ctx, api, ctx.product(track_stock=False), seller=sl.pk)
    bank = FinancialAccount.all_objects.filter(account=ctx.account, kind="bank").first()
    r = api.post(V + "/commissions/payout/", {"seller": sl.pk, "financial_account": str(bank.pk)}, format="json").json()
    rv = api.post(f"{V}/finance/transactions/{r['transaction']}/reverse/", {"reason": "conta errada"}, format="json")
    again = api.post(V + "/commissions/payout/", {"seller": sl.pk, "financial_account": str(bank.pk)}, format="json")
    assert rv.status_code >= 400 or again.status_code == 201, (rv.status_code, again.json())


# 6. promocao nunca aumenta o preco
def test_promocao_nao_aumenta(ctx):
    v = ctx.product("Vaso", price="50.00")
    api = ctx.client()
    r = api.post(V + "/promotions/tables/", {"name": "T", "rules": [{"name": "R", "target": "products", "kind": "percent", "value": "0",
                 "products": [{"product": str(v.product_id), "promotional_price": "90.00", "compare_at_price": "100.00"}]}]}, format="json")
    assert r.status_code >= 400 or pricing.quote(v, ctx.store.pk).unit_price <= 50, pricing.quote(v, ctx.store.pk)


@pytest.mark.parametrize("p", ["abc", "NaN", "1e30", [1]])
def test_aprovar_preco_lixo(ctx, p):
    mods(ctx, "pricing")
    v = ctx.product("Vaso", price="50.00")
    c = PriceCheck.all_objects.create(account=ctx.account, variant=v, status="pending", suggested_price=D(60))
    api = ctx.client()
    api.raise_request_exception = False
    assert api.post(f"{V}/price-checks/{c.pk}/approve/", {"price": p}, format="json").status_code < 500


# 7. foto em pe do celular continua em pe
def test_exif(ctx, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from PIL import Image as P
    im = P.new("RGB", (3000, 1500))
    ex = P.Exif()
    ex[0x0112] = 6  # girar 90
    b = BytesIO()
    im.save(b, "JPEG", exif=ex)
    b.seek(0)
    b.name = "f.jpg"
    r = media.store_upload(ctx.account, ctx.admin, b)
    out = P.open(r.file.path)

    assert out.getexif().get(0x0112) == 6 or out.height > out.width


# 8. vendedor apaga avaliacao alheia
def test_vendedor_nao_apaga_avaliacao(ctx):
    v = ctx.product(track_stock=False)
    rv = Review.all_objects.create(account=ctx.account, store=ctx.store, kind="product", product=v.product, rating=1, public_name="X", status="approved")
    sl = ctx.user("ven", "seller", is_seller=True)
    r = ctx.client(sl).delete(f"{V}/reviews/{rv.pk}/")
    assert r.status_code == 403, r.status_code


# 9. patrimonio: baixar muda a situacao; mover muda o local; baixa nao se apaga
def test_patrimonio(ctx):
    mods(ctx, "assets", "stock")
    api = ctx.client()
    w = stock.default_warehouse(ctx.store)
    a = api.post(V + "/assets/", {"description": "PC", "purchase_price": "1000"}, format="json").json()
    m = api.post(V + "/assets/movements/", {"asset": a["id"], "to_location": str(w.pk)}, format="json")
    d = api.post(V + "/assets/disposals/", {"asset": a["id"], "kind": "scrapped", "reason": "x"}, format="json")
    obj = Asset.all_objects.get(pk=a["id"])
    assert (m.status_code, d.status_code) == (201, 201), (m.json(), d.json())
    assert obj.location_id == w.pk and obj.status == "disposed", (obj.location_id, obj.status)


# 10. perfil fiscal do sistema
def test_perfil_sistema(ctx):
    api = ctx.client()
    p = FiscalProfile.all_objects.filter(account=ctx.account, is_system=True).first()
    api.patch(f"{V}/fiscal/profiles/{p.pk}/", {"is_system": False}, format="json")
    assert api.delete(f"{V}/fiscal/profiles/{p.pk}/").status_code == 409
    q = FiscalProfile.all_objects.filter(account=ctx.account, is_system=True).exclude(pk=p.pk).first()
    api.patch(f"{V}/fiscal/profiles/{q.pk}/", {"is_default": True}, format="json")
    assert FiscalProfile.all_objects.filter(account=ctx.account, is_default=True).count() <= 1


# 11. kit dentro de kit
def test_kit_de_kit_baixa(ctx):
    mods(ctx, "stock")
    a = ctx.product("A", sku="A")
    w = stock.default_warehouse(ctx.store)
    stock.move(a, w, D(10), "initial", unit_cost=D(5))
    api = ctx.client()
    k1, k2 = ctx.product("K1", sku="K1", type="kit", track_stock=False), ctx.product("K2", sku="K2", type="kit", track_stock=False)
    r1 = api.post(V + "/catalog/components/", {"kit": str(k1.product_id), "component": str(a.pk), "quantity": "2"}, format="json")
    r2 = api.post(V + "/catalog/components/", {"kit": str(k2.product_id), "component": str(k1.pk), "quantity": "1"}, format="json")
    assert r1.status_code == 201, r1.json()
    if r2.status_code == 201:
        sold(ctx, api, k2)
        assert stock.available(a, w) == 8 and SaleItem.all_objects.get(variant=k2).unit_cost == 10


# 12. imagem: excluir usada; PATCH nao troca arquivo
def test_imagem(ctx):
    api = ctx.client()
    from django.core.files.uploadedfile import SimpleUploadedFile as F
    for n, c in (("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"), ("a.html", b"<script>1</script>"), ("../../x.png", b"GIF89a<script>")):
        assert api.post(V + "/catalog/images/", {"file": F(n, c, "image/png")}, format="multipart").status_code in (400, 422)


# 13. metacampo / tags lixo
@pytest.mark.parametrize("meta", [{"a": {"b": 1}}, {"a" * 61: 1}, {"x": [1]}, "x", {"a": 1e308}])
def test_metafield_lixo(ctx, meta):
    api = ctx.client()
    api.raise_request_exception = False
    v = ctx.product()
    assert api.patch(f"{V}/catalog/products/{v.product_id}/", {"metafields": meta}, format="json").status_code < 500
    assert api.patch(f"{V}/catalog/products/{v.product_id}/", {"tags": ["x" * 5000, "", None, 1]}, format="json").status_code < 500


# 14. importacao que ninguem processa
def test_import(ctx):
    api = ctx.client()
    r = api.post(V + "/imports/", {"resource": "products", "rows": [{"name": "A"}]}, format="json")
    assert r.status_code >= 400 or ImportJob.all_objects.get(pk=r.json()["id"]).status != "queued"
