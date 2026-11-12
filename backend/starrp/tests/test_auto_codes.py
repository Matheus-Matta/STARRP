"""Código que o usuário não precisa digitar: vazio, o sistema gera (e nunca repete)."""
import re


def test_caixa_gera_o_codigo_pelo_nome_e_nao_repete(ctx):
    api = ctx.client()
    url = "/api/v1/cash/registers/"
    first = api.post(url, {"name": "Caixa da Frente", "store": str(ctx.store.pk)}, format="json")
    second = api.post(url, {"name": "Caixa da Frente", "store": str(ctx.store.pk)}, format="json")
    typed = api.post(url, {"name": "Balcão", "code": "B1", "store": str(ctx.store.pk)}, format="json")

    assert first.status_code == 201, first.json()
    assert first.json()["code"] == "CAIXA-DA-FRENTE" and second.json()["code"] == "CAIXA-DA-FRENTE-2"
    assert typed.json()["code"] == "B1"


def test_cupom_gera_pelo_nome_ou_aleatorio(ctx):
    api = ctx.client()
    url = "/api/v1/promotions/coupons/"
    body = {"kind": "percent", "value": "10"}
    named = api.post(url, {**body, "name": "Black Friday"}, format="json")
    blank = api.post(url, body, format="json")

    assert named.status_code == 201, named.json()
    assert named.json()["code"] == "BLACKFRIDAY"
    assert re.fullmatch(r"CUPOM[0-9A-F]{6}", blank.json()["code"])


def test_categoria_financeira_lote_e_patrimonio(ctx):
    from starrp.models import Asset, FinancialCategory, StockLot, Warehouse

    category = FinancialCategory.all_objects.create(account=ctx.account, name="Aluguel da Loja", kind="expense")
    warehouse = Warehouse.all_objects.filter(store=ctx.store).first()
    product = ctx.product(name="Leite", price="5.00")
    lot = StockLot.all_objects.create(account=ctx.account, variant=product, warehouse=warehouse, initial_quantity=1,
                                      quantity=1)
    assets = [Asset.all_objects.create(account=ctx.account, store=ctx.store, description=f"Notebook {n}") for n in (1, 2)]

    assert category.code == "aluguel-da-loja"
    assert re.fullmatch(r"L[0-9A-F]{8}", lot.code)
    assert [a.code for a in assets] == ["PAT-000001", "PAT-000002"]
