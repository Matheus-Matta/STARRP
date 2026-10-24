"""Plano de contas básico e contas financeiras padrão (idempotente: pode rodar de novo).

As categorias com `system_key` são as que os lançamentos automáticos usam;
o usuário pode renomear ("Vendas" → "Receita de vendas") sem quebrar nada.
"""
from starrp.models import FinancialAccount, FinancialCategory, PaymentMethod

INCOME, EXPENSE = FinancialCategory.Kind.INCOME, FinancialCategory.Kind.EXPENSE

DEFAULT_CATEGORIES = [
    ("sales", "1.01", "Vendas", INCOME),
    ("freight_income", "1.02", "Frete cobrado", INCOME),
    ("financial_income", "1.03", "Juros e multas recebidos", INCOME),
    ("other_income", "1.09", "Outras receitas", INCOME),
    ("suppliers", "2.01", "Compras de mercadorias (fornecedores)", EXPENSE),
    ("card_fees", "2.02", "Taxas de cartão e meios de pagamento", EXPENSE),
    ("commissions", "2.03", "Comissões de vendedores", EXPENSE),
    ("cash_shortage", "2.04", "Quebra de caixa", EXPENSE),
    ("payroll", "2.10", "Salários e encargos", EXPENSE),
    ("rent", "2.11", "Aluguel", EXPENSE),
    ("utilities", "2.12", "Energia, água e internet", EXPENSE),
    ("taxes", "2.13", "Impostos", EXPENSE),
    ("other_expenses", "2.99", "Outras despesas", EXPENSE),
]

BANK = "Banco principal"
ACQUIRER = "Cartões (adquirente)"


def ensure_categories(account):
    for key, code, name, kind in DEFAULT_CATEGORIES:
        FinancialCategory.all_objects.get_or_create(
            account=account, system_key=key, deleted_at=None, defaults={"code": code, "name": name, "kind": kind}
        )


def vault_for(store):
    """O cofre da loja: para onde vai o dinheiro dos caixas (sangria e fechamento)."""
    vault = FinancialAccount.all_objects.filter(
        account_id=store.account_id, store=store, kind=FinancialAccount.Kind.CASH, deleted_at__isnull=True
    ).order_by("created_at").first()
    if vault is None:
        vault = FinancialAccount.all_objects.create(
            account_id=store.account_id, store=store, kind=FinancialAccount.Kind.CASH, name=f"Cofre - {store.name}"[:120]
        )
    return vault


def _shared_account(account, name, kind):
    found = FinancialAccount.all_objects.filter(account=account, name=name, deleted_at__isnull=True).first()
    return found or FinancialAccount.all_objects.create(account=account, name=name, kind=kind)


def ensure_defaults(account):
    """Categorias + banco e adquirente da rede; liga PIX/cartões a eles."""
    ensure_categories(account)
    bank = _shared_account(account, BANK, FinancialAccount.Kind.BANK)
    acquirer = _shared_account(account, ACQUIRER, FinancialAccount.Kind.ACQUIRER)
    targets = {
        PaymentMethod.Kind.PIX: bank, PaymentMethod.Kind.BANK_SLIP: bank,
        PaymentMethod.Kind.DEBIT_CARD: acquirer, PaymentMethod.Kind.CREDIT_CARD: acquirer,
        PaymentMethod.Kind.VOUCHER: acquirer,
    }
    for method in PaymentMethod.all_objects.filter(account=account, financial_account__isnull=True):
        if method.kind in targets:
            method.financial_account = targets[method.kind]
            method.save(update_fields=["financial_account", "updated_at"])
    return bank, acquirer
