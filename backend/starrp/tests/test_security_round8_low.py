"""Rodada 8 (baixas): nota já cancelada na SEFAZ fica registrada, devolução por partes, validade da autorização, foto PNG."""
from datetime import timedelta
from decimal import Decimal as D
from io import BytesIO

import pytest
from django.utils import timezone

from starrp.core.errors import StateConflict
from starrp.models import Invoice, Sale, SaleReturn, StockBalance, StorageBin, Warehouse
from starrp.services import invoice_cancel, media, reports, returns, stock
from starrp.tests.test_pdv_offline_fiscal import _fiscal
from starrp.tests.test_security_round6_sales import S, new, pay, ret
from starrp.tests.test_security_round7_probe import V, note, sold

REASON = "cliente desistiu da compra toda"


def test_segunda_nota_recusada_nao_desfaz_a_primeira(ctx, monkeypatch):
    _fiscal(ctx)
    api = ctx.client()
    sale = sold(ctx, api, ctx.product(track_stock=False), method="pix")
    notes = [Invoice.all_objects.create(
        account=ctx.account, store=ctx.store, sale_id=sale["id"], document_model=model, series=1, number=n, environment="2",
        status="authorized", provider="acbrlib", authorized_at=timezone.now(), total="10") for n, model in ((1, "65"), (2, "55"))]
    sent, failing = [], [True]

    def send(invoice, reason):
        if sent and failing[0]:
            raise StateConflict("A SEFAZ não confirmou.")
        sent.append(invoice.number)
        return f"P{invoice.number}"

    monkeypatch.setattr(invoice_cancel, "_send_event", send)
    r = api.post(f"{V}/sales/{sale['id']}/cancel/", {"reason": REASON}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_cancel_partial", r.json()
    for n in notes:
        n.refresh_from_db()
    by_status = sorted(n.status for n in notes)
    assert by_status == ["authorized", "cancelled"] and S(sale["id"]).status == Sale.Status.COMPLETED
    assert next(n for n in notes if n.status == "cancelled").cancel_protocol == f"P{sent[0]}"

    failing[0] = False  # a nova tentativa segue só com a que faltou
    r = api.post(f"{V}/sales/{sale['id']}/cancel/", {"reason": REASON}, format="json")
    assert r.status_code == 200, r.json()
    assert len(sent) == 2 and S(sale["id"]).status == Sale.Status.CANCELLED
    assert not Invoice.all_objects.filter(sale_id=sale["id"], status="authorized").exists()


def test_devolucao_por_partes_com_endereco_desativado(ctx):
    w = stock.default_warehouse(ctx.store)
    Warehouse.all_objects.filter(pk=w.pk).update(uses_bins=True)
    w.refresh_from_db()
    v = ctx.product(price="10.00")
    a, b = (StorageBin.all_objects.create(account=ctx.account, warehouse=w, code=c, kind="picking") for c in ("A1", "B1"))
    for place in (a, b):
        stock.move(v, w, D(2), "purchase", bin=place, unit_cost=D(1))
    api = ctx.client()
    sid = new(ctx, api, (v, 4))
    assert pay(ctx, api, sid).status_code == 200
    StorageBin.all_objects.filter(pk=a.pk).update(is_active=False)
    for _ in range(4):
        returns.complete(ret(api, sid, "original_payment"), ctx.admin)
    moves = stock.StockMovement.all_objects.filter(kind="sale_return", variant=v)
    back = {}
    for move in moves:
        back[move.bin_id] = back.get(move.bin_id, D(0)) + move.quantity
    assert back == {b.pk: D(4)}, back  # nada volta para o desativado, e o total fecha
    assert StockBalance.all_objects.get(variant=v, warehouse=w).quantity == 4


def test_autorizacao_da_devolucao_vale_24_horas(ctx):
    op = ctx.user("op", "cashier")
    api = ctx.client(op)
    sid = new(ctx, ctx.client(), (ctx.product(track_stock=False), 1))
    assert pay(ctx, ctx.client(), sid).status_code == 200
    item = S(sid).items.get()
    r = api.post(f"{V}/sales/{sid}/returns/", {
        "items": [{"sale_item": str(item.pk), "quantity": "1"}], "refund_method": "original_payment", "reason": "x",
        "approval": {"username": "admin-lojateste", "password": "senha123"}}, format="json")
    assert r.status_code == 201, r.json()
    SaleReturn.all_objects.filter(pk=r.json()["id"]).update(created_at=timezone.now() - timedelta(hours=25))
    path = f"{V}/returns/{r.json()['id']}/complete/"
    assert api.post(path, {}, format="json").status_code == 403
    assert ctx.client().post(path, {}, format="json").status_code == 200


def test_nota_rejeitada_nao_derruba_a_contingencia(ctx):
    _fiscal(ctx)
    api = ctx.client()
    sale = sold(ctx, api, ctx.product(track_stock=False), method="pix")
    assert note(ctx, api, sale, 2, situ="contingencia", emission_type="9").status_code == 200
    assert note(ctx, api, sale, 3, situ="rejeitada").status_code == 200
    assert Invoice.all_objects.get(sale_id=sale["id"], number=2).status == "processing"
    r = api.post(f"{V}/sales/{sale['id']}/cancel/", {"reason": REASON}, format="json")
    assert r.status_code == 409, r.json()


def test_faturamento_liquido_por_produto(ctx):
    """A receita da curva e do relatório por produto já sai com a parte do produto no desconto da venda."""
    api = ctx.client()
    v = ctx.product(price="100.00", track_stock=False)
    sid = new(ctx, api, (v, 1))
    assert api.post(f"{V}/sales/{sid}/discount/", {"amount": "30.00"}, format="json").status_code == 200
    assert pay(ctx, api, sid).status_code == 200
    items = reports._items(Sale.all_objects.filter(pk=sid))
    net = reports.net_by(items, "variant__product_id")[v.product_id][0]
    assert reports.money(net) == D("70.00"), net


def test_patrimonio_nao_reescreve_o_historico(ctx):
    ctx.account.extra_modules = ["assets", "stock"]
    ctx.account.save()
    api = ctx.client()
    asset = api.post(V + "/assets/", {"description": "PC", "purchase_price": "1000"}, format="json").json()
    row = api.post(V + "/assets/disposals/", {"asset": asset["id"], "kind": "scrapped", "reason": "x"}, format="json").json()
    assert api.delete(f"{V}/assets/disposals/{row['id']}/").status_code == 405
    assert api.patch(f"{V}/assets/disposals/{row['id']}/", {"kind": "sold"}, format="json").status_code == 405


@pytest.mark.parametrize("kind", ["PNG", "JPEG"])
def test_foto_sai_em_pe_e_sem_dados_da_camera(ctx, settings, tmp_path, kind):
    from PIL import Image as Pillow

    settings.MEDIA_ROOT = tmp_path
    exif = Pillow.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "Camera"
    data = BytesIO()
    Pillow.new("RGB", (300, 150)).save(data, kind, exif=exif)
    data.seek(0)
    data.name = "foto"
    out = Pillow.open(media.store_upload(ctx.account, ctx.admin, data).file.path)
    assert out.height > out.width and not out.getexif()


@pytest.mark.parametrize("bad", [["x"], {"a": 1}, -1, 1e30, None])
def test_bootstrap_com_terminal_malformado(ctx, bad):
    r = ctx.client().post(f"{V}/pdv/bootstrap/", {"installation_id": bad}, format="json")
    assert r.status_code == 422, r.content


@pytest.mark.parametrize("report", ["cupons", "categorias", "avaliacoes", "entradas-e-saidas"])
def test_exportar_com_caractere_de_controle_no_filtro(ctx, report):
    ctx.account.extra_modules = ["stock", "finance"]
    ctx.account.save()
    r = ctx.client().get(f"{V}/reports/book/{report}/export/", {"seller": "a\x00", "kind": "a\x01", "status": "b\x02"})
    assert r.status_code < 500, r.status_code
