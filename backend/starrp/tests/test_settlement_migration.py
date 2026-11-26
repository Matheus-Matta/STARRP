"""Migration 0076: baixas antigas viram linhas e o crédito com categoria não fica negativo."""
import importlib
from decimal import Decimal as D

from django.apps import apps
from django.utils import timezone

from starrp.models import Customer, FinancialAccount, FinancialCategory, FinancialTransaction, Installment, InstallmentSettlement
from starrp.services import finance

migration = importlib.import_module("starrp.migrations.0076_settlement_history")


def test_baixa_antiga_e_credito_com_categoria(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ze")
    bank = FinancialAccount.all_objects.filter(account=ctx.account, kind="bank").first()
    category = FinancialCategory.all_objects.get(account=ctx.account, system_key="other_income")
    base = {"account": ctx.account, "financial_account": bank, "kind": "in", "amount": 100, "date": timezone.localdate(),
            "customer": customer}
    FinancialTransaction.all_objects.create(description="antigo", category=category, **base)
    title = finance.create_title(store=ctx.store, kind="receivable", description="t", total=D(110), customer=customer)
    Installment.all_objects.filter(title=title).update(credit_used=100, paid_amount=110, interest=10, status="paid",
                                                       paid_at=timezone.localdate())
    migration.fill(apps, None)
    migration.settle_credit(apps, None)
    row = InstallmentSettlement.all_objects.get()
    assert (row.amount, row.credit, row.interest) == (10, 100, 10)
    FinancialTransaction.all_objects.create(description="novo", **base)
    assert finance.party_credit(customer=customer) == 100
