"""Rodada 8 (ataque): dado malformado vira recusa, DRE é sempre da empresa, quem só consulta não modera."""
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.models import CashMovement, FreightTable, Payment, Review, Sale
from starrp.tests.test_security_round4_money import _boot, _off
from starrp.tests.test_security_round6_sales import new, pay, ret

OFFLINE = "/api/v1/pdv/offline-sales/"
CASH = "/api/v1/pdv/offline-cash/"
BAD = ["x", ["x"], {"a": 1}, 10 ** 40, 1e30, True, "2026-99-99T00:00:00Z", "f20363e2-8c65-4a59-9601-14633c0c2487"]


def _ready(ctx):
    api = ctx.client()
    _boot(api)
    return api, ctx.product(track_stock=False)


@pytest.mark.parametrize("field", ["seller", "operator", "discount_approved_by", "delivery", "addresses", "coupon_code",
                                   "completed_at", "approval_proofs"])
def test_fila_offline_nunca_da_500_com_campo_malformado(ctx, field):
    api, v = _ready(ctx)
    api.raise_request_exception = False
    for bad in BAD:
        value = {"delivery": bad} if field == "addresses" and not isinstance(bad, dict) else bad
        r = api.post(OFFLINE, _off(ctx, v, discount="1.00", total="99.00", **{field: value}), format="json")
        assert r.status_code < 500, (field, bad, r.content)


@pytest.mark.parametrize("where,field", [("items", "id"), ("items", "parent"), ("items", "approved_by"),
                                         ("payments", "installments"), ("payments", "nsu")])
def test_fila_offline_linha_malformada(ctx, where, field):
    api, v = _ready(ctx)
    api.raise_request_exception = False
    for bad in BAD:
        body = _off(ctx, v)
        body[where][0][field] = bad
        assert api.post(OFFLINE, body, format="json").status_code < 500, (field, bad)


def test_hora_sem_fuso_e_textos_longos_nao_travam_a_venda(ctx):
    api, v = _ready(ctx)
    naive = timezone.localtime().replace(tzinfo=None, microsecond=0).isoformat()
    body = _off(ctx, v, completed_at=naive, customer_name="N" * 400, customer_document="1" * 50)
    body["payments"][0]["nsu"] = "9" * 90
    r = api.post(OFFLINE, body, format="json")
    assert r.status_code == 201, r.json()
    sale = Sale.all_objects.get(pk=r.json()["id"])
    assert (len(sale.customer_name), len(sale.customer_document)) == (180, 18)
    assert len(Payment.all_objects.get(sale=sale).nsu) == 40


@pytest.mark.parametrize("amount", ["abc", "NaN", "Infinity", "-5", "1e30", ["1"], {"a": 1}])
def test_caixa_offline_valor_invalido(ctx, amount):
    ctx.require_cash()
    ctx.link(ctx.admin)
    api, _v = _ready(ctx)
    api.raise_request_exception = False
    opening = {"event": "open", "offline_id": "t1", "register": str(ctx.register.pk), "installation_id": "pc-1"}
    assert api.post(CASH, {**opening, "opening_amount": amount}, format="json").status_code == 422
    assert api.post(CASH, {**opening, "opening_amount": "100.00"}, format="json").status_code == 201
    move = {"event": "movement", "offline_id": "m1", "session": "off:t1", "kind": "supply", "reason": "x"}
    assert api.post(CASH, {**move, "amount": amount}, format="json").status_code == 422
    assert not CashMovement.all_objects.filter(offline_id="m1").exists()
    close = {"event": "close", "offline_id": "c1", "session": "off:t1", "counted_amount": amount}
    assert api.post(CASH, close, format="json").status_code == 422


