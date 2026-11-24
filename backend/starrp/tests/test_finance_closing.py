"""Financeiro de serviços: parcelas por frequência, encargos de atraso, crédito de cliente, recorrências,
contas de sócio e o relatório de fechamento."""
from datetime import date, time
from decimal import Decimal

import pytest

from starrp.models import (
    Customer, FinancialAccount, FinancialCategory, FinancialTitle, FinancialTransaction, RecurringTitle, Supplier,
)
from starrp.services import finance, ledger, recurring


@pytest.fixture
def fin(ctx):
    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    ctx.bank = FinancialAccount.all_objects.get(account=ctx.account, name="Banco principal")
    ctx.me = FinancialAccount.all_objects.create(account=ctx.account, name="Sócio Matheus", kind="partner",
                                                 partner_share=Decimal("50"))
    ctx.partner = FinancialAccount.all_objects.create(account=ctx.account, name="Sócio João", kind="partner",
                                                      partner_share=Decimal("50"))
    ctx.services = FinancialCategory.all_objects.create(account=ctx.account, name="Serviços", kind="income")
    ctx.ads = FinancialCategory.all_objects.create(account=ctx.account, name="Divulgação", kind="expense")
    ctx.customer = Customer.all_objects.create(account=ctx.account, name="Cliente A", document="12345678909")
    ctx.supplier = Supplier.all_objects.create(account=ctx.account, name="Diarista B")
    return ctx


def _take(gen, n):
    return [next(gen) for _ in range(n)]


def test_vencimentos_por_frequencia_atravessam_o_ano():
    assert _take(finance.due_dates(date(2026, 10, 1), due_day=10), 4) == [
        date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10), date(2027, 1, 10)]
    assert _take(finance.due_dates(date(2026, 1, 15), due_day=31), 2) == [date(2026, 1, 31), date(2026, 2, 28)]
    # Dia 10 já passou no mês do início: começa no seguinte
    assert next(finance.due_dates(date(2026, 10, 20), due_day=10)) == date(2026, 11, 10)
    # Toda segunda (20/11/2026 é sexta)
    assert _take(finance.due_dates(date(2026, 11, 20), frequency="weekly", due_weekday=0), 2) == [
        date(2026, 11, 23), date(2026, 11, 30)]
    assert _take(finance.due_dates(date(2026, 12, 31), frequency="daily"), 2) == [date(2026, 12, 31), date(2027, 1, 1)]


def test_parcelado_toda_segunda_com_horario_e_pagamento_unico(fin):
    api = fin.client()
    weekly = api.post("/api/v1/finance/titles/", {
        "kind": "receivable", "description": "Serviço semanal", "total": "400.00", "customer": str(fin.customer.pk),
        "payment_mode": "installments", "installment_count": 4, "first_due": "2026-11-20", "frequency": "weekly",
        "due_weekday": 0, "due_time": "14:00", "fine_percent": "2", "interest_percent": "1"}, format="json")
    single = api.post("/api/v1/finance/titles/", {
        "kind": "receivable", "description": "Avulso", "total": "300.00", "payment_mode": "single",
        "installment_count": 5, "first_due": "2026-11-25"}, format="json")

    assert weekly.status_code == 201, weekly.json()
    dues = [i["due_date"] for i in weekly.json()["installments"]]
    assert dues == ["2026-11-23", "2026-11-30", "2026-12-07", "2026-12-14"]
    title = FinancialTitle.all_objects.get(pk=weekly.json()["id"])
    assert title.due_time == time(14, 0) and title.frequency == "weekly"
    assert len(single.json()["installments"]) == 1


def test_multa_e_juros_de_atraso(fin):
    title = finance.create_title(store=fin.store, kind="receivable", description="Boleto", total=Decimal("1500"),
                                 first_due=date(2026, 10, 10), customer=fin.customer, fine_percent=Decimal("2"),
                                 interest_percent=Decimal("1"))
    part = title.installments.get()
    charges = finance.late_charges(part, on=date(2026, 11, 9))  # 30 dias
    assert charges == {"days_late": 30, "fine": Decimal("30.00"), "interest": Decimal("15.00")}
    assert finance.late_charges(part, on=date(2026, 10, 10))["fine"] == 0  # no dia ainda não atrasou
    late = fin.client().get(f"/api/v1/finance/installments/{part.pk}/").json()["late"]
    assert Decimal(late["fine"]) == Decimal("30.00")


def test_pago_a_mais_vira_credito_e_quita_a_proxima(fin):
    title = finance.create_title(store=fin.store, kind="receivable", description="Mensalidade", total=Decimal("3000"),
                                 installments=2, first_due=date(2026, 11, 10), customer=fin.customer)
    first, second = title.installments.order_by("number")
    api = fin.client()

    refused = api.post(f"/api/v1/finance/installments/{first.pk}/settle/",
                       {"financial_account": str(fin.bank.pk), "amount": "2000.00"}, format="json")
    paid = api.post(f"/api/v1/finance/installments/{first.pk}/settle/",
                    {"financial_account": str(fin.bank.pk), "amount": "2000.00", "allow_excess": True}, format="json")
    credit = api.get(f"/api/v1/finance/installments/{second.pk}/credit/").json()
    with_credit = api.post(f"/api/v1/finance/installments/{second.pk}/settle/",
                           {"financial_account": str(fin.bank.pk), "amount": "1000.00", "use_credit": True}, format="json")

    assert refused.status_code == 422
    assert paid.status_code == 200 and paid.json()["status"] == "paid", paid.json()
    assert credit["credit"] == "500.00"
    assert with_credit.status_code == 200 and with_credit.json()["status"] == "paid", with_credit.json()
    second.refresh_from_db()
    assert second.credit_used == Decimal("500.00") and finance.party_credit(customer=fin.customer) == 0
    # o dinheiro que entrou no banco: 2000 + 1000 = o devido (3000)
    assert sum(t.amount for t in FinancialTransaction.all_objects.filter(financial_account=fin.bank, kind="in",
                                                                         description__contains="Mensalidade")) == 3000


