"""Entrada por NF-e: importar o XML, casar itens, aprender o vínculo e receber."""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from starrp.models import (
    FinancialTitle, InboundNFe, LogisticsSettings, ProductBarcode, ProductVariant, ReceivingDivergence, Store,
    SupplierProduct,
)
from starrp.services import stock

from .nfe_fixture import UNIT_EAN, nfe_xml


@pytest.fixture
def setup(ctx):
    ctx.account.extra_modules = ["stock", "inbound_nfe", "finance"]
    ctx.account.save()
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj="11222333000181")
    # A maioria dos testes aprova direto ("receber e aprovar"): isso é conferência manual.
    LogisticsSettings.all_objects.update_or_create(store=ctx.store, defaults={"account": ctx.account,
                                                                              "allow_manual_conference": True})
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


def test_voltar_passos_desvincula_descarta_conferencia_e_desfaz_recebimento(setup):
    """Vinculou errado e já recebeu: desfazer o recebimento estorna o estoque e cancela as contas
    a pagar; desvincular esquece o aprendido; vincular certo e receber de novo gera tudo outra vez."""
    ctx, soda, yogurt = setup
    api = ctx.client()
    nfe = _import(api).json()
    url = f"/api/v1/inbound-nfe/{nfe['id']}"
    item1 = next(i for i in nfe["items"] if i["item_number"] == 1)
    item2 = next(i for i in nfe["items"] if i["item_number"] == 2)
    wrong = ctx.product(name="Água Mineral", sku="AGUA", price="3.00")
    api.post(f"{url}/map-item/", {"item": item2["id"], "variant": str(wrong.pk)}, format="json")
    draft = api.get(f"{url}/").json()["entry"]
    api.post(f"/api/v1/stock/documents/{draft['id']}/check/", {}, format="json")
    api.post(f"/api/v1/stock/documents/{draft['id']}/post/", {}, format="json")
    assert stock.available(wrong) == Decimal("10")

    locked = api.post(f"/api/v1/inbound-nfe/items/{item2['id']}/unmap/", {}, format="json")
    no_reason = api.post(f"{url}/undo-receipt/", {"reason": ""}, format="json")
    undone = api.post(f"{url}/undo-receipt/", {"reason": "Item 2 vinculado ao produto errado"}, format="json")
    unmapped = api.post(f"/api/v1/inbound-nfe/items/{item2['id']}/unmap/", {}, format="json")

    assert locked.status_code == 409 and locked.json()["error"]["code"] == "nfe_already_received"
    assert no_reason.status_code == 422
    assert undone.status_code == 200 and undone.json()["stage"] == "pending_receipt", undone.json()
    assert stock.available(wrong) == Decimal("0") and stock.available(soda) == Decimal("0")
    assert FinancialTitle.all_objects.get(inbound_nfe_id=nfe["id"]).status == "cancelled"
    assert unmapped.status_code == 200 and unmapped.json()["variant"] is None
    assert not SupplierProduct.all_objects.filter(supplier_code="REF-IOG", variant=wrong, confirmed=True).exists()

    # Ignorar e voltar a usar um item com a conferência aberta descarta o rascunho e refaz.
    api.post(f"{url}/map-item/", {"item": item2["id"], "variant": str(yogurt.pk)}, format="json")
    first_draft = api.get(f"{url}/").json()["entry"]["id"]
    api.post(f"/api/v1/inbound-nfe/items/{item1['id']}/ignore/", {}, format="json")
    back = api.post(f"/api/v1/inbound-nfe/items/{item1['id']}/unignore/", {}, format="json")
    state = api.get(f"{url}/").json()
    assert back.json()["variant"] == str(soda.pk) and not back.json()["ignored"]
    assert state["stage"] == "checking" and state["entry"]["id"] != first_draft

    # Descartar a conferência volta para "gerar entrada"; receber de novo gera novas contas a pagar.
    discarded = api.post(f"{url}/discard-entry/", {}, format="json").json()
    assert discarded["stage"] == "pending_receipt" and discarded["entry"] is None
    api.post(f"{url}/receive/", {"post": True}, format="json")
    assert stock.available(yogurt) == Decimal("10") and stock.available(soda) == Decimal("24")
    assert FinancialTitle.all_objects.filter(inbound_nfe_id=nfe["id"], status="open").count() == 1


def test_desfazer_recebimento_com_duplicata_paga_e_recusado(setup):
    ctx, _, yogurt = setup
    api = ctx.client()
    nfe = _import(api).json()
    item2 = next(i for i in nfe["items"] if i["item_number"] == 2)
    api.post(f"/api/v1/inbound-nfe/{nfe['id']}/map-item/", {"item": item2["id"], "variant": str(yogurt.pk)},
             format="json")
    api.post(f"/api/v1/inbound-nfe/{nfe['id']}/receive/", {"post": True}, format="json")
    FinancialTitle.all_objects.get(inbound_nfe_id=nfe["id"]).installments.filter(number=1).update(
        paid_amount=Decimal("41.40"))

    refused = api.post(f"/api/v1/inbound-nfe/{nfe['id']}/undo-receipt/", {"reason": "Teste de estorno"}, format="json")

    assert refused.status_code == 409 and refused.json()["error"]["code"] == "title_paid"
    assert stock.available(yogurt) == Decimal("10")  # nada foi estornado
    assert InboundNFe.all_objects.get(pk=nfe["id"]).receiving == InboundNFe.Receiving.RECEIVED


