"""Rodada 5b: financeiro e relatorios. Cada teste afirma o comportamento correto."""
from datetime import datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.models import (
    Category, Customer, FinancialAccount, FinancialCategory, FinancialTransaction, Installment, PaymentMethod, Sale,
    StockMovement,
)
from starrp.services import cash, cash_flow, finance, ledger, stock

D = Decimal
A = "/api/v1"


@pytest.fixture(autouse=True)
def _mods(ctx):
    ctx.account.extra_modules = ["stock", "inbound_nfe", "finance", "pricing"]
    ctx.account.save()


def bank(ctx):
    return FinancialAccount.all_objects.filter(account=ctx.account, kind="bank").order_by("created_at").first()


def cat(ctx, key):
    return FinancialCategory.all_objects.get(account=ctx.account, system_key=key)


def sale(ctx, api, items, discount=None, method="pix"):
    sid = api.post(f"{A}/sales/", {}, format="json").json()["id"]
    for v, q in items:
        r = api.post(f"{A}/sales/{sid}/items/", {"variant": str(v.pk), "quantity": q}, format="json")
        assert r.status_code == 201, r.json()
    if discount:
        r = api.post(f"{A}/sales/{sid}/discount/", {"amount": discount}, format="json")
        assert r.status_code == 200, r.json()
    s = Sale.all_objects.get(pk=sid)
    r = api.post(f"{A}/sales/{sid}/checkout/", {"payments": [
        {"nsu": "1", "method": str(ctx.methods[method].pk), "amount": str(s.total)}]}, format="json")
    assert r.status_code == 200, r.json()
    return Sale.all_objects.get(pk=sid)


def stocked(ctx, name="Mesa", price="100.00", cost="60.00", q=10):
    v = ctx.product(name=name, price=price, sku=name.upper())
    stock.move(v, stock.default_warehouse(ctx.store), D(q), StockMovement.Kind.PURCHASE, unit_cost=D(cost))
    return v


def avulso(ctx, api, acc, kind, amount, **extra):
    r = api.post(f"{A}/finance/transactions/", {"financial_account": str(acc.pk), "kind": kind, "amount": amount,
                 "date": str(timezone.localdate()), "description": "avulso", **extra}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def test_f01_despesa_estornada_sai_da_dre(ctx):
    api = ctx.client()
    pk = avulso(ctx, api, bank(ctx), "out", "100.00", category=str(cat(ctx, "rent").pk))
    assert api.post(f"{A}/finance/transactions/{pk}/reverse/", {}, format="json").status_code == 201
    d = api.get(f"{A}/reports/dre/").json()
    assert D(d["expenses_total"]) == 0, d["expenses"]


def test_f02_receita_avulsa_categorizada_nao_vira_credito(ctx):
    api = ctx.client()
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    avulso(ctx, api, bank(ctx), "in", "100.00", category=str(cat(ctx, "other_income").pk), customer=str(c.pk))
    d = api.get(f"{A}/reports/dre/").json()
    assert D(d["other_revenue_total"]) == 100
    assert finance.party_credit(customer=c) == 0


def test_f03_credito_usado_nao_pode_ser_estornado(ctx):
    u = ctx.user("fin", "finance_assistant")
    b = FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="Banco loja", kind="bank")
    api = ctx.client(u)
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    t = finance.create_title(store=ctx.store, kind="receivable", description="divida", total=D("100"), customer=c)
    part = t.installments.first()
    pk = avulso(ctx, api, b, "in", "100.00", customer=str(c.pk))
    r = api.post(f"{A}/finance/installments/{part.pk}/settle/", {"use_credit": True}, format="json")
    assert r.status_code == 200, r.json()
    rv = api.post(f"{A}/finance/transactions/{pk}/reverse/", {}, format="json")
    part.refresh_from_db()
    saldo = cash_flow._net(FinancialTransaction.all_objects.filter(financial_account=b))
    assert not (rv.status_code == 201 and part.status == "paid" and saldo == 0), (
        rv.status_code, part.status, saldo, finance.party_credit(customer=c))


