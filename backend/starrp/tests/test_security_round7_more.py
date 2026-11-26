# ruff: noqa: F403, F405
from decimal import Decimal as D
from starrp.models import *  # noqa
V = "/api/v1"


def test_frete_negativo(ctx):
    sup = ctx.user("sup", "supervisor")
    r = ctx.client(sup).post(V + "/logistics/freight-tables/", {"name": "X", "kind": "zip_range", "store": str(ctx.store.pk), "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "-90.00"}]}, format="json")
    assert r.status_code == 400, r.json()


def test_frete_negativo_abate_venda(ctx):
    sup = ctx.user("sup", "supervisor")
    api = ctx.client(sup)
    c = Customer.all_objects.create(account=ctx.account, name="A")
    ad = CustomerAddress.all_objects.create(account=ctx.account, customer=c, zip_code="01310100", label="c")
    t = api.post(V + "/logistics/freight-tables/", {"name": "X", "kind": "zip_range", "store": str(ctx.store.pk), "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "-45.00"}]}, format="json")
    if t.status_code == 400:
        return
    s = api.post(V + "/sales/", {"customer": str(c.pk)}, format="json").json()
    api.post(f"{V}/sales/{s['id']}/items/", {"variant": str(ctx.product(track_stock=False).pk)}, format="json")
    s = api.post(f"{V}/sales/{s['id']}/delivery/", {"address": str(ad.pk), "table": t.json()["id"]}, format="json").json()
    assert D(s["total"]) >= 50, s["total"]


def test_vendedor_apaga_avaliacao_da_propria_venda_na_lista_em_massa(ctx):
    v = ctx.product(track_stock=False)
    rv = Review.all_objects.create(account=ctx.account, store=ctx.store, kind="product", product=v.product, rating=1, public_name="X", status="approved")
    sl = ctx.user("ven", "seller", is_seller=True)
    ctx.client(sl).post(V + "/reviews/bulk/", {"action": "delete", "ids": [str(rv.pk)]}, format="json")
    rv.refresh_from_db()
    assert rv.deleted_at is None


def test_danfe_da_nota_autorizada_nao_muda_por_reenvio(ctx):
    from starrp.tests.test_security_round7_probe import sold, note, _fiscal
    _fiscal(ctx)
    api = ctx.client()
    s = sold(ctx, api, ctx.product(track_stock=False))
    note(ctx, api, s, 1)
    note(ctx, api, s, 1, issuer={"legal_name": "GOLPE LTDA", "cnpj": "1"}, recipient={"name": "Outro", "document": "52998224725"},
         items=[{"n": 1, "description": "FALSO", "quantity": "1", "total": "50"}])
    inv = Invoice.all_objects.get(sale_id=s["id"])
    d = api.get(f"{V}/sales/{s['id']}/invoices/{inv.pk}/danfe/").json()
    assert d["issuer"]["legal_name"] != "GOLPE LTDA" and not any(i["description"] == "FALSO" for i in d["items"])


def test_impressora_fila(ctx, other):
    p = Printer.all_objects.create(account=other.account, store=other.store, name="P")
    r = ctx.client().post(V + "/devices/print-jobs/", {"printer": str(p.pk), "kind": "receipt", "payload": {}}, format="json")
    assert r.status_code == 400
    s = ctx.user("sel", "seller")
    for u in ("devices/printers", "devices/print-jobs", "devices/scales", "assets", "imports", "audit-logs", "integrations"):
        r = ctx.client(s).post(f"{V}/{u}/", {}, format="json")
        assert r.status_code in (403, 405), (u, r.status_code)


def test_notificacao_alheia(ctx):
    a, b = ctx.user("a", "seller"), ctx.user("b", "seller")
    n = Notification.all_objects.create(account=ctx.account, recipient=a, title="x", category="system")
    assert ctx.client(b).get(f"{V}/notifications/{n.pk}/").status_code == 404
    assert ctx.client(b).post(f"{V}/notifications/{n.pk}/read/").status_code == 404
    ctx.client(b).post(V + "/notifications/bulk/", {"action": "delete", "ids": [str(n.pk)]}, format="json")
    n.refresh_from_db()
    assert n.deleted_at is None


def test_admin_staff_comum(ctx, client):
    from django.contrib.auth.models import Permission as P
    u = ctx.user("staff", "manager")
    u.is_staff = True
    u.save()
    u.user_permissions.set(P.objects.all())
    client.force_login(u)
    for path in ("", "starrp/account/", "starrp/product/", "auth/user/", "starrp/stockmovement/", "starrp/fiscalconfig/"):
        r = client.get("/admin/" + path)
        assert r.status_code in (302, 403), (path, r.status_code)
