"""Fechamento financeiro do período: TUDO num lugar só, com data (livro de relatórios, slug "fechamento").

- resultado (competência, a mesma DRE): receitas de venda e de serviços, custos e despesas por categoria;
- caixa: o que entrou e saiu das contas no período (transferências fora, elas só mudam o dinheiro de lugar);
- reembolso: o que cada pessoa pagou do bolso pela empresa, o que já foi devolvido e quanto falta (e, se for sócio,
  a parte dele no resultado);
- clientes e fornecedores: faturado e pago no período, o que está em aberto, o crédito (pago a mais)
  e o saldo de cada um;
- saldos das contas no fim do período, parcelas em aberto até o fim dele, contas recorrentes e a lista
  de TODOS os lançamentos do período.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from starrp.core.tenant import tenant_context
from starrp.models import (
    FinancialAccount, FinancialTitle, FinancialTransaction, Installment, RecurringTitle, TitleStatus,
)
from starrp.services import cash_flow, dre, finance, recurring
from starrp.services.report_book import TABLE_MAX, _report, _scoped, _window, brl, kpi, pt

ZERO = Decimal("0")
CENTS = Decimal("0.01")
IN, OUT = FinancialTransaction.Kind.IN, FinancialTransaction.Kind.OUT
OPEN = [TitleStatus.OPEN, TitleStatus.PARTIAL]


def ensure_recurring(account):
    """Sem o Celery rodando (desenvolvimento, servidor pequeno), as recorrências geram aqui, 1x por dia."""
    key = f"recurring-generated:{account.pk}:{timezone.localdate()}"
    if cache.add(key, True, 60 * 60 * 24):
        with tenant_context(account):  # a conta inteira: a marca do dia é da conta, não das filiais de quem abriu a tela
            recurring.generate_all(account)


def _net(qs):
    agg = qs.aggregate(i=Coalesce(Sum("amount", filter=Q(kind=IN)), ZERO), o=Coalesce(Sum("amount", filter=Q(kind=OUT)), ZERO))
    return agg["i"] - agg["o"]


def _party_name(tx):
    if tx.customer_id:
        return tx.customer.name
    if tx.supplier_id:
        return tx.supplier.name
    title = tx.installment.title if tx.installment_id else None
    if title is not None:
        party = title.customer or title.supplier
        return party.name if party else ""
    return ""


def _kind_label(tx):
    if tx.transfer_pair:
        return "Transferência"
    if tx.reversal_of_id:
        return "Estorno"
    return "Entrada" if tx.kind == IN else "Saída"


def _reimbursements(accounts, txs, start, end, result):
    """Conta de reembolso: cada despesa que a pessoa pagou do bolso, quanto dela já foi reembolsado e o que falta.

    O reembolso (transferência para a conta dele) e o que entrou na conta dele cobrem as despesas da
    mais antiga para a mais nova. Estorno e lançamento estornado ficam de fora (anulam-se)."""
    summary, items = [], []
    for acc in accounts:
        if acc.kind != FinancialAccount.Kind.PARTNER:
            continue
        mine = txs.filter(financial_account=acc, date__lte=end, reversal_of__isnull=True, reversals__isnull=True)
        spent = list(mine.filter(kind=OUT, transfer_pair__isnull=True)
                     .select_related("category", "supplier", "customer", "installment__title__supplier",
                                     "installment__title__customer")
                     .order_by("date", "created_at"))
        back_total = mine.filter(kind=IN, transfer_pair__isnull=False).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
        put_in = mine.filter(kind=IN, transfer_pair__isnull=True).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
        moved_out = mine.filter(kind=OUT, transfer_pair__isnull=False).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
        cover = max(acc.opening_balance, ZERO) + back_total + put_in - moved_out
        pending_total = ZERO
        paid_period = ZERO
        for tx in spent:
            covered = min(max(cover, ZERO), tx.amount)
            cover -= covered
            missing = tx.amount - covered
            pending_total += missing
            if start <= tx.date <= end:
                paid_period += tx.amount
            title = tx.installment.title if tx.installment_id else None
            items.append({"date": tx.date, "partner": acc.name, "description": title.description if title else tx.description,
                          "category": tx.category.name if tx.category_id else "", "who": _party_name(tx),
                          "amount": tx.amount, "reimbursed": covered, "pending": missing,
                          "status": "Reembolsado" if missing == 0 else "Parcial" if covered > 0 else "Pendente"})
        back_period = txs.filter(financial_account=acc, kind=IN, transfer_pair__isnull=False,
                                 reversal_of__isnull=True, reversals__isnull=True, date__range=(start, end)).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
        # Divisão do LUCRO: mês com prejuízo não gera parte a receber (o prejuízo fica na empresa).
        share = (max(result, ZERO) * acc.partner_share / 100).quantize(CENTS) if acc.partner_share else ZERO
        summary.append({"name": acc.name, "paid_period": paid_period, "paid": sum((t.amount for t in spent), ZERO),
                        "reimbursed": back_total + put_in, "reimbursed_period": back_period, "owed": pending_total,
                        "items": sum(1 for i in items if i["partner"] == acc.name and i["pending"] > 0),
                        "share_pct": acc.partner_share, "share": share, "total": pending_total + share})
    items.sort(key=lambda r: (r["status"] == "Reembolsado", r["date"]))
    return summary, items


def _parties(account, store, titles, txs, start, end):
    """Por cliente e fornecedor: faturado no período, pago no período, em aberto, crédito e saldo."""
    data = defaultdict(lambda: {"billed": ZERO, "paid": ZERO, "open": ZERO})
    names = {}

    def key_of(customer_id, supplier_id, name):
        key = ("c", customer_id) if customer_id else ("s", supplier_id)
        names[key] = name
        return key

    for t in titles.filter(issue_date__range=(start, end)).exclude(status=TitleStatus.CANCELLED).filter(
            Q(customer__isnull=False) | Q(supplier__isnull=False)).values(
            "customer_id", "supplier_id", "customer__name", "supplier__name").annotate(v=Sum("total")):
        key = key_of(t["customer_id"], t["supplier_id"], t["customer__name"] or t["supplier__name"])
        data[key]["billed"] += t["v"]
    moved = txs.filter(date__range=(start, end), transfer_pair__isnull=True)
    for field, kind in (("installment__title__customer", "c"), ("installment__title__supplier", "s"),
                        ("customer", "c"), ("supplier", "s")):
        for r in moved.filter(**{f"{field}__isnull": False}).values(ref=F(field), label=F(f"{field}__name")).annotate(
                i=Coalesce(Sum("amount", filter=Q(kind=IN)), ZERO), o=Coalesce(Sum("amount", filter=Q(kind=OUT)), ZERO)):
            key = (kind, r["ref"])
            names[key] = r["label"]
            # cliente: o que ele pagou (entradas); fornecedor: o que se pagou a ele (saídas)
            data[key]["paid"] += (r["i"] - r["o"]) if kind == "c" else (r["o"] - r["i"])
    open_parts = Installment.all_objects.filter(account=account, status__in=OPEN, deleted_at__isnull=True,
                                                title__in=titles.exclude(status=TitleStatus.CANCELLED))
    for p in open_parts.filter(Q(title__customer__isnull=False) | Q(title__supplier__isnull=False)).select_related(
            "title__customer", "title__supplier"):
        title = p.title
        key = key_of(title.customer_id, title.supplier_id, (title.customer or title.supplier).name)
        data[key]["open"] += p.balance
    rows = []
    # Crédito de todas as partes em 4 consultas (antes: 2 consultas + a busca da parte, por parte).
    credits = finance.party_credits(customer_ids=[pk for kind, pk in data if kind == "c"],
                                    supplier_ids=[pk for kind, pk in data if kind == "s"])
    for key, row in data.items():
        credit = max(credits.get(key, ZERO), ZERO)
        rows.append({"name": names.get(key) or "—", "type": "Cliente" if key[0] == "c" else "Fornecedor",
                     "billed": row["billed"], "paid": row["paid"], "open": row["open"], "credit": credit,
                     "balance": row["open"] - credit})
    return sorted(rows, key=lambda r: (r["type"], -r["balance"]))


def closing(account, store, params):
    ensure_recurring(account)
    start, end = _window(params)
    d = dre.build(account, store, params)
    accounts = list(cash_flow.visible_accounts(account, store))
    txs = FinancialTransaction.all_objects.filter(financial_account__in=accounts, deleted_at__isnull=True)
    in_period = txs.filter(date__range=(start, end))
    cash = in_period.filter(transfer_pair__isnull=True)
    inflow = cash.filter(kind=IN).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"].quantize(CENTS)
    outflow = cash.filter(kind=OUT).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"].quantize(CENTS)
    revenue = d["net_revenue"].quantize(CENTS)
    result = d["operating_result"].quantize(CENTS)
    costs = revenue - result

    titles = _scoped(FinancialTitle.all_objects.filter(account=account, deleted_at__isnull=True), store)
    partners, refunds = _reimbursements(accounts, txs, start, end, result)
    parties = _parties(account, store, titles, txs, start, end)
    open_parts = list(Installment.all_objects.filter(
        account=account, status__in=OPEN, deleted_at__isnull=True, title__in=titles, due_date__range=(start, end))
        .select_related("title__customer", "title__supplier").order_by("due_date")[:TABLE_MAX])
    owed_partners = sum((p["owed"] for p in partners), ZERO)
    partner_spent = sum((p["paid_period"] for p in partners), ZERO)

    # Contas a receber: SÓ as parcelas que vencem no período (pela data de vencimento).
    # A receber no período = Recebido + Falta receber; o que venceu antes e segue em aberto é "Atrasado de antes".
    receivables = titles.filter(kind=FinancialTitle.Kind.RECEIVABLE)
    parts = Installment.all_objects.filter(account=account, deleted_at__isnull=True, title__in=receivables).exclude(
        status=TitleStatus.CANCELLED)
    due_parts = list(parts.filter(due_date__range=(start, end)))
    due_total = sum((p.amount + p.interest + p.fine - p.discount for p in due_parts), ZERO).quantize(CENTS)
    open_this_period = sum((p.balance for p in due_parts if p.status in OPEN), ZERO).quantize(CENTS)
    received = due_total - open_this_period
    due_paid = sum(1 for p in due_parts if p.status == TitleStatus.PAID)
    due_open = sum(1 for p in due_parts if p.status in OPEN)
    old_parts = list(parts.filter(status__in=OPEN, due_date__lt=start))
    open_before = sum((p.balance for p in old_parts), ZERO).quantize(CENTS)
    sales_revenue = (d["gross_revenue"] + d["freight"] - d["discounts"] - d["returns"]).quantize(CENTS)
    services_revenue = d["other_revenue_total"].quantize(CENTS)
    payables = titles.filter(kind=FinancialTitle.Kind.PAYABLE, issue_date__range=(start, end)).exclude(
        status=TitleStatus.CANCELLED)
    payable_count = payables.count()
    partner_items = sum(1 for r in refunds if start <= r["date"] <= end)
    payable_open = sum((p.balance for p in open_parts if p.title.kind == FinancialTitle.Kind.PAYABLE), ZERO)

    period_q = {"date_from": start.isoformat(), "date_to": end.isoformat()}
    issue_q = {"issue_date__gte": start.isoformat(), "issue_date__lte": end.isoformat()}
    due_q = {"due_date__gte": start.isoformat(), "due_date__lte": end.isoformat()}

    def plural(n, one, many):
        return f"{n} {one if n == 1 else many}"

    def card(label, value, fmt="money", *, link, icon, hint="", good="up", tone=None, count=None):
        """`count`: a quantidade que acompanha o valor no MESMO card (ex.: "3 contas")."""
        out = kpi(label, value, fmt, good=good, hint=hint)
        out.update(link=link, icon=icon, tone=tone, count=count)
        return out

    balances = [{"name": a.name, "kind": a.get_kind_display(),
                 "balance": a.opening_balance + _net(txs.filter(financial_account=a, date__lte=end))} for a in accounts]
    revenue_rows = [{"label": "Vendas (PDV/pedidos)", "value": d["gross_revenue"] + d["freight"] - d["discounts"] - d["returns"]},
                    *({"label": r["category"], "value": r["amount"]} for r in d["other_revenue"])]
    expense_rows = [{"label": e["category"], "value": e["amount"]} for e in d["expenses"]] + [
        {**r, "value": r["value"].quantize(CENTS)} for r in
        [{"label": "CMV (custo das mercadorias)", "value": d["cmv"]}, {"label": "Taxas de cartão", "value": d["card_fees"]},
         {"label": "Comissões", "value": d["commissions"]}] if r["value"]]
    lines = list(in_period.select_related("financial_account", "category", "customer", "supplier",
                                          "installment__title__customer", "installment__title__supplier")
                 .order_by("date", "created_at")[:TABLE_MAX])
    recurrences = _scoped(RecurringTitle.all_objects.filter(account=account, deleted_at__isnull=True, is_active=True), store) \
        .select_related("customer", "supplier", "category")
    money_col = {"format": "money"}

    return _report("Fechamento financeiro", "O resultado de tudo no período: faturamento, contas, custos, reembolsos aos "
                   "reembolsos, clientes e fornecedores e todos os lançamentos. Clique num card para abrir a tela dele.", params, [
        card("Faturamento total", revenue, icon="pi pi-chart-line", link={"path": "/relatorios/dre", "query": period_q},
             count=f"{brl(sales_revenue)} vendas · {brl(services_revenue)} serviços",
             hint="tudo o que foi vendido/cobrado no período (competência), pago ou não"),
        card("A receber no período", due_total, icon="pi pi-calendar", count=plural(len(due_parts), "parcela", "parcelas"),
             link={"path": "/cadastros/vencimentos", "query": {"title__kind": "receivable", **due_q}},
             hint="parcelas que vencem no período = recebido + falta receber"),
        card("Recebido", received, icon="pi pi-check-circle", tone="good",
             count=f"{due_paid} de {plural(len(due_parts), 'parcela paga', 'parcelas pagas')}" if due_parts else None,
             link={"path": "/cadastros/vencimentos", "query": {"title__kind": "receivable", "status": "paid", **due_q}},
             hint="das parcelas que vencem no período, o que já foi pago"),
        card("Falta receber", open_this_period, icon="pi pi-clock", good="down",
             tone="bad" if open_this_period else None,
             count=plural(due_open, "parcela em aberto", "parcelas em aberto"),
             link={"path": "/cadastros/vencimentos", "query": {"title__kind": "receivable", "status": "open", **due_q}},
             hint="das parcelas que vencem no período, o que ainda não foi pago"),
        card("Atrasado de antes", open_before, icon="pi pi-history", good="down", tone="bad" if open_before else None,
             count=plural(len(old_parts), "parcela", "parcelas"),
             link={"path": "/cadastros/vencimentos", "query": {"title__kind": "receivable", "status": "open",
                                                               "due_date__lte": (start - timedelta(days=1)).isoformat()}},
             hint="venceram antes do período e seguem sem pagamento"),
        card("Custo total", costs, icon="pi pi-wallet", good="down",
             count=plural(payable_count + partner_items, "conta a pagar", "contas a pagar"),
             link={"path": "/cadastros/contas-a-pagar", "query": issue_q},
             hint=f"todas as despesas, inclusive {brl(partner_spent)} pagas do bolso (reembolso)" if partner_spent
             else "todas as despesas do período"),
        card("Resultado", result, icon="pi pi-calculator", tone="good" if result > 0 else "bad" if result < 0 else None,
             link={"path": "/relatorios/dre", "query": period_q},
             hint=f"faturamento − custo total · margem {pt(d['operating_margin_percent'])}%"),
        card("Reembolso", owed_partners, icon="pi pi-users", good="down",
             tone="bad" if owed_partners else None,
             count=plural(sum(p["items"] for p in partners), "item pendente", "itens pendentes") if partners else None,
             link={"path": "/cadastros/contas-financeiras", "query": {"kind": "partner"}},
             hint="a devolver, por pessoa e item a item, logo abaixo" if partners
             else "cadastre uma conta do tipo Conta de reembolso"),
    ], [
        {"type": "table", "title": "Reembolso por pessoa", "span": "full",
         "description": "Quanto a empresa deve a cada pessoa pelas despesas que ela pagou do bolso. Reembolsar = "
                        "transferência do banco para a conta dele (Financeiro → Transferir).",
         "columns": [{"key": "name", "label": "Conta de reembolso"}, {"key": "paid_period", "label": "Pagou no período", **money_col},
                     {"key": "paid", "label": "Pagou (total)", **money_col},
                     {"key": "reimbursed", "label": "Já reembolsado", **money_col},
                     {"key": "items", "label": "Itens pendentes", "format": "number"},
                     {"key": "owed", "label": "A reembolsar", **money_col}],
         "rows": [*partners, *([{"name": "Total", "strong": True,
                                 **{k: sum((p[k] for p in partners), ZERO) for k in ("paid_period", "paid", "reimbursed", "owed")},
                                 "items": sum(p["items"] for p in partners)}] if len(partners) > 1 else [])],
         "empty": "Nenhuma conta de reembolso: cadastre em Contas financeiras com o tipo \"Conta de reembolso\"."},
        {"type": "table", "title": "Itens a reembolsar", "span": "full",
         "description": "Cada despesa paga do bolso. As abas separam por pessoa (com o total pendente); busque por "
                        "pessoa, descrição ou categoria e filtre por faixa de valor.",
         "tabs": {"key": "partner", "label": "", "sum": "pending"}, "search": True, "range": "amount",
         "columns": [{"key": "date", "label": "Data", "format": "date"}, {"key": "partner", "label": "Quem pagou"},
                     {"key": "description", "label": "Descrição"}, {"key": "category", "label": "Categoria"},
                     {"key": "who", "label": "Pago a"}, {"key": "amount", "label": "Valor", **money_col},
                     {"key": "reimbursed", "label": "Reembolsado", **money_col},
                     {"key": "pending", "label": "Falta", **money_col}, {"key": "status", "label": "Situação"}],
         "rows": refunds, "empty": "Nenhuma despesa paga do bolso até o fim do período."},
        {"type": "table", "title": "Divisão do resultado", "span": "half",
         "description": "Lucro do período × % de cada um (com prejuízo, zero; sem %, só o reembolso) + o que falta reembolsar.",
         "columns": [{"key": "name", "label": "Conta de reembolso"}, {"key": "share_pct", "label": "%", "format": "percent"},
                     {"key": "share", "label": "Parte no lucro", **money_col},
                     {"key": "owed", "label": "A reembolsar", **money_col},
                     {"key": "total", "label": "Total a receber", **money_col}],
         "rows": partners},
        {"type": "table", "title": "Saldos das contas no fim do período", "span": "half",
         "columns": [{"key": "name", "label": "Conta"}, {"key": "kind", "label": "Tipo"},
                     {"key": "balance", "label": "Saldo", **money_col}], "rows": balances},
        {"type": "ranking", "title": "Faturamento por origem", "span": "half", "format": "money", "limit": 8,
         "rows": [r for r in revenue_rows if r["value"]]},
        {"type": "ranking", "title": "Custos por categoria", "span": "half", "format": "money", "limit": 8,
         "rows": expense_rows},
        {"type": "table", "title": "Clientes e fornecedores", "span": "full", "search": True, "range": "balance",
         "tabs": {"key": "type", "label": "", "sum": "balance"},
         "description": "Faturado e pago no período; em aberto, crédito (pago a mais) e saldo de hoje. "
                        "Saldo positivo: cliente que deve / fornecedor a quem se deve. Negativo: crédito.",
         "columns": [{"key": "name", "label": "Nome"}, {"key": "type", "label": "Tipo"},
                     {"key": "billed", "label": "Faturado no período", **money_col},
                     {"key": "paid", "label": "Pago no período", **money_col},
                     {"key": "open", "label": "Em aberto", **money_col},
                     {"key": "credit", "label": "Crédito", **money_col},
                     {"key": "balance", "label": "Saldo", **money_col}],
         "rows": parties},
        {"type": "table", "title": "Parcelas em aberto que vencem no período", "span": "full", "search": True, "range": "open",
         "tabs": {"key": "kind", "label": "", "sum": "open"},
         "description": f"Falta receber {brl(open_this_period)} e pagar {brl(payable_open)} do que vence no período. "
                        f"Atrasado de antes (fora desta lista): {brl(open_before)}.",
         "columns": [{"key": "due", "label": "Vencimento", "format": "date"}, {"key": "kind", "label": "Tipo"},
                     {"key": "who", "label": "Cliente / fornecedor"}, {"key": "description", "label": "Descrição"},
                     {"key": "open", "label": "Em aberto", **money_col}],
         "rows": [{"due": p.due_date, "kind": p.title.get_kind_display(), "description": p.title.description,
                   "who": (p.title.customer or p.title.supplier).name if (p.title.customer_id or p.title.supplier_id) else "—",
                   "open": p.balance} for p in open_parts]},
        {"type": "table", "title": "Contas recorrentes", "span": "full", "search": True,
         "columns": [{"key": "description", "label": "Descrição"}, {"key": "who", "label": "Cliente / fornecedor"},
                     {"key": "kind", "label": "Tipo"}, {"key": "amount", "label": "Valor", **money_col},
                     {"key": "next", "label": "Próximo vencimento", "format": "date"}],
         "rows": [{"description": r.description, "kind": r.get_kind_display(), "amount": r.amount,
                   "who": (r.customer or r.supplier).name if (r.customer_id or r.supplier_id) else "—",
                   "next": (recurring.upcoming(r, 1) or [None])[0]} for r in recurrences]},
        {"type": "table", "title": "Todos os lançamentos do período", "span": "full", "search": True, "range": "amount",
         "tabs": {"key": "kind", "label": "", "sum": "amount", "order": ["Entrada", "Saída", "Transferência", "Estorno"]},
         "description": f"Entrou {brl(inflow)} · saiu {brl(outflow)}. Transferência (inclusive o reembolso) "
                        "só muda o dinheiro de conta: não é receita nem despesa.",
         "columns": [{"key": "date", "label": "Data", "format": "date"}, {"key": "account", "label": "Conta"},
                     {"key": "kind", "label": "Tipo"}, {"key": "description", "label": "Descrição"},
                     {"key": "category", "label": "Categoria"}, {"key": "who", "label": "Cliente / fornecedor"},
                     {"key": "amount", "label": "Valor", **money_col}],
         "rows": [{"date": t.date, "account": t.financial_account.name, "kind": _kind_label(t),
                   "description": t.description, "category": t.category.name if t.category_id else "",
                   "who": _party_name(t), "amount": t.amount if t.kind == IN else -t.amount} for t in lines]},
    ])