def test_recorrencia_gera_uma_vez_por_vencimento(fin):
    rec = RecurringTitle.all_objects.create(
        account=fin.account, store=fin.store, kind="receivable", description="Mensalidade Cliente A",
        customer=fin.customer, category=fin.services, amount=Decimal("1500"), due_day=10,
        start_date=date(2026, 10, 1), lead_days=10)
    created = recurring.generate_one(rec, today=date(2026, 11, 20))
    again = recurring.generate_one(rec, today=date(2026, 11, 20))
    rec.refresh_from_db()

    assert [t.recurring_period for t in created] == [date(2026, 10, 10), date(2026, 11, 10)]
    assert again == [] and rec.next_period == date(2026, 12, 10)
    assert created[0].installments.get().due_date == date(2026, 10, 10) and created[0].issue_date == date(2026, 10, 10)
    assert recurring.generate_one(rec, today=date(2026, 11, 30))[0].recurring_period == date(2026, 12, 10)


def test_fechamento_com_socios_clientes_e_lancamentos(fin):
    api = fin.client()
    for n in range(3):  # 3 boletos de 1500
        title = finance.create_title(store=fin.store, kind="receivable", description=f"Boleto {n + 1}",
                                     total=Decimal("1500"), first_due=date(2026, 11, 10), customer=fin.customer,
                                     category=fin.services, issue_date=date(2026, 11, 1))
        if n < 2:
            finance.settle(title.installments.get(), fin.bank, Decimal("1500"), fin.admin, date=date(2026, 11, 10))
    # o sócio João pagou a divulgação do bolso; a diarista foi paga pelo banco
    api.post("/api/v1/finance/transactions/", {"financial_account": str(fin.partner.pk), "kind": "out", "amount": "400.00",
                                               "date": "2026-11-05", "description": "Anúncio", "category": str(fin.ads.pk)},
             format="json")
    diarias = finance.create_title(store=fin.store, kind="payable", description="Diárias", total=Decimal("600"),
                                   first_due=date(2026, 11, 15), supplier=fin.supplier, issue_date=date(2026, 11, 2))
    finance.settle(diarias.installments.get(), fin.bank, Decimal("600"), fin.admin, date=date(2026, 11, 15))
    # reembolso parcial ao João
    ledger.transfer(fin.bank, fin.partner, Decimal("100"), description="reembolso", date=date(2026, 11, 20))

    report = api.get("/api/v1/reports/book/fechamento/", {"date_from": "2026-11-01", "date_to": "2026-11-30"})

    assert report.status_code == 200, report.json()
    data = report.json()
    kpis = {k["label"]: Decimal(k["value"]) for k in data["kpis"]}
    assert kpis["Faturamento total"] == Decimal("4500.00")
    assert kpis["A receber no período"] == Decimal("4500.00")
    assert kpis["Recebido"] == Decimal("3000.00")
    assert kpis["Falta receber"] == Decimal("1500.00")
    assert kpis["Recebido"] + kpis["Falta receber"] == kpis["A receber no período"]
    assert kpis["Atrasado de antes"] == 0
    counts = {k["label"]: k["count"] for k in data["kpis"]}
    assert counts["Recebido"] == "2 de 3 parcelas pagas" and counts["Falta receber"] == "1 parcela em aberto"
    assert counts["Custo total"] == "2 contas a pagar"
    assert kpis["Custo total"] == Decimal("1000.00")
    assert kpis["Resultado"] == Decimal("3500.00")
    assert kpis["Reembolso"] == Decimal("300.00")
    links = {k["label"]: k["link"] for k in data["kpis"]}
    assert links["Recebido"] == {"path": "/cadastros/vencimentos", "query": {
        "title__kind": "receivable", "status": "paid", "due_date__gte": "2026-11-01", "due_date__lte": "2026-11-30"}}
    blocks = {b["title"]: b for b in data["blocks"]}
    partners = {r["name"]: r for r in blocks["Reembolso por pessoa"]["rows"]}
    joao = partners["Sócio João"]
    assert Decimal(joao["paid"]) == 400 and Decimal(joao["reimbursed"]) == 100 and Decimal(joao["owed"]) == 300
    items = blocks["Itens a reembolsar"]["rows"]
    assert [(i["description"], i["status"], Decimal(i["pending"])) for i in items] == [("Anúncio", "Parcial", Decimal("300"))]
    assert blocks["Itens a reembolsar"]["search"] is True and blocks["Itens a reembolsar"]["tabs"]["key"] == "partner"
    division = {r["name"]: r for r in blocks["Divisão do resultado"]["rows"]}
    assert Decimal(division["Sócio João"]["share"]) == Decimal("1750.00")
    assert Decimal(division["Sócio João"]["total"]) == Decimal("2050.00")
    people = {r["name"]: r for r in blocks["Clientes e fornecedores"]["rows"]}
    assert Decimal(people["Cliente A"]["billed"]) == 4500 and Decimal(people["Cliente A"]["paid"]) == 3000
    assert Decimal(people["Cliente A"]["balance"]) == 1500
    assert Decimal(people["Diarista B"]["paid"]) == 600
    assert len(blocks["Todos os lançamentos do período"]["rows"]) == 6