def test_f04_aging_bate_com_saldo_com_desconto(ctx):
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    t = finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"), customer=c)
    p = finance.settle(t.installments.first(), bank(ctx), D("50"), ctx.admin, discount=D("20"))
    a = ctx.client().get(f"{A}/reports/aging/").json()["receivable"]
    total = sum(D(x) for x in a.values())
    assert (total, finance.open_receivables(c)) == (p.balance, p.balance), (total, finance.open_receivables(c), p.balance)


def test_f05_limite_crediario_com_juros(ctx):
    c = Customer.all_objects.create(account=ctx.account, name="Ze", credit_limit=D("100"))
    t = finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"), customer=c)
    p = finance.settle(t.installments.first(), bank(ctx), D("60"), ctx.admin, interest=D("50"))
    assert finance.open_receivables(c) == p.balance, (finance.open_receivables(c), p.balance)


def test_f06_juros_recebidos_na_dre(ctx):
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    t = finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"), customer=c,
                             category_key="other_income")
    finance.settle(t.installments.first(), bank(ctx), D("110"), ctx.admin, interest=D("10"))
    d = ctx.client().get(f"{A}/reports/dre/").json()
    assert D(d["operating_result"]) == 110, d["operating_result"]


def test_f07_desconto_concedido_na_dre(ctx):
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    t = finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"), customer=c,
                             category_key="other_income")
    finance.settle(t.installments.first(), bank(ctx), D("60"), ctx.admin, discount=D("40"))
    d = ctx.client().get(f"{A}/reports/dre/").json()
    assert D(d["operating_result"]) == 60, d["operating_result"]


def test_f08_compra_de_mercadoria_nao_conta_duas_vezes(ctx):
    v = stocked(ctx)
    api = ctx.client()
    # o que a entrada da NF-e cria (nfe_receiving._payables): titulo a pagar na categoria suppliers
    finance.create_title(store=ctx.store, kind="payable", description="NF-e 1", total=D("600"), category_key="suppliers")
    sale(ctx, api, [(v, "10")])
    d = api.get(f"{A}/reports/dre/").json()
    assert D(d["operating_result"]) == 400, d  # vendeu tudo: 1000 - 600


def test_f09_fechamento_a_noite_no_dia_certo(ctx):
    s = cash.open_session(ctx.register, ctx.admin, D("0"))
    s.counted_amount = D("500")
    s.closed_at = datetime(2026, 11, 1, 1, 0, tzinfo=tz.utc)  # 31/10 22:00 em Sao Paulo
    ledger.session_closed(s)
    tx = FinancialTransaction.all_objects.get(source_key=f"cash_close:{s.pk}")
    assert str(tx.date) == "2026-10-31", tx.date


def test_f10_margem_do_painel_bate_com_dre(ctx):
    v = stocked(ctx)
    api = ctx.client()
    sale(ctx, api, [(v, "1")], discount="30.00")
    s = api.get(f"{A}/reports/summary/").json()
    d = api.get(f"{A}/reports/dre/").json()
    assert D(s["gross_margin"]) == D(d["gross_profit"]), (s["gross_margin"], d["gross_profit"])


def test_f11_conta_com_forma_de_pagamento_nao_some(ctx):
    v = ctx.product(name="X", price="100.00", track_stock=False)
    api = ctx.client()
    b = PaymentMethod.all_objects.get(pk=ctx.methods["pix"].pk).financial_account
    r = api.delete(f"{A}/finance/accounts/{b.pk}/")
    sale(ctx, api, [(v, "1")])
    total = D(api.get(f"{A}/reports/balances/").json()["total"])
    assert not (r.status_code == 204 and total == 0), (r.status_code, total)


def test_f11b_conta_com_saldo_nao_exclui(ctx):
    api = ctx.client(ctx.user("fin", "finance_assistant"))
    b = FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="Banco loja", kind="bank")
    ledger.post(b, "in", D("5000"), description="dep")
    assert api.delete(f"{A}/finance/accounts/{b.pk}/").status_code != 204


def _transfer(ctx):
    net = bank(ctx)
    mine = FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="Banco loja", kind="bank")
    tx = ledger.transfer(mine, net, D("1000"), description="deposito matriz", user=ctx.admin)
    return net, tx, ctx.client(ctx.user("fin", "finance_assistant"))


