"""Financeiro: contas (caixa/banco), plano de contas, títulos e baixas.

Novo no Starrp. O desenho mínimo que um varejo precisa:
- `FinancialTitle` é a conta a pagar OU a receber (um documento);
- `Installment` são as parcelas dele (crediário 3x = 1 título, 3 parcelas);
- `FinancialTransaction` é o dinheiro que efetivamente se moveu numa conta
  (baixa de parcela, taxa da adquirente, transferência entre contas).

O status do título e da parcela é derivado dos valores pagos, e gravado só
para filtrar rápido — quem grava é `services.finance`, nunca a view.
"""
from django.db import models

from starrp.models.base import MoneyField, StoreModel, TenantModel, alive, optional_store_fk, user_fk


class FinancialAccount(TenantModel):
    store_lookup = "store"
    store_shared_when_null = True

    class Kind(models.TextChoices):
        CASH = "cash", "Caixa / cofre"
        BANK = "bank", "Conta bancária"
        ACQUIRER = "acquirer", "Adquirente de cartão"
        WALLET = "wallet", "Carteira digital"

    store = optional_store_fk()
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BANK)
    bank_code = models.CharField(max_length=5, blank=True)
    agency = models.CharField(max_length=10, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    opening_balance = MoneyField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_financial_account"),
        ]

    def __str__(self):
        return self.name


class FinancialCategory(TenantModel):
    """Plano de contas (receitas e despesas), hierárquico."""

    class Kind(models.TextChoices):
        INCOME = "income", "Receita"
        EXPENSE = "expense", "Despesa"

    code = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    # Chave fixa das categorias que o sistema usa nos lançamentos automáticos
    # ("sales", "card_fees"...). O usuário pode renomear; a chave não muda.
    system_key = models.SlugField(max_length=40, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code", "name"]
        verbose_name_plural = "financial categories"
        constraints = [
            models.UniqueConstraint(fields=["account", "kind", "name"], condition=alive(), name="uniq_fin_category"),
            models.UniqueConstraint(fields=["account", "system_key"], condition=alive() & ~models.Q(system_key=""),
                                    name="uniq_fin_category_system_key"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}".strip()


class TitleStatus(models.TextChoices):
    OPEN = "open", "Em aberto"
    PARTIAL = "partial", "Pago parcialmente"
    PAID = "paid", "Pago"
    CANCELLED = "cancelled", "Cancelado"


class FinancialTitle(StoreModel):
    class Kind(models.TextChoices):
        RECEIVABLE = "receivable", "A receber"
        PAYABLE = "payable", "A pagar"

    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    description = models.CharField(max_length=255)
    customer = models.ForeignKey(
        "starrp.Customer", null=True, blank=True, related_name="titles", on_delete=models.PROTECT
    )
    supplier = models.ForeignKey(
        "starrp.Supplier", null=True, blank=True, related_name="titles", on_delete=models.PROTECT
    )
    category = models.ForeignKey(
        FinancialCategory, null=True, blank=True, related_name="titles", on_delete=models.SET_NULL
    )
    document_number = models.CharField(max_length=60, blank=True)
    issue_date = models.DateField()
    total = MoneyField()
    status = models.CharField(max_length=10, choices=TitleStatus.choices, default=TitleStatus.OPEN, db_index=True)
    # Origem automática (crediário, cartão a receber, duplicata de NF-e).
    sale = models.ForeignKey("starrp.Sale", null=True, blank=True, related_name="titles", on_delete=models.PROTECT)
    payment = models.ForeignKey("starrp.Payment", null=True, blank=True, related_name="titles", on_delete=models.PROTECT)
    inbound_nfe = models.ForeignKey(
        "starrp.InboundNFe", null=True, blank=True, related_name="titles", on_delete=models.PROTECT
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date"]
        constraints = [
            models.CheckConstraint(
                condition=~(models.Q(customer__isnull=False) & models.Q(supplier__isnull=False)),
                name="title_single_counterparty",
            ),
        ]

    def __str__(self):
        return self.description


class Installment(TenantModel):
    store_lookup = "title__store"

    title = models.ForeignKey(FinancialTitle, related_name="installments", on_delete=models.CASCADE)
    number = models.PositiveSmallIntegerField(default=1)
    due_date = models.DateField(db_index=True)
    amount = MoneyField()
    interest = MoneyField()
    fine = MoneyField()
    discount = MoneyField()
    paid_amount = MoneyField()
    paid_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=TitleStatus.choices, default=TitleStatus.OPEN, db_index=True)

    class Meta:
        ordering = ["due_date", "number"]
        constraints = [
            models.UniqueConstraint(fields=["title", "number"], condition=alive(), name="uniq_installment_number"),
        ]

    @property
    def balance(self):
        return self.amount + self.interest + self.fine - self.discount - self.paid_amount


class FinancialTransaction(TenantModel):
    store_lookup = "financial_account__store"
    store_shared_when_null = True

    class Kind(models.TextChoices):
        IN = "in", "Entrada"
        OUT = "out", "Saída"

    financial_account = models.ForeignKey(FinancialAccount, related_name="transactions", on_delete=models.PROTECT)
    kind = models.CharField(max_length=3, choices=Kind.choices)
    amount = MoneyField()
    date = models.DateField(db_index=True)
    description = models.CharField(max_length=255)
    category = models.ForeignKey(
        FinancialCategory, null=True, blank=True, related_name="transactions", on_delete=models.SET_NULL
    )
    installment = models.ForeignKey(
        Installment, null=True, blank=True, related_name="transactions", on_delete=models.PROTECT
    )
    # Transferência entre contas = duas transações com o mesmo par.
    transfer_pair = models.UUIDField(null=True, blank=True, db_index=True)
    # Origem dos lançamentos automáticos (caixa, venda, pagamento).
    cash_session = models.ForeignKey("starrp.CashSession", null=True, blank=True, related_name="financial_transactions",
                                     on_delete=models.PROTECT)
    sale = models.ForeignKey("starrp.Sale", null=True, blank=True, related_name="financial_transactions",
                             on_delete=models.PROTECT)
    payment = models.ForeignKey("starrp.Payment", null=True, blank=True, related_name="financial_transactions",
                                on_delete=models.PROTECT)
    reversal_of = models.ForeignKey("self", null=True, blank=True, related_name="reversals", on_delete=models.PROTECT)
    # Identidade da origem: o mesmo evento nunca lança duas vezes (reenvio, retry).
    source_key = models.CharField(max_length=200, blank=True)
    reconciled = models.BooleanField(default=False)
    operator = user_fk("+")

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["account", "source_key"], condition=alive() & ~models.Q(source_key=""),
                                    name="uniq_fin_transaction_source_key"),
        ]
