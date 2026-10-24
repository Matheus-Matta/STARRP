"""Entrada por NF-e: importar o XML, casar itens, aprender o vínculo e receber."""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from starrp.models import (
    FinancialTitle, InboundNFe, ProductBarcode, ProductVariant, Store, SupplierProduct,
)
from starrp.services import stock

from .nfe_fixture import UNIT_EAN, nfe_xml


@pytest.fixture
def setup(ctx):
    ctx.account.extra_modules = ["stock", "inbound_nfe", "finance"]
    ctx.account.save()
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj="11222333000181")
    soda = ctx.product(name="Refrigerante Lata", sku="REFRI", price="5.00")
    ProductBarcode.all_objects.create(account=ctx.account, variant=soda, code=UNIT_EAN)
    yogurt = ctx.product(name="Iogurte Natural", sku="IOG", price="6.00", track_lots=True)
    return ctx, soda, yogurt


def _import(api, xml=None):
    upload = SimpleUploadedFile("nota.xml", xml or nfe_xml(), content_type="text/xml")
    return api.post("/api/v1/inbound-nfe/import/", {"file": upload}, format="multipart")


def test_importa_e_casa_caixa_pelo_ean_da_unidade(setup):
    """A caixa com 12 casa pelo EAN tributável (a lata) com fator 12; o fornecedor é cadastrado."""
    ctx, soda, _ = setup
    response = _import(ctx.client())

    assert response.status_code == 201, response.json()
    body = response.json()
    items = {item["item_number"]: item for item in body["items"]}
    assert items[1]["variant"] == str(soda.pk) and Decimal(items[1]["conversion_factor"]) == Decimal("12")
    assert items[2]["variant"] is None
    assert body["stage"] == "pending_mapping"
    assert body["supplier_name"] == "Distribuidora Exemplo"


def test_receber_converte_unidade_soma_frete_ipi_no_custo_e_traz_lote_e_duplicatas(setup):
    """2 CX × 12 = 24 UN a (48 + 2,40 frete + 2,40 IPI) / 24 = R$ 2,20; lote e validade vêm do rastro."""
    ctx, soda, yogurt = setup
    api = ctx.client()
    nfe = _import(api).json()
    item2 = next(i for i in nfe["items"] if i["item_number"] == 2)
    blocked = api.post(f"/api/v1/inbound-nfe/{nfe['id']}/receive/",
                       {"warehouse": str(stock.default_warehouse(ctx.store).pk)}, format="json")
    api.post(f"/api/v1/inbound-nfe/{nfe['id']}/map-item/", {"item": item2["id"], "variant": str(yogurt.pk)},
             format="json")
    received = api.post(f"/api/v1/inbound-nfe/{nfe['id']}/receive/",
                        {"warehouse": str(stock.default_warehouse(ctx.store).pk), "post": True}, format="json")

    assert blocked.json()["error"]["code"] == "nfe_unmapped"
    assert received.status_code == 201, received.json()
    assert stock.available(soda) == Decimal("24")
    assert ProductVariant.all_objects.get(pk=soda.pk).last_cost == Decimal("2.2000")
    lot = yogurt.lots.get()
    assert (lot.lot_number, str(lot.expires_at), lot.quantity) == ("LT-778", "2026-11-30", Decimal("10.000"))
    assert InboundNFe.all_objects.get(pk=nfe["id"]).receiving == InboundNFe.Receiving.RECEIVED
    title = FinancialTitle.all_objects.get(inbound_nfe_id=nfe["id"])
    assert title.kind == "payable" and [i.amount for i in title.installments.all()] == [Decimal("41.40")] * 2


def test_vinculo_confirmado_casa_sozinho_na_proxima_nota(setup):
    """O operador vincula uma vez; a nota seguinte do mesmo fornecedor já vem casada."""
    ctx, _, yogurt = setup
    api = ctx.client()
    first = _import(api).json()
    item2 = next(i for i in first["items"] if i["item_number"] == 2)
    api.post(f"/api/v1/inbound-nfe/{first['id']}/map-item/", {"item": item2["id"], "variant": str(yogurt.pk)},
             format="json")

    second = _import(api, nfe_xml(key="35261012345678000199550010000012351000012351", number="1235")).json()

    assert SupplierProduct.all_objects.filter(supplier_code="REF-IOG", variant=yogurt).exists()
    assert all(item["variant"] for item in second["items"])
    # Tudo vinculado: a entrada já nasceu em rascunho, esperando a conferência.
    assert second["stage"] == "checking" and second["entry"]["status"] == "draft"


def test_recusa_nota_repetida_de_outra_empresa_e_xml_perigoso(setup):
    """Mesma chave = 409; destinatário de outro CNPJ = 422; DOCTYPE (XXE) recusado."""
    ctx, _, _ = setup
    api = ctx.client()
    _import(api)

    again = _import(api)
    other = _import(api, nfe_xml(key="35261012345678000199550010000099991000099991", recipient="99888777000166"))
    evil = _import(api, b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')

    assert again.status_code == 409 and again.json()["error"]["code"] == "nfe_duplicate"
    assert other.status_code == 422 and other.json()["error"]["code"] == "nfe_other_recipient"
    assert evil.status_code == 422 and evil.json()["error"]["code"] == "nfe_invalid"


def test_conferencia_com_quantidade_diferente_marca_divergencia(setup):
    """A entrada nasce em rascunho; conferido menos do que a nota diz, a nota fica DIVERGENTE."""
    ctx, soda, yogurt = setup
    api = ctx.client()
    nfe = _import(api).json()
    item2 = next(i for i in nfe["items"] if i["item_number"] == 2)
    api.post(f"/api/v1/inbound-nfe/{nfe['id']}/map-item/", {"item": item2["id"], "variant": str(yogurt.pk)},
             format="json")
    doc = api.post(f"/api/v1/inbound-nfe/{nfe['id']}/receive/",
                   {"warehouse": str(stock.default_warehouse(ctx.store).pk)}, format="json").json()
    items = [dict(i) for i in doc["items"]]
    for item in items:
        if item["variant"] == str(soda.pk):
            item["quantity"] = "23.000"  # chegou uma lata a menos
    api.patch(f"/api/v1/stock/documents/{doc['id']}/", {"items": items}, format="json")

    unchecked = api.post(f"/api/v1/stock/documents/{doc['id']}/post/", {}, format="json")
    checked = api.post(f"/api/v1/stock/documents/{doc['id']}/check/", {}, format="json")
    posted = api.post(f"/api/v1/stock/documents/{doc['id']}/post/", {}, format="json")

    assert unchecked.status_code == 422 and unchecked.json()["error"]["code"] == "conference_required"
    assert checked.status_code == 200 and checked.json()["checked_at"]
    assert posted.status_code == 200, posted.json()
    assert stock.available(soda) == Decimal("23")
    assert InboundNFe.all_objects.get(pk=nfe["id"]).receiving == InboundNFe.Receiving.DIVERGENT