@pytest.mark.parametrize("bad", BAD)
def test_acoes_com_corpo_livre(ctx, bad):
    ctx.account.extra_modules = ["inbound_nfe", "stock"]
    ctx.account.save()
    api, v = _ready(ctx)
    api.raise_request_exception = False
    sid = new(ctx, api, (v, 1))
    for path, body in ((f"sales/{sid}/addresses/", {"delivery": bad}), (f"sales/{sid}/metafields/", {"metafields": bad}),
                       (f"sales/{sid}/customer/", {"seller": bad}), ("commissions/payout/", {"seller": bad}),
                       (f"sales/{sid}/coupon/", {"code": bad}), ("inbound-nfe/sync/", {"config": bad})):
        r = api.post(f"/api/v1/{path}", body, format="json")
        assert r.status_code < 500, (path, body, r.content)


def test_corpo_lista_e_caractere_nulo(ctx):
    ctx.account.extra_modules = ["inbound_nfe", "stock"]
    ctx.account.save()
    api = ctx.client()
    for path in ("inbound-nfe/sync/", f"stores/{ctx.store.pk}/fiscal/certificate/"):
        assert api.post(f"/api/v1/{path}", [{}], format="json").status_code == 400
    assert api.post("/api/v1/catalog/brands/", {"name": "a\x00b"}, format="json").status_code == 400


def test_patch_com_linha_vazia(ctx):
    api = ctx.client()
    r = api.post("/api/v1/logistics/freight-tables/", {"name": "Moto", "kind": "zip_range", "lead_days": 1, "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "10.00"}]}, format="json")
    assert r.status_code == 201, r.json()
    path = f"/api/v1/logistics/freight-tables/{r.json()['id']}/"
    assert api.patch(path, {"ranges": [{}]}, format="json").status_code == 400
    ok = {"zip_start": "01000000", "zip_end": "05999999", "value": "12.00"}
    assert api.patch(path, {"ranges": [ok]}, format="json").status_code == 200
    assert FreightTable.all_objects.get(pk=r.json()["id"]).ranges.filter(deleted_at__isnull=True).get().value == 12
    r = api.post("/api/v1/promotions/tables/", {"name": "Tab", "rules": []}, format="json")
    assert r.status_code == 201, r.json()
    path = f"/api/v1/promotions/tables/{r.json()['id']}/"
    assert api.patch(path, {"rules": [{}]}, format="json").status_code == 400
    assert api.patch(path, {"rules": [{"name": "R", "target": "products", "value": "5", "products": [{}]}]},
                     format="json").status_code == 400
    cat = ctx.product().product.category
    if cat is not None:  # sem `target`/`kind`: valem os padrões, como no POST
        assert api.patch(path, {"rules": [{"name": "R", "value": "5", "categories": [str(cat.pk)]}]},
                         format="json").status_code == 200


def test_dre_e_da_empresa_mesmo_com_filtro_de_vendedor(ctx):
    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    api, v = _ready(ctx)
    one, two = (ctx.user(f"v{i}", "seller", is_seller=True) for i in (1, 2))
    for seller in (one, two):
        sid = new(ctx, api, (v, 1), seller=seller.pk)
        assert pay(ctx, api, sid).status_code == 200
    ret(api, sid, "original_payment")
    base = api.get("/api/v1/reports/dre/").json()
    assert Decimal(base["gross_revenue"]) == 2 * Sale.all_objects.get(pk=sid).subtotal
    for seller in (one, two):
        assert api.get("/api/v1/reports/dre/", {"seller": seller.pk}).json() == base


def test_auditor_nao_modera_avaliacao(ctx):
    api, v = _ready(ctx)
    review = Review.all_objects.create(account=ctx.account, store=ctx.store, product=v.product, rating=5, comment="bom")
    auditor = ctx.client(ctx.user("aud", "auditor"))
    for path, body in (("approve", {}), ("reject", {"reason": "spam"})):
        assert auditor.post(f"/api/v1/reviews/{review.pk}/{path}/", body, format="json").status_code == 403
    assert auditor.get(f"/api/v1/reviews/{review.pk}/").status_code == 200
    marketing = ctx.client(ctx.user("mkt", "marketing"))
    assert marketing.post(f"/api/v1/reviews/{review.pk}/approve/", {}, format="json").status_code == 200