def test_f12_estorno_da_transferencia_pela_perna_da_filial(ctx):
    net, tx, api = _transfer(ctx)
    r = api.post(f"{A}/finance/transactions/{tx.pk}/reverse/", {}, format="json")
    saldo = cash_flow._net(FinancialTransaction.all_objects.filter(financial_account=net))
    assert saldo == 1000, (r.status_code, saldo)


def test_f12b_em_massa(ctx):
    net, tx, api = _transfer(ctx)
    r = api.post(f"{A}/finance/transactions/bulk/", {"action": "reverse", "ids": [str(tx.pk)]}, format="json")
    saldo = cash_flow._net(FinancialTransaction.all_objects.filter(financial_account=net))
    assert saldo == 1000, (r.status_code, r.json(), saldo)


def test_f13_baixa_errada_tem_como_desfazer(ctx):
    api = ctx.client()
    c = Customer.all_objects.create(account=ctx.account, name="Ze", credit_limit=D("500"))
    v = ctx.product(name="X", price="100.00", track_stock=False)
    sid = api.post(f"{A}/sales/", {"customer": str(c.pk)}, format="json").json()["id"]
    api.post(f"{A}/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
    m = next(x for x in ctx.methods.values() if x.kind == "installment_plan")
    r = api.post(f"{A}/sales/{sid}/checkout/", {"payments": [{"method": str(m.pk), "amount": "100.00"}]}, format="json")
    assert r.status_code == 200, r.json()
    part = Installment.all_objects.get(title__sale_id=sid)
    api.post(f"{A}/finance/installments/{part.pk}/settle/", {"financial_account": str(bank(ctx).pk), "amount": "100"},
             format="json")
    tx = FinancialTransaction.all_objects.get(installment=part)
    assert api.post(f"{A}/finance/transactions/{tx.pk}/reverse/", {}, format="json").status_code == 409
    undo = f"{A}/finance/installments/{part.pk}/unsettle/"
    assert api.post(undo, {}, format="json").status_code == 422  # sem motivo
    assert api.post(undo, {"reason": "parcela errada"}, format="json").status_code == 200
    part.refresh_from_db()
    assert part.status == "open" and part.paid_amount == 0
    assert cash_flow._net(FinancialTransaction.all_objects.filter(financial_account=bank(ctx))) == 0
    assert api.post(f"{A}/sales/{sid}/cancel/", {"reason": "erro de lancamento"}, format="json").status_code == 200


def test_f13b_titulo_manual_sem_baixa_cancela(ctx):
    title = finance.create_title(store=ctx.store, kind="payable", description="x", total=D("10"))
    r = ctx.client().post(f"{A}/finance/titles/{title.pk}/cancel/", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_f14_dre_de_quem_nao_ve_vendas_da_equipe(ctx):
    v = stocked(ctx)
    sale(ctx, ctx.client(), [(v, "1")])
    r = ctx.client(ctx.user("compr", "comprador")).get(f"{A}/reports/dre/")
    assert r.status_code == 403 or D(r.json()["gross_revenue"]) == 100, r.json()


def test_f15_faturamento_filtrado_por_categoria(ctx):
    cx, cy = (Category.all_objects.create(account=ctx.account, name=n) for n in "XY")
    a, b = stocked(ctx, "Caro", "900.00", "500.00"), stocked(ctx, "Barato", "100.00", "50.00")
    for v, c in ((a, cx), (b, cy)):
        v.product.category = c
        v.product.save()
    api = ctx.client()
    sale(ctx, api, [(a, "1"), (b, "1")])
    r = api.get(f"{A}/reports/book/vendas/?category={cy.pk}").json()
    k = {x["label"]: x["value"] for x in r["kpis"]}
    assert D(k["Faturamento"]) == 100, k


def test_f16_taxa_alterada_nao_muda_mes_passado(ctx):
    v = ctx.product(name="X", price="100.00", track_stock=False)
    api = ctx.client()
    m = ctx.methods["pix"]
    PaymentMethod.all_objects.filter(pk=m.pk).update(fee_percent=D("2"))
    sale(ctx, api, [(v, "1")])
    d1 = api.get(f"{A}/reports/dre/").json()["card_fees"]
    PaymentMethod.all_objects.filter(pk=m.pk).update(fee_percent=D("10"))
    d2 = api.get(f"{A}/reports/dre/").json()["card_fees"]
    assert d1 == d2, (d1, d2)


def test_f17_estorno_de_transferencia_nao_vira_movimento_no_fechamento(ctx):
    a = bank(ctx)
    b = FinancialAccount.all_objects.create(account=ctx.account, name="B2", kind="bank")
    tx = ledger.transfer(a, b, D("1000"), description="x", user=ctx.admin)
    ledger.reverse(tx, user=ctx.admin)
    r = ctx.client().get(f"{A}/reports/book/fechamento/").json()
    t = next(x for x in r["blocks"] if x["title"].startswith("Todos os"))
    assert "Entrou R$ 0,00" in t["description"], t["description"]


def test_f18_perda_de_estoque_no_resultado(ctx):
    v = stocked(ctx)
    wh = stock.default_warehouse(ctx.store)
    api = ctx.client()
    r = api.post(f"{A}/stock/documents/", {"kind": "exit", "exit_reason": "loss", "warehouse": str(wh.pk),
                 "reason": "quebra", "effective_date": str(timezone.localdate()),
                 "items": [{"variant": str(v.pk), "quantity": "5"}]}, format="json")
    assert r.status_code == 201, r.json()
    p = api.post(f"{A}/stock/documents/{r.json()['id']}/post/", {}, format="json")
    assert p.status_code == 200, p.json()
    d = api.get(f"{A}/reports/dre/").json()
    assert D(d["operating_result"]) == -300, d["operating_result"]


def test_f19_cliente_com_divida_nao_exclui(ctx):
    c = Customer.all_objects.create(account=ctx.account, name="Ze", credit_limit=D("500"))
    finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"), customer=c)
    r = ctx.client(ctx.user("cx", "cashier")).delete(f"{A}/customers/{c.pk}/")
    assert r.status_code not in (204, 404), r.status_code


def test_f20_ciclo_devolucao_fecha(ctx):
    v = stocked(ctx)
    api = ctx.client()
    s = sale(ctx, api, [(v, "3")], discount="10.00")
    it = s.items.first()
    for _ in range(3):
        r = api.post(f"{A}/sales/{s.pk}/returns/", {"items": [{"sale_item": str(it.pk), "quantity": "1"}],
                     "refund_method": "original_payment", "reason": "x"}, format="json")
        assert r.status_code == 201, r.json()
        assert api.post(f"{A}/returns/{r.json()['id']}/complete/", {}, format="json").status_code == 200
    d = api.get(f"{A}/reports/dre/").json()
    assert D(d["net_revenue"]) == 0 and D(d["cmv"]) == 0, d
    assert stock.available(v) == 10
    assert D(api.get(f"{A}/reports/balances/").json()["total"]) == 0


def test_f21_kit_alterado_devolve_o_que_saiu(ctx):
    from starrp.models import KitComponent, Product
    a, b = stocked(ctx, "Peca", "10", "5"), stocked(ctx, "Outra", "10", "5")
    k = ctx.product(name="Kit", price="30.00", sku="KIT")
    Product.all_objects.filter(pk=k.product_id).update(type="kit", track_stock=False)
    KitComponent.all_objects.create(account=ctx.account, kit_id=k.product_id, component=a, quantity=1)
    api = ctx.client()
    s = sale(ctx, api, [(k, "1")])
    assert stock.available(a) == 9
    KitComponent.all_objects.filter(kit_id=k.product_id).delete()
    KitComponent.all_objects.create(account=ctx.account, kit_id=k.product_id, component=b, quantity=1)
    r = api.post(f"{A}/sales/{s.pk}/returns/", {"items": [{"sale_item": str(s.items.first().pk), "quantity": "1"}],
                 "refund_method": "original_payment", "reason": "x"}, format="json")
    assert api.post(f"{A}/returns/{r.json()['id']}/complete/", {}, format="json").status_code == 200
    assert (stock.available(a), stock.available(b)) == (10, 10)