def _draft(api, ctx, yogurt):
    nfe = _import(api).json()
    item2 = next(i for i in nfe["items"] if i["item_number"] == 2)
    api.post(f"/api/v1/inbound-nfe/{nfe['id']}/map-item/", {"item": item2["id"], "variant": str(yogurt.pk)},
             format="json")
    return nfe, api.get(f"/api/v1/inbound-nfe/{nfe['id']}/").json()["entry"]["id"]


def test_conferencia_manual_com_item_incorreto_entra_ajustada_e_registra_o_erro(setup):
    """Lata: correta. Iogurte: chegaram 9 (nota 10), 1 avariado → entram 8; na aprovação o
    estoque entra ajustado e o erro de entrada fica registrado com o motivo."""
    ctx, soda, yogurt = setup
    api = ctx.client()
    nfe, doc_id = _draft(api, ctx, yogurt)
    doc = api.get(f"/api/v1/stock/documents/{doc_id}/").json()
    assert doc["manual_conference"] is True
    rows = {r["variant"]: r for r in doc["items"]}
    soda_row, yogurt_row = rows[str(soda.pk)], rows[str(yogurt.pk)]

    incomplete = api.post(f"/api/v1/stock/documents/{doc_id}/check/",
                          {"lines": [{"item": soda_row["id"], "ok": True}]}, format="json")
    no_reason = api.post(f"/api/v1/stock/documents/{doc_id}/check/", {"lines": [
        {"item": soda_row["id"], "ok": True}, {"item": yogurt_row["id"], "ok": False, "arrived": 9, "accepted": 8}]},
        format="json")
    checked = api.post(f"/api/v1/stock/documents/{doc_id}/check/", {"lines": [
        {"item": soda_row["id"], "ok": True},
        {"item": yogurt_row["id"], "ok": False, "arrived": "9", "accepted": "8", "reason": "damaged",
         "notes": "1 pote amassado, 1 faltou"}]}, format="json")
    posted = api.post(f"/api/v1/stock/documents/{doc_id}/post/", {}, format="json")

    assert incomplete.json()["error"]["code"] == "conference_incomplete"
    assert no_reason.json()["error"]["code"] == "divergence_reason_required"
    assert checked.status_code == 200 and checked.json()["conference_mode"] == "manual", checked.json()
    assert posted.status_code == 200, posted.json()
    assert stock.available(soda) == Decimal("24") and stock.available(yogurt) == Decimal("8")
    assert InboundNFe.all_objects.get(pk=nfe["id"]).receiving == InboundNFe.Receiving.DIVERGENT
    error = ReceivingDivergence.all_objects.get()
    assert (error.expected_quantity, error.arrived_quantity, error.accepted_quantity, error.reason) == (
        Decimal("10"), Decimal("9"), Decimal("8"), "damaged")
    assert error.supplier_id is not None and error.mode == "manual"
    listed = api.get("/api/v1/stock/divergences/", {"inbound_nfe": nfe["id"]}).json()["results"]
    assert listed[0]["difference"] == "-1.000" and listed[0]["nfe_number"]


def test_sem_permissao_da_logistica_so_confere_lendo_os_codigos(setup):
    ctx, soda, yogurt = setup
    LogisticsSettings.all_objects.filter(store=ctx.store).update(allow_manual_conference=False)
    api = ctx.client()
    _, doc_id = _draft(api, ctx, yogurt)
    doc = api.get(f"/api/v1/stock/documents/{doc_id}/").json()

    manual = api.post(f"/api/v1/stock/documents/{doc_id}/check/",
                      {"lines": [{"item": r["id"], "ok": True} for r in doc["items"]]}, format="json")
    typed = api.post(f"/api/v1/stock/documents/{doc_id}/check/", {}, format="json")
    scanned = api.post(f"/api/v1/stock/documents/{doc_id}/check/",
                       {"codes": [UNIT_EAN] * 23 + ["IOG"] * 10}, format="json")
    api.post(f"/api/v1/stock/documents/{doc_id}/post/", {}, format="json")

    assert doc["manual_conference"] is False
    assert manual.json()["error"]["code"] == typed.json()["error"]["code"] == "manual_conference_disabled"
    assert scanned.status_code == 200, scanned.json()
    # A leitura achou uma lata a menos: o erro também é registrado (motivo "faltou").
    error = ReceivingDivergence.all_objects.get()
    assert (error.variant_id, error.reason, error.mode) == (soda.pk, "missing", "scan")


def test_item_da_nota_e_da_entrada_trazem_os_volumes_do_produto(setup):
    """Guarda-roupa em 3 caixas: a nota e a conferência mostram os volumes para marcar."""
    from starrp.models import ProductVolume

    ctx, soda, yogurt = setup
    for number, description in ((1, "Laterais"), (2, "Portas"), (3, "Ferragens")):
        ProductVolume.all_objects.create(account=ctx.account, variant=yogurt, number=number, description=description)
    api = ctx.client()
    nfe, doc_id = _draft(api, ctx, yogurt)

    nfe_items = {i["variant"]: i for i in api.get(f"/api/v1/inbound-nfe/{nfe['id']}/").json()["items"]}
    doc_items = {i["variant"]: i for i in api.get(f"/api/v1/stock/documents/{doc_id}/").json()["items"]}

    assert [v["description"] for v in nfe_items[str(yogurt.pk)]["volumes"]] == ["Laterais", "Portas", "Ferragens"]
    assert len(doc_items[str(yogurt.pk)]["volumes"]) == 3 and doc_items[str(soda.pk)]["volumes"] == []
