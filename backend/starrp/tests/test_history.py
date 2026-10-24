"""Histórico de cada registro: auditoria com o que mudou + acontecimentos do registro, paginado."""
from decimal import Decimal

from starrp.services import stock


def test_alteracao_mostra_o_que_mudou_e_quem_fez(ctx):
    api = ctx.client()
    brand = api.post("/api/v1/catalog/brands/", {"name": "Acme"}, format="json").json()
    api.patch(f"/api/v1/catalog/brands/{brand['id']}/", {"name": "Acme Brasil"}, format="json")

    body = api.get(f"/api/v1/catalog/brands/{brand['id']}/history/").json()

    assert body["count"] == 2
    latest, first = body["results"]
    assert (latest["label"], first["label"]) == ("Alterado", "Criado")
    assert {"field": "Name", "from": "Acme", "to": "Acme Brasil"} in latest["changes"] or \
        any(c["from"] == "Acme" and c["to"] == "Acme Brasil" for c in latest["changes"])
    assert latest["by"]


def test_documento_confirmado_aparece_no_historico_e_pagina(ctx):
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    api = ctx.client()
    variant = ctx.product(name="Caneta", sku="CAN", price="2.00")
    doc = api.post("/api/v1/stock/documents/", {
        "kind": "entry", "warehouse": str(stock.default_warehouse(ctx.store).pk), "effective_date": "2026-10-20",
        "items": [{"variant": str(variant.pk), "quantity": "5", "unit_cost": "1.00"}],
    }, format="json").json()
    api.post(f"/api/v1/stock/documents/{doc['id']}/post/", {}, format="json")

    full = api.get(f"/api/v1/stock/documents/{doc['id']}/history/").json()
    first_page = api.get(f"/api/v1/stock/documents/{doc['id']}/history/?page_size=1").json()

    assert [row["label"] for row in full["results"]][:1] == ["Confirmado"]
    assert "Criado" in [row["label"] for row in full["results"]]
    assert first_page["count"] == full["count"] and len(first_page["results"]) == 1 and first_page["next"]
    assert stock.available(variant) == Decimal("5")
