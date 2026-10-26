"""Livro de relatórios: cada relatório devolve o MESMO formato, desenhado por uma só tela.

    {"title", "subtitle", "period": {"from", "to"}, "grain": "day" | "week" | "month",
     "filters": [{"name", "label", "options": [{"label", "value"}]}],
     "kpis":    [{"label", "value", "format", "delta", "good", "hint"}],
     "blocks":  [{"type": "line" | "bars" | "ranking" | "share" | "heatmap" | "waterfall" | "table",
                  "title", "description", "span": "full" | "half", ...}]}

`format`: money | number (inteiro) | decimal (1 casa: médias) | quantity | percent | text. `delta`: variação % contra o período
anterior de mesmo tamanho (`good`: "up" quando subir é bom, "down" quando cair é bom).
`filters`: os filtros próprios do relatório, com as opções já prontas (quem vê o relatório
não precisa ver o cadastro de vendedores, categorias...); o valor volta como parâmetro.
Séries no tempo agrupam sozinhas: até 45 dias por dia, até ~7 meses por semana, além por mês.
Os recortes de venda partem de `reports.completed_sales` (os números batem com o painel);
sem filial ativa, a rede permitida ao usuário (`scope_to_allowed`).
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Min, Q, Sum
from django.db.models.functions import Abs, Coalesce, TruncDate
from django.utils import timezone

from starrp.models import (
    Brand, Category, Commission, Customer, CustomerGroup, FinancialAccount, Installment, Payment, PaymentMethod,
    ReceivingDivergence, Sale, SaleItem, StockBalance, StockMovement, Supplier, TitleStatus,
    UserProfile, Warehouse,
)
from starrp.services import cash_flow, dre, reports
from starrp.services.store_access import scope_to_allowed

ZERO = Decimal("0")
OTHERS = "Outros"
WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
# Tabelas vêm completas (a tela pagina e exporta tudo); o teto só protege de um período absurdo.
TABLE_MAX = 5000
COST = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18, decimal_places=4))


# ── base ────────────────────────────────────────────────────────────────────
def _window(params):
    start, end = reports.period(params)
    return start.date(), end.date()


def _previous(params):
    """O período anterior de mesmo tamanho (30 dias → os 30 dias antes), com os mesmos filtros."""
    start, end = _window(params)
    days = (end - start).days + 1
    return {**{key: params.get(key) for key in params}, "date_from": str(start - timedelta(days=days)),
            "date_to": str(start - timedelta(days=1))}


def _delta(current, previous):
    if not previous:
        return None
    return ((Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100).quantize(Decimal("0.1"))


def kpi(label, value, fmt="money", *, previous=None, good="up", hint=""):
    return {"label": label, "value": value, "format": fmt, "good": good, "hint": hint,
            "delta": _delta(value, previous) if previous is not None else None}


def _pct(part, whole):
    return (Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1")) if whole else ZERO


def pt(value):
    """Número para texto pt-BR ("45.5" → "45,5"), para as dicas dos indicadores."""
    return f"{Decimal(value):f}".replace(".", ",")


def brl(value):
    """R$ em texto pt-BR ("R$ 1.650,06"), para as dicas dos indicadores."""
    text = f"{Decimal(value).quantize(Decimal('0.01')):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}".replace("R$ -", "-R$ ")


def _ticket(total, count):
    return (Decimal(total) / count).quantize(Decimal("0.01")) if count else ZERO


def _top(rows, limit=6, label="label", value="value"):
    """Até `limit - 1` fatias e o resto somado em "Outros" (cores fixas, nunca uma 9ª)."""
    rows = sorted(rows, key=lambda r: -Decimal(r[value] or 0))
    if len(rows) <= limit:
        return rows
    rest = sum((Decimal(r[value] or 0) for r in rows[limit - 1:]), ZERO)
    return [*rows[:limit - 1], {label: OTHERS, value: rest}]


def _scoped(qs, store, field="store"):
    return qs.filter(**{field: store}) if store is not None else scope_to_allowed(qs, field)


def _report(title, subtitle, params, kpis, blocks, filters=()):
    start, end = _window(params)
    return {"title": title, "subtitle": subtitle, "period": {"from": start, "to": end}, "grain": _grain(params),
            "filters": list(filters), "kpis": kpis, "blocks": blocks}


# ── tempo: dia, semana ou mês conforme o tamanho do período ─────────────────
def _grain(params):
    start, end = _window(params)
    days = (end - start).days + 1
    return "day" if days <= 45 else "week" if days <= 210 else "month"


def _bucket(day, grain):
    if grain == "week":
        return day - timedelta(days=day.weekday())
    if grain == "month":
        return day.replace(day=1)
    return day


def _buckets(params):
    """As chaves (início de cada dia/semana/mês) e a data ISO de cada uma, na ordem. O gráfico
    recebe a data + o `grain` e formata sozinho (eixo curto, balão por extenso)."""
    start, end = _window(params)
    grain = _grain(params)
    keys, cursor = [], start
    while cursor <= end:
        key = _bucket(cursor, grain)
        if key not in keys:
            keys.append(key)
        cursor += timedelta(days=1)
    return keys, [k.isoformat() for k in keys]


WEEKDAY_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MONTH_NAMES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
               "Novembro", "Dezembro"]


def period_label(key, grain):
    """Período por extenso, pt-BR, para tabela/Excel/impressão: "24/10/2026 (sáb)",
    "19/10 a 25/10/2026", "Outubro/2026"."""
    if grain == "week":
        end = key + timedelta(days=6)
        return f"{key:%d/%m} a {end:%d/%m/%Y}" if key.year == end.year else f"{key:%d/%m/%Y} a {end:%d/%m/%Y}"
    if grain == "month":
        return f"{MONTH_NAMES[key.month - 1]}/{key.year}"
    return f"{key:%d/%m/%Y} ({WEEKDAY_SHORT[key.weekday()]})"


def _series(rows, keys, grain, field):
    """Soma `field` de linhas {"day", field} em cada balde (dia/semana/mês)."""
    acc = defaultdict(lambda: ZERO)
    for row in rows:
        if row["day"] is not None:
            acc[_bucket(row["day"], grain)] += Decimal(row[field] or 0)
    return [acc[k] for k in keys]


GRAIN_WORD = {"day": "por dia", "week": "por semana", "month": "por mês"}


# ── filtros próprios de cada relatório (opções prontas) ─────────────────────
def _choice(name, label, options):
    return {"name": name, "label": label, "options": [{"label": str(lbl), "value": str(val)} for val, lbl in options]}


def f_sellers(account, store):
    profiles = UserProfile.all_objects.filter(account=account, is_seller=True, is_active=True)
    if store is not None:
        profiles = profiles.filter(Q(all_stores=True) | Q(stores=store)).distinct()
    rows = profiles.select_related("user").order_by("user__first_name")
    return _choice("seller", "Vendedor", [(p.user_id, p.user.get_full_name() or p.user.username) for p in rows])


def f_methods(account):
    return _choice("method", "Forma de pagamento", PaymentMethod.all_objects.filter(
        account=account, deleted_at__isnull=True).order_by("name").values_list("pk", "name"))


def f_channels():
    return _choice("channel", "Canal", Sale._meta.get_field("channel").choices)


def f_categories(account):
    return _choice("category", "Categoria", Category.all_objects.filter(
        account=account, deleted_at__isnull=True).order_by("name").values_list("pk", "name")[:1000])


def f_brands(account):
    return _choice("brand", "Marca", Brand.all_objects.filter(
        account=account, deleted_at__isnull=True).order_by("name").values_list("pk", "name")[:1000])


def f_groups(account):
    return _choice("customer_group", "Grupo de clientes", CustomerGroup.all_objects.filter(
        account=account, deleted_at__isnull=True).order_by("name").values_list("pk", "name"))


def f_warehouses(account, store):
    return _choice("warehouse", "Depósito", _scoped(Warehouse.all_objects.filter(
        account=account, deleted_at__isnull=True), store).order_by("name").values_list("pk", "name"))


def f_suppliers(account):
    return _choice("supplier", "Fornecedor", Supplier.all_objects.filter(
        account=account, deleted_at__isnull=True).order_by("name").values_list("pk", "name")[:1000])


# ── vendas com os filtros (canal, forma, categoria, marca, grupo de clientes) ─
def _sales(account, store, params):
    qs = reports.completed_sales(account, store, params)
    if params.get("channel"):
        qs = qs.filter(channel=params["channel"])
    if params.get("method"):
        qs = qs.filter(pk__in=Payment.all_objects.filter(method_id=params["method"],
                                                         status=Payment.Status.APPROVED).values("sale_id"))
    if params.get("customer_group"):
        qs = qs.filter(customer__groups=params["customer_group"])
    item_filter = _item_q(params)
    if item_filter:
        qs = qs.filter(pk__in=SaleItem.all_objects.filter(item_filter, status=SaleItem.Status.ACTIVE).values("sale_id"))
    return qs.distinct() if params.get("customer_group") else qs


def _item_q(params, prefix="variant__product__"):
    q = Q()
    if params.get("category"):
        q &= Q(**{f"{prefix}category_id": params["category"]})
    if params.get("brand"):
        q &= Q(**{f"{prefix}brand_id": params["brand"]})
    return q


def _items(sales, params):
    """Itens das vendas; com categoria/marca no filtro, só os itens dela (não a venda inteira)."""
    return SaleItem.all_objects.filter(Q(sale__in=sales) & _item_q(params), status=SaleItem.Status.ACTIVE)


def _margin(items):
    agg = items.aggregate(revenue=Coalesce(Sum("total"), ZERO), cost=Coalesce(Sum(COST), ZERO))
    return agg["revenue"] - agg["cost"]


def _sales_totals(sales):
    agg = sales.aggregate(count=Count("id"), revenue=Coalesce(Sum("total"), ZERO))
    return agg["count"], agg["revenue"]


def _by_day(qs, field, value="total", date_field="completed_at"):
    return qs.annotate(day=TruncDate(date_field)).values("day").annotate(**{field: Sum(value)})


SALES_FILTERS = ("channel", "method", "seller", "category", "brand", "customer_group")


def _sales_filters(account, store, *names):
    builders = {"channel": f_channels, "method": lambda: f_methods(account), "seller": lambda: f_sellers(account, store),
                "category": lambda: f_categories(account), "brand": lambda: f_brands(account),
                "customer_group": lambda: f_groups(account)}
    return [builders[n]() for n in names]


# ── Movimento ───────────────────────────────────────────────────────────────
def movement_sales(account, store, params):
    sales, before = _sales(account, store, params), _sales(account, store, _previous(params))
    count, revenue = _sales_totals(sales)
    prev_count, prev_revenue = _sales_totals(before)
    margin, prev_margin = _margin(_items(sales, params)), _margin(_items(before, params))
    discounts = sales.aggregate(t=Coalesce(Sum("discount"), ZERO) + Coalesce(Sum("coupon_discount"), ZERO))["t"]
    grain, (keys, labels) = _grain(params), _buckets(params)
    prev_keys, _ = _buckets(_previous(params))
    now_rev = _series(_by_day(sales, "revenue"), keys, grain, "revenue")
    then_rev = _series(_by_day(before, "revenue"), prev_keys, grain, "revenue")[:len(keys)]
    now_count = _series(sales.annotate(day=TruncDate("completed_at")).values("day").annotate(n=Count("id")), keys, grain, "n")
    channel_label = dict(Sale._meta.get_field("channel").choices)
    by_channel = sales.values("channel").annotate(value=Sum("total"))
    word = GRAIN_WORD[grain]
    return _report("Vendas no período", "Faturamento das vendas concluídas contra o mesmo período imediatamente anterior.",
                   params, [
                       kpi("Faturamento", revenue, previous=prev_revenue),
                       kpi("Vendas", count, "number", previous=prev_count),
                       kpi("Ticket médio", _ticket(revenue, count), previous=_ticket(prev_revenue, prev_count)),
                       kpi("Margem bruta", margin, previous=prev_margin, hint=f"{pt(_pct(margin, revenue))}% do faturamento"),
                       kpi("Descontos concedidos", discounts, good="down", hint=f"{pt(_pct(discounts, revenue + discounts))}% do bruto"),
                   ], [
                       {"type": "line", "title": f"Faturamento {word}", "span": "full", "format": "money",
                        "description": "A linha laranja é o período anterior, alinhado dia a dia: mostra se o ritmo melhorou.",
                        "grain": grain, "x": labels, "series": [{"name": "Período atual", "values": now_rev},
                                                {"name": "Período anterior", "values": then_rev}]},
                       {"type": "bars", "title": f"Quantidade de vendas {word}", "span": "half", "format": "number",
                        "description": "Volume de atendimentos fechados (independe do valor).",
                        "grain": grain, "x": labels, "series": [{"name": "Vendas", "values": now_count}]},
                       {"type": "share", "title": "Faturamento por canal", "span": "half", "format": "money",
                        "description": "Onde a venda aconteceu: PDV, retaguarda, PDV móvel ou loja virtual.",
                        "rows": [{"label": channel_label.get(r["channel"], r["channel"]), "value": r["value"]}
                                 for r in by_channel]},
                       {"type": "table", "title": "Detalhe " + word, "span": "full", "columns": [
                           {"key": "label", "label": "Período"}, {"key": "count", "label": "Vendas", "format": "number"},
                           {"key": "revenue", "label": "Faturamento", "format": "money"},
                           {"key": "ticket", "label": "Ticket médio", "format": "money"},
                           {"key": "previous", "label": "Período anterior", "format": "money"}],
                        "rows": [{"label": period_label(k, grain), "count": int(c), "revenue": r, "ticket": _ticket(r, int(c)),
                                  "previous": p}
                                 for k, c, r, p in zip(keys, now_count, now_rev, then_rev + [ZERO] * len(keys),
                                                       strict=False) if c][::-1]},
                   ], _sales_filters(account, store, *SALES_FILTERS))


def movement_hours(account, store, params):
    sales = _sales(account, store, params)
    measure = params.get("measure") or "revenue"
    tz = timezone.get_current_timezone()
    revenue, counts = defaultdict(lambda: ZERO), defaultdict(int)
    for moment, total in sales.values_list("completed_at", "total"):
        local = moment.astimezone(tz)
        key = ((local.weekday() + 1) % 7, local.hour)  # domingo primeiro
        revenue[key] += total
        counts[key] += 1
    grid = revenue if measure == "revenue" else counts
    fmt = "money" if measure == "revenue" else "number"
    used = sorted({h for _, h in revenue}) or list(range(8, 19))
    hours = list(range(min(used), max(used) + 1))
    by_hour = [sum((grid[(d, h)] for d in range(7)), 0) for h in hours]
    by_weekday = [{"label": WEEKDAYS[d], "value": sum((grid[(d, h)] for h in hours), 0)} for d in range(7)]
    peak_hour = hours[by_hour.index(max(by_hour))] if any(by_hour) else None
    peak_day = max(by_weekday, key=lambda r: r["value"]) if any(r["value"] for r in by_weekday) else None
    weak_day = min(by_weekday, key=lambda r: r["value"]) if peak_day else None
    total_count = sum(counts.values())
    word = "Faturamento" if measure == "revenue" else "Vendas"
    return _report("Horários de pico", "Quando a filial mais vende: cruza o dia da semana com a hora do dia.", params, [
        kpi("Horário de pico", f"{peak_hour}h às {peak_hour + 1}h" if peak_hour is not None else "—", "text"),
        kpi("Dia mais forte", peak_day["label"] if peak_day else "—", "text"),
        kpi("Dia mais fraco", weak_day["label"] if weak_day else "—", "text", hint="bom para promoções e folgas"),
        kpi("Vendas no período", total_count, "number"),
    ], [
        {"type": "heatmap", "title": f"{word} por dia da semana e hora", "span": "full", "format": fmt,
         "description": "Quanto mais escuro, mais movimento. Use para escalar equipe e caixas nos horários fortes.",
         "rows": WEEKDAYS, "cols": [f"{h}h" for h in hours], "values": [[grid[(d, h)] for h in hours] for d in range(7)]},
        {"type": "bars", "title": f"{word} por hora do dia", "span": "half", "format": fmt,
         "description": "Somando todos os dias da semana.",
         "x": [f"{h}h" for h in hours], "series": [{"name": word, "values": by_hour}]},
        {"type": "ranking", "title": f"{word} por dia da semana", "span": "half", "format": fmt, "limit": 7, "ordered": False,
         "description": "Na ordem da semana (domingo a sábado).", "rows": by_weekday},
        {"type": "table", "title": "Faixas com movimento", "span": "full", "columns": [
            {"key": "day", "label": "Dia"}, {"key": "hour", "label": "Hora"},
            {"key": "count", "label": "Vendas", "format": "number"},
            {"key": "revenue", "label": "Faturamento", "format": "money"},
            {"key": "ticket", "label": "Ticket médio", "format": "money"}],
         "rows": sorted(({"day": WEEKDAYS[d], "hour": f"{h}h às {h + 1}h", "count": counts[(d, h)], "revenue": revenue[(d, h)],
                          "ticket": _ticket(revenue[(d, h)], counts[(d, h)])} for (d, h) in revenue),
                        key=lambda r: -r["revenue"])},
    ], [_choice("measure", "Medir por", [("revenue", "Faturamento"), ("count", "Quantidade de vendas")]),
        *_sales_filters(account, store, "channel", "seller", "category")])


def movement_payments(account, store, params):
    sales = _sales(account, store, {k: v for k, v in params.items() if k != "method"})
    payments = Payment.all_objects.filter(sale__in=sales, status=Payment.Status.APPROVED)
    if params.get("method"):
        payments = payments.filter(method_id=params["method"])
    rows = list(payments.values("method__name").annotate(value=Sum("amount"), count=Count("id")).order_by("-value"))
    total = sum((r["value"] for r in rows), ZERO)
    # As mesmas 6 formas (+ "Outros") nas barras e na participação: a cor segue a forma nos dois.
    top = [r["method__name"] for r in rows[:6]]
    grain, (keys, labels) = _grain(params), _buckets(params)
    per = defaultdict(list)
    for row in payments.annotate(day=TruncDate("sale__completed_at")).values("day", "method__name").annotate(v=Sum("amount")):
        per[row["method__name"] if row["method__name"] in top else OTHERS].append({"day": row["day"], "v": row["v"]})
    names = top + ([OTHERS] if OTHERS in per else [])
    before = Payment.all_objects.filter(sale__in=_sales(account, store, _previous(params)),
                                        status=Payment.Status.APPROVED).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
    fees = sum((Decimal(r["value"]) * Decimal(m.fee_percent or 0) / 100 for r in rows
                for m in PaymentMethod.all_objects.filter(account=account, name=r["method__name"])[:1]), ZERO)
    return _report("Formas de recebimento", "Como os clientes pagaram: participação de cada forma e o custo das taxas.",
                   params, [
                       kpi("Total recebido", total, previous=before),
                       kpi("Pagamentos", sum(r["count"] for r in rows), "number"),
                       kpi("Forma principal", rows[0]["method__name"] if rows else "—", "text",
                           hint=f"{pt(_pct(rows[0]['value'], total))}% do recebido" if rows else ""),
                       kpi("Taxas estimadas", fees.quantize(Decimal("0.01")), good="down",
                           hint="pela taxa cadastrada em cada forma"),
                   ], [
                       {"type": "bars", "title": f"Recebido {GRAIN_WORD[grain]}", "span": "full", "format": "money",
                        "stacked": True, "description": "Cada cor é uma forma de pagamento; a altura total é o recebido.",
                        "grain": grain, "x": labels, "series": [{"name": n, "values": _series(per[n], keys, grain, "v")} for n in names]},
                       {"type": "share", "title": "Participação no recebido", "span": "half", "format": "money",
                        "rows": _top([{"label": r["method__name"], "value": r["value"]} for r in rows], limit=7)},
                       {"type": "ranking", "title": "Valor médio por pagamento", "span": "half", "format": "money",
                        "description": "Formas com valor médio alto costumam ser parceladas.",
                        "rows": sorted(({"label": r["method__name"], "value": _ticket(r["value"], r["count"]),
                                         "sub": f"{r['count']} pagamento(s)"} for r in rows), key=lambda r: -r["value"])},
                       {"type": "table", "title": "Resumo por forma", "span": "full", "columns": [
                           {"key": "method", "label": "Forma"}, {"key": "count", "label": "Pagamentos", "format": "number"},
                           {"key": "value", "label": "Recebido", "format": "money"},
                           {"key": "avg", "label": "Valor médio", "format": "money"},
                           {"key": "share", "label": "Participação", "format": "percent"}],
                        "rows": [{"method": r["method__name"], "count": r["count"], "value": r["value"],
                                  "avg": _ticket(r["value"], r["count"]), "share": _pct(r["value"], total)} for r in rows]},
                   ], _sales_filters(account, store, "method", "channel", "seller"))


def movement_sellers(account, store, params):
    sales = _sales(account, store, params).filter(seller__isnull=False)
    rows = list(sales.values("seller_id", "seller__first_name", "seller__last_name", "seller__username").annotate(
        count=Count("id"), revenue=Sum("total"), discount=Coalesce(Sum("discount"), ZERO) + Coalesce(Sum("coupon_discount"), ZERO))
        .order_by("-revenue"))
    commission = {r["seller_id"]: r["total"] for r in Commission.all_objects.filter(sale__in=sales).exclude(
        status=Commission.Status.CANCELLED).values("seller_id").annotate(total=Sum("amount"))}
    prev = dict(_sales(account, store, _previous(params)).filter(seller__isnull=False).values_list("seller_id")
                .annotate(t=Sum("total")))
    total = sum((r["revenue"] for r in rows), ZERO)
    for r in rows:
        r["name"] = " ".join(filter(None, [r["seller__first_name"], r["seller__last_name"]])) or r["seller__username"]
        r["ticket"], r["commission"] = _ticket(r["revenue"], r["count"]), commission.get(r["seller_id"], ZERO)
        r["discount_pct"], r["share"] = _pct(r["discount"], r["revenue"] + r["discount"]), _pct(r["revenue"], total)
        r["growth"] = _delta(r["revenue"], prev.get(r["seller_id"])) or ZERO
    best = rows[0] if rows else None
    return _report("Desempenho de vendedores", "Quem vendeu mais, com que ticket, quanto descontou e quanto ganhou de comissão.",
                   params, [
                       kpi("Vendido com vendedor", total),
                       kpi("Vendedores com venda", len(rows), "number"),
                       kpi("Destaque", best["name"] if best else "—", "text",
                           hint=f"{pt(_pct(best['revenue'], total))}% do total" if best else ""),
                       kpi("Comissões", sum((r["commission"] for r in rows), ZERO), good="down"),
                   ], [
                       {"type": "ranking", "title": "Faturamento por vendedor", "span": "half", "format": "money",
                        "rows": [{"label": r["name"], "value": r["revenue"], "sub": f"{r['count']} venda(s) · {pt(r['share'])}%"}
                                 for r in rows]},
                       {"type": "ranking", "title": "Ticket médio por vendedor", "span": "half", "format": "money",
                        "description": "Quem vende mais por atendimento (venda casada, produto de maior valor).",
                        "rows": sorted(({"label": r["name"], "value": r["ticket"]} for r in rows), key=lambda r: -r["value"])},
                       {"type": "ranking", "title": "Desconto concedido (% do bruto)", "span": "half", "format": "percent",
                        "description": "Desconto alto com ticket baixo pede conversa.",
                        "rows": sorted(({"label": r["name"], "value": r["discount_pct"]} for r in rows),
                                       key=lambda r: -r["value"])},
                       {"type": "ranking", "title": "Crescimento vs. período anterior (%)", "span": "half", "format": "percent",
                        "description": "Barra para a esquerda: vendeu menos que no período anterior.",
                        "rows": sorted(({"label": r["name"], "value": r["growth"]} for r in rows), key=lambda r: -r["value"])},
                       {"type": "table", "title": "Vendedores", "span": "full", "columns": [
                           {"key": "name", "label": "Vendedor"}, {"key": "count", "label": "Vendas", "format": "number"},
                           {"key": "revenue", "label": "Faturamento", "format": "money"},
                           {"key": "ticket", "label": "Ticket médio", "format": "money"},
                           {"key": "discount", "label": "Descontos", "format": "money"},
                           {"key": "commission", "label": "Comissão", "format": "money"},
                           {"key": "share", "label": "Participação", "format": "percent"}], "rows": rows},
                   ], _sales_filters(account, store, "channel", "category", "brand"))


def movement_branches(account, store, params):
    """Comparativo da rede: sempre todas as filiais que o usuário enxerga."""
    sales = _sales(account, None, params)
    rows = list(sales.values("store_id", "store__name").annotate(count=Count("id"), revenue=Sum("total")).order_by("-revenue"))
    margins = {r["sale__store_id"]: (r["revenue"] or 0) - (r["cost"] or 0) for r in _items(sales, params).values(
        "sale__store_id").annotate(revenue=Sum("total"), cost=Sum(COST))}
    prev = dict(_sales(account, None, _previous(params)).values_list("store_id").annotate(t=Sum("total")))
    total = sum((r["revenue"] for r in rows), ZERO)
    for r in rows:
        r["name"], r["margin"] = r["store__name"], margins.get(r["store_id"], ZERO)
        r["ticket"], r["margin_pct"] = _ticket(r["revenue"], r["count"]), _pct(r["margin"], r["revenue"])
        r["growth"] = _delta(r["revenue"], prev.get(r["store_id"])) or ZERO
    best = rows[0] if rows else None
    return _report("Comparativo de filiais", "Faturamento, ticket, margem e crescimento de cada filial lado a lado.", params, [
        kpi("Faturamento da rede", total, previous=sum(prev.values(), ZERO)),
        kpi("Filiais com venda", len(rows), "number"),
        kpi("Filial destaque", best["name"] if best else "—", "text",
            hint=f"{pt(_pct(best['revenue'], total))}% da rede" if best else ""),
        kpi("Ticket médio da rede", _ticket(total, sum(r["count"] for r in rows))),
    ], [
        {"type": "ranking", "title": "Faturamento por filial", "span": "half", "format": "money",
         "rows": [{"label": r["name"], "value": r["revenue"], "sub": f"{r['count']} venda(s)"} for r in rows]},
        {"type": "share", "title": "Participação na rede", "span": "half", "format": "money",
         "rows": _top([{"label": r["name"], "value": r["revenue"]} for r in rows], limit=8)},
        {"type": "ranking", "title": "Margem bruta por filial (%)", "span": "half", "format": "percent",
         "rows": sorted(({"label": r["name"], "value": r["margin_pct"]} for r in rows), key=lambda r: -r["value"])},
        {"type": "ranking", "title": "Crescimento vs. período anterior (%)", "span": "half", "format": "percent",
         "rows": sorted(({"label": r["name"], "value": r["growth"]} for r in rows), key=lambda r: -r["value"])},
        {"type": "table", "title": "Filiais", "span": "full", "columns": [
            {"key": "name", "label": "Filial"}, {"key": "count", "label": "Vendas", "format": "number"},
            {"key": "revenue", "label": "Faturamento", "format": "money"},
            {"key": "ticket", "label": "Ticket médio", "format": "money"},
            {"key": "margin", "label": "Margem bruta", "format": "money"},
            {"key": "margin_pct", "label": "Margem %", "format": "percent"},
            {"key": "growth", "label": "Crescimento", "format": "percent"}], "rows": rows},
    ], _sales_filters(account, None, "channel", "category", "brand"))


# ── Mercadorias ─────────────────────────────────────────────────────────────
def _products(sales, params):
    # `sold_quantity`, e não `quantity`: o campo seria sombreado (agregado dentro de agregado).
    rows = (_items(sales, params).values("variant_id", "description", "sku").annotate(
        sold_quantity=Sum("quantity"), revenue=Sum("total"), cost=Sum(COST)).order_by("-revenue"))
    return [{**r, "margin": (r["revenue"] or 0) - (r["cost"] or 0)} for r in rows]


def goods_abc(account, store, params):
    from starrp.services import report_cross as rx

    measure = params.get("measure") or "revenue"
    rows = _products(_sales(account, store, params), params)
    key = {"revenue": "revenue", "margin": "margin", "quantity": "sold_quantity"}[measure]
    rows.sort(key=lambda r: -Decimal(r[key] or 0))
    total = sum((Decimal(r[key] or 0) for r in rows), ZERO)
    running, classes = ZERO, {"A": [], "B": [], "C": []}
    for index, r in enumerate(rows, start=1):
        running += Decimal(r[key] or 0)
        r["position"], r["share"], r["cumulative"] = index, _pct(r[key], total), _pct(running, total)
        r["abc"] = "A" if r["cumulative"] <= 80 or index == 1 else "B" if r["cumulative"] <= 95 else "C"
        classes[r["abc"]].append(r)
    fmt = "quantity" if measure == "quantity" else "money"
    word = {"revenue": "faturamento", "margin": "margem", "quantity": "quantidade vendida"}[measure]
    share = [{"label": f"Classe {k}", "value": sum((Decimal(r[key] or 0) for r in v), ZERO)} for k, v in classes.items()]
    return _report("Curva ABC de produtos", f"Classifica os produtos pelo {word}: A = até 80% do total, B = os próximos 15%, "
                   "C = o resto.", params, [
                       kpi("Produtos vendidos", len(rows), "number"),
                       kpi("Classe A", len(classes["A"]), "number",
                           hint=f"{pt(_pct(len(classes['A']), len(rows)))}% dos produtos fazem {pt(_pct(share[0]['value'], total))}%"),
                       kpi("Classe B", len(classes["B"]), "number"),
                       kpi("Classe C", len(classes["C"]), "number", hint="candidatos a revisar o mix"),
                   ], [
                       {"type": "share", "title": f"{word.capitalize()} por classe", "span": "half", "format": fmt,
                        "description": "Poucos produtos (A) costumam carregar a maior parte do resultado.", "rows": share},
                       {"type": "share", "title": "Quantidade de produtos por classe", "span": "half", "format": "number",
                        "description": "Compare com o gráfico ao lado: muitos produtos C rendem pouco.",
                        "rows": [{"label": f"Classe {k}", "value": len(v)} for k, v in classes.items()]},
                       {"type": "ranking", "title": f"Os 20 que mais pesam no {word}", "span": "full", "format": fmt, "limit": 10,
                        "rows": [{"label": r["description"], "value": r[key], "sub": f"{pt(r['cumulative'])}% acumulado",
                                  "group": f"Classe {r['abc']}"} for r in rows[:20]]},
                       rx.compare("Cada classe: margem, nota e devolução", rx.PRODUCT_METRICS,
                                  rx.product_class_rows(account, store, params),
                                  "Cruzamento com as avaliações e as devoluções (mais em Cruzamentos › Produtos × qualidade)."),
                       # Abas por classe (Todas / A / B / C): a exportação leva só a aba aberta.
                       {"type": "table", "title": "Curva completa", "span": "full", "tabs": {"key": "abc", "label": "Classe",
                                                                                           "sum": "revenue"},
                        "columns": [
                           {"key": "position", "label": "#", "format": "number"}, {"key": "description", "label": "Produto"},
                           {"key": "sku", "label": "SKU"}, {"key": "sold_quantity", "label": "Qtd.", "format": "quantity"},
                           {"key": "revenue", "label": "Faturamento", "format": "money"},
                           {"key": "margin", "label": "Margem", "format": "money"},
                           {"key": "share", "label": "%", "format": "percent"},
                           {"key": "cumulative", "label": "% acum.", "format": "percent"}, {"key": "abc", "label": "Classe"}],
                        "rows": rows[:TABLE_MAX]},
                   ], [_choice("measure", "Classificar por", [("revenue", "Faturamento"), ("margin", "Margem bruta"),
                                                               ("quantity", "Quantidade vendida")]),
                       *_sales_filters(account, store, "category", "brand", "channel")])


def goods_categories(account, store, params):
    items = _items(_sales(account, store, params), params)
    rows = list(items.values("variant__product__category__name").annotate(
        revenue=Sum("total"), cost=Sum(COST), quantity=Sum("quantity")).order_by("-revenue"))
    brands = list(items.values("variant__product__brand__name").annotate(revenue=Sum("total")).order_by("-revenue"))
    total = sum((r["revenue"] or ZERO for r in rows), ZERO)
    for r in rows:
        r["name"] = r["variant__product__category__name"] or "Sem categoria"
        r["margin"] = (r["revenue"] or 0) - (r["cost"] or 0)
        r["margin_pct"], r["share"] = _pct(r["margin"], r["revenue"]), _pct(r["revenue"], total)
    best_margin = max(rows, key=lambda r: r["margin_pct"]) if rows else None
    return _report("Vendas por categoria", "O que cada categoria e marca fatura e quanto deixa de margem.", params, [
        kpi("Faturamento", total),
        kpi("Categorias com venda", len(rows), "number"),
        kpi("Maior faturamento", rows[0]["name"] if rows else "—", "text", hint=f"{pt(rows[0]['share'])}% do total" if rows else ""),
        kpi("Melhor margem", best_margin["name"] if best_margin else "—", "text",
            hint=f"{pt(best_margin['margin_pct'])}% de margem" if best_margin else ""),
    ], [
        {"type": "ranking", "title": "Faturamento por categoria", "span": "half", "format": "money",
         "rows": [{"label": r["name"], "value": r["revenue"], "sub": f"{pt(r['share'])}% · margem {pt(r['margin_pct'])}%"}
                  for r in rows]},
        {"type": "ranking", "title": "Margem bruta por categoria (%)", "span": "half", "format": "percent",
         "description": "Categoria que fatura muito com margem baixa vende volume, não lucro.",
         "rows": sorted(({"label": r["name"], "value": r["margin_pct"]} for r in rows), key=lambda r: -r["value"])},
        {"type": "share", "title": "Participação no faturamento", "span": "half", "format": "money",
         "rows": _top([{"label": r["name"], "value": r["revenue"]} for r in rows])},
        {"type": "share", "title": "Faturamento por marca", "span": "half", "format": "money",
         "rows": _top([{"label": r["variant__product__brand__name"] or "Sem marca", "value": r["revenue"]} for r in brands])},
        {"type": "table", "title": "Categorias", "span": "full", "columns": [
            {"key": "name", "label": "Categoria"}, {"key": "quantity", "label": "Qtd.", "format": "quantity"},
            {"key": "revenue", "label": "Faturamento", "format": "money"}, {"key": "margin", "label": "Margem", "format": "money"},
            {"key": "margin_pct", "label": "Margem %", "format": "percent"},
            {"key": "share", "label": "Participação", "format": "percent"}], "rows": rows},
    ], _sales_filters(account, store, "brand", "channel", "seller"))


def goods_stock(account, store, params):
    balances = _scoped(StockBalance.all_objects.filter(account=account, quantity__gt=0), store, "warehouse__store")
    if params.get("warehouse"):
        balances = balances.filter(warehouse_id=params["warehouse"])
    balances = balances.filter(_item_q(params, "variant__product__"))
    value_expr = ExpressionWrapper(F("quantity") * F("variant__last_cost"), output_field=DecimalField(max_digits=18, decimal_places=4))
    agg = balances.aggregate(units=Coalesce(Sum("quantity"), ZERO), value=Coalesce(Sum(value_expr), ZERO),
                             skus=Count("variant", distinct=True))
    by_warehouse = list(balances.values("warehouse__name").annotate(value=Sum(value_expr)).order_by("-value"))
    by_category = list(balances.values("variant__product__category__name").annotate(value=Sum(value_expr)).order_by("-value"))
    # `units`, e não `quantity`: sombrearia o campo e o valor viraria agregado dentro de agregado.
    per_variant = list(balances.values("variant_id", "variant__sku", "variant__product__name", "variant__name",
                                       "variant__min_stock").annotate(units=Sum("quantity"), value=Sum(value_expr))
                       .order_by("-value"))
    sold = set(_items(reports.completed_sales(account, store, params), {}).values_list("variant_id", flat=True))
    name = lambda r: " ".join(filter(None, [r["variant__product__name"], r["variant__name"]]))  # noqa: E731
    stale = [r for r in per_variant if r["variant_id"] not in sold]
    below = [r for r in per_variant if r["variant__min_stock"] is not None and r["units"] < r["variant__min_stock"]]
    situation = params.get("situation")
    listed = stale if situation == "stale" else below if situation == "below" else per_variant
    stale_value = sum((r["value"] or ZERO for r in stale), ZERO)
    return _report("Posição de estoque", "Quanto há guardado hoje, quanto vale (pelo último custo) e o que está parado.", params, [
        kpi("Valor em estoque", agg["value"]),
        kpi("Unidades", agg["units"], "quantity"),
        kpi("Parado no período", stale_value, good="down",
            hint=f"{len(stale)} produto(s) sem venda · {pt(_pct(stale_value, agg['value']))}% do valor"),
        kpi("Abaixo do mínimo", len(below), "number", good="down", hint="precisam de reposição"),
    ], [
        {"type": "share", "title": "Valor por depósito", "span": "half", "format": "money",
         "rows": _top([{"label": r["warehouse__name"], "value": r["value"]} for r in by_warehouse])},
        {"type": "ranking", "title": "Valor por categoria", "span": "half", "format": "money", "limit": 6,
         "rows": [{"label": r["variant__product__category__name"] or "Sem categoria", "value": r["value"]} for r in by_category]},
        {"type": "ranking", "title": "Dinheiro parado: maior valor sem venda no período", "span": "full", "format": "money", "limit": 8,
         "description": "Estoque que não girou no período escolhido: candidatos a promoção, devolução ou transferência.",
         "rows": [{"label": name(r), "value": r["value"], "sub": f"{pt(r['units'].normalize())} un. em estoque"}
                  for r in stale[:15]]},
        {"type": "table", "title": {"stale": "Produtos sem venda no período", "below": "Produtos abaixo do mínimo"}.get(
            situation, "Produtos em estoque"), "span": "full", "columns": [
            {"key": "sku", "label": "SKU"}, {"key": "name", "label": "Produto"},
            {"key": "quantity", "label": "Saldo", "format": "quantity"}, {"key": "min", "label": "Mínimo", "format": "quantity"},
            {"key": "value", "label": "Valor", "format": "money"}, {"key": "status", "label": "Situação"}],
         "rows": [{"sku": r["variant__sku"], "name": name(r), "quantity": r["units"], "min": r["variant__min_stock"],
                   "value": r["value"], "status": "Abaixo do mínimo" if r in below else "Sem venda" if r in stale else "OK"}
                  for r in listed[:TABLE_MAX]]},
    ], [f_warehouses(account, store), f_categories(account), f_brands(account),
        _choice("situation", "Situação", [("stale", "Sem venda no período"), ("below", "Abaixo do mínimo")])])


MOVE_IN = {"initial", "purchase", "sale_return", "transfer_in"}


def goods_movements(account, store, params):
    start, end = _window(params)
    moves = _scoped(StockMovement.all_objects.filter(account=account, created_at__date__range=(start, end)),
                    store, "warehouse__store")
    if params.get("warehouse"):
        moves = moves.filter(warehouse_id=params["warehouse"])
    if params.get("kind"):
        moves = moves.filter(kind=params["kind"])
    moves = moves.filter(_item_q(params, "variant__product__"))
    labels = dict(StockMovement.Kind.choices)
    by_kind = list(moves.values("kind").annotate(quantity=Sum(Abs("quantity")), cost=Sum(Abs("total_cost")),
                                                  count=Count("id")).order_by("-quantity"))
    grain, (keys, xlabels) = _grain(params), _buckets(params)
    day_rows = list(moves.annotate(day=TruncDate("created_at")).values("day").annotate(
        entries=Coalesce(Sum("quantity", filter=Q(quantity__gt=0)), ZERO),
        exits=Coalesce(Sum(Abs("quantity"), filter=Q(quantity__lt=0)), ZERO)))
    entries, exits = sum((r["entries"] for r in day_rows), ZERO), sum((r["exits"] for r in day_rows), ZERO)
    entry_cost = moves.filter(quantity__gt=0).aggregate(t=Coalesce(Sum("total_cost"), ZERO))["t"]
    top_products = list(moves.values("variant__product__name", "variant__name").annotate(q=Sum(Abs("quantity")))
                        .order_by("-q")[:15])
    return _report("Entradas e saídas de estoque", "Tudo o que entrou e saiu dos depósitos, por tipo de movimento.", params, [
        kpi("Unidades que entraram", entries, "quantity"),
        kpi("Unidades que saíram", exits, "quantity"),
        kpi("Saldo do período", entries - exits, "quantity", hint="entrou − saiu"),
        kpi("Custo das entradas", entry_cost),
    ], [
        {"type": "bars", "title": f"Entradas e saídas {GRAIN_WORD[grain]}", "span": "full", "format": "quantity",
         "description": "Lado a lado: entrada maior que saída é estoque crescendo.", "grain": grain, "x": xlabels, "series": [
             {"name": "Entradas", "values": _series(day_rows, keys, grain, "entries")},
             {"name": "Saídas", "values": _series(day_rows, keys, grain, "exits")}]},
        {"type": "share", "title": "Movimento por tipo (unidades)", "span": "half", "format": "quantity",
         "rows": _top([{"label": labels.get(r["kind"], r["kind"]), "value": r["quantity"]} for r in by_kind])},
        {"type": "ranking", "title": "Produtos que mais movimentaram", "span": "half", "format": "quantity", "limit": 6,
         "rows": [{"label": " ".join(filter(None, [r["variant__product__name"], r["variant__name"]])), "value": r["q"]}
                  for r in top_products]},
        {"type": "table", "title": "Por tipo de movimento", "span": "full", "columns": [
            {"key": "label", "label": "Tipo"}, {"key": "direction", "label": "Sentido"},
            {"key": "count", "label": "Movimentos", "format": "number"},
            {"key": "quantity", "label": "Unidades", "format": "quantity"}, {"key": "cost", "label": "Custo", "format": "money"}],
         "rows": [{**r, "label": labels.get(r["kind"], r["kind"]), "direction": "Entrada" if r["kind"] in MOVE_IN else "Saída"}
                  for r in by_kind]},
    ], [_choice("kind", "Tipo de movimento", StockMovement.Kind.choices), f_warehouses(account, store), f_categories(account)])


def goods_receiving_errors(account, store, params):
    start, end = _window(params)
    errors = _scoped(ReceivingDivergence.all_objects.filter(account=account, created_at__date__range=(start, end),
                                                            deleted_at__isnull=True), store)
    if params.get("supplier"):
        errors = errors.filter(supplier_id=params["supplier"])
    if params.get("reason"):
        errors = errors.filter(reason=params["reason"])
    labels = dict(ReceivingDivergence._meta.get_field("reason").choices)
    by_supplier = list(errors.values("supplier__name").annotate(count=Count("id")).order_by("-count"))
    by_reason = list(errors.values("reason").annotate(count=Count("id")).order_by("-count"))
    missing = sum((max(e - a, ZERO) for e, a in errors.values_list("expected_quantity", "arrived_quantity")), ZERO)
    rows = list(errors.select_related("variant__product", "supplier", "inbound_nfe").order_by("-created_at")[:TABLE_MAX])
    return _report("Erros de entrada", "O que a nota dizia × o que chegou, por fornecedor e por motivo.", params, [
        kpi("Erros registrados", errors.count(), "number", good="down"),
        kpi("Unidades que faltaram", missing, "quantity", good="down"),
        kpi("Fornecedores com erro", len(by_supplier), "number", good="down"),
        kpi("Motivo mais comum", labels.get(by_reason[0]["reason"], "—") if by_reason else "—", "text"),
    ], [
        {"type": "ranking", "title": "Erros por fornecedor", "span": "half", "format": "number",
         "description": "Base para cobrar o fornecedor ou trocar de parceiro.",
         "rows": [{"label": r["supplier__name"] or "Sem fornecedor", "value": r["count"]} for r in by_supplier]},
        {"type": "share", "title": "Erros por motivo", "span": "half", "format": "number",
         "rows": [{"label": labels.get(r["reason"], r["reason"]), "value": r["count"]} for r in by_reason]},
        {"type": "table", "title": "Registros", "span": "full", "columns": [
            {"key": "date", "label": "Quando", "format": "date"}, {"key": "product", "label": "Produto"},
            {"key": "supplier", "label": "Fornecedor"}, {"key": "nfe", "label": "NF-e"}, {"key": "reason", "label": "Motivo"},
            {"key": "expected", "label": "Na nota", "format": "quantity"}, {"key": "arrived", "label": "Chegou", "format": "quantity"},
            {"key": "accepted", "label": "Entrou", "format": "quantity"}, {"key": "notes", "label": "Observação"}],
         "rows": [{"date": e.created_at.date(), "product": e.variant.display_name,
                   "supplier": e.supplier.name if e.supplier_id else "—",
                   "nfe": e.inbound_nfe.number if e.inbound_nfe_id else "—", "reason": e.get_reason_display(),
                   "expected": e.expected_quantity, "arrived": e.arrived_quantity, "accepted": e.accepted_quantity,
                   "notes": e.notes} for e in rows]},
    ], [f_suppliers(account), _choice("reason", "Motivo", ReceivingDivergence._meta.get_field("reason").choices)])


# ── Contábil ────────────────────────────────────────────────────────────────
def ledger_dre(account, store, params):
    d, before = dre.build(account, store, params), dre.build(account, store, _previous(params))
    steps = [
        {"label": "Receita bruta", "value": d["gross_revenue"], "kind": "add"},
        {"label": "Frete", "value": d["freight"], "kind": "add"},
        {"label": "Descontos", "value": -d["discounts"], "kind": "sub"},
        {"label": "Devoluções", "value": -d["returns"], "kind": "sub"},
        {"label": "Receita líquida", "value": d["net_revenue"], "kind": "total"},
        {"label": "CMV", "value": -d["cmv"], "kind": "sub"},
        {"label": "Lucro bruto", "value": d["gross_profit"], "kind": "total"},
        {"label": "Taxas de cartão", "value": -d["card_fees"], "kind": "sub"},
        {"label": "Comissões", "value": -d["commissions"], "kind": "sub"},
        {"label": "Diferenças de caixa", "value": d["cash_differences"], "kind": "add" if d["cash_differences"] >= 0 else "sub"},
        {"label": "Despesas", "value": -d["expenses_total"], "kind": "sub"},
        {"label": "Resultado", "value": d["operating_result"], "kind": "total"},
    ]
    prev = {s["label"]: s for s in [
        {"label": "Receita bruta", "value": before["gross_revenue"]}, {"label": "Receita líquida", "value": before["net_revenue"]},
        {"label": "CMV", "value": -before["cmv"]}, {"label": "Lucro bruto", "value": before["gross_profit"]},
        {"label": "Despesas", "value": -before["expenses_total"]}, {"label": "Resultado", "value": before["operating_result"]}]}
    return _report("DRE gerencial", "Da receita ao resultado (regime de competência), com o peso de cada linha.", params, [
        kpi("Receita líquida", d["net_revenue"], previous=before["net_revenue"]),
        kpi("Lucro bruto", d["gross_profit"], previous=before["gross_profit"], hint=f"margem {pt(d['gross_margin_percent'])}%"),
        kpi("Despesas", d["expenses_total"], previous=before["expenses_total"], good="down"),
        kpi("Resultado", d["operating_result"], previous=before["operating_result"],
            hint=f"margem {pt(d['operating_margin_percent'])}%"),
    ], [
        {"type": "waterfall", "title": "Da receita ao resultado", "span": "full", "format": "money",
         "description": "Cada coluna soma (azul) ou tira (vermelho) do acumulado; as cinzas são os subtotais. "
                        "Linhas zeradas no período ficam de fora.",
         "steps": [s for s in steps if s["kind"] == "total" or s["value"]]},
        {"type": "ranking", "title": "Despesas por categoria", "span": "half", "format": "money", "limit": 6,
         "description": "Onde cortar primeiro: as maiores linhas de despesa.",
         "rows": [{"label": e["category"], "value": e["amount"]} for e in d["expenses"]]},
        {"type": "share", "title": "Para onde vai a receita líquida", "span": "half", "format": "money",
         "rows": [r for r in [
             {"label": "CMV (custo das mercadorias)", "value": d["cmv"]}, {"label": "Despesas", "value": d["expenses_total"]},
             {"label": "Taxas e comissões", "value": d["card_fees"] + d["commissions"]},
             {"label": "Sobra (resultado)", "value": max(d["operating_result"], ZERO)}] if r["value"] > 0]},
        {"type": "table", "title": "Demonstrativo", "span": "full", "columns": [
            {"key": "label", "label": "Linha"}, {"key": "value", "label": "Valor", "format": "money"},
            {"key": "pct", "label": "% da receita líquida", "format": "percent"},
            {"key": "previous", "label": "Período anterior", "format": "money"}],
         "rows": [{"label": s["label"], "value": s["value"], "pct": _pct(s["value"], d["net_revenue"]),
                   "previous": prev.get(s["label"], {}).get("value"), "strong": s["kind"] == "total"} for s in steps]},
    ])


def ledger_cash_flow(account, store, params):
    flow = cash_flow.build(account, store, params)
    account_id = params.get("financial_account")
    rows = flow["by_day"]
    opening = flow["opening_balance"]
    if account_id:  # uma conta só: recalcula só com ela
        from starrp.models import FinancialTransaction
        acc = FinancialAccount.all_objects.filter(pk=account_id, account=account).first()
        start, end = _window(params)
        txs = FinancialTransaction.all_objects.filter(financial_account_id=account_id, deleted_at__isnull=True)
        net = lambda qs: (qs.filter(kind="in").aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]  # noqa: E731
                          - qs.filter(kind="out").aggregate(t=Coalesce(Sum("amount"), ZERO))["t"])
        opening = (acc.opening_balance if acc else ZERO) + net(txs.filter(date__lt=start))
        rows = list(txs.filter(date__range=(start, end)).values("date").annotate(
            inflow=Coalesce(Sum("amount", filter=Q(kind="in")), ZERO), outflow=Coalesce(Sum("amount", filter=Q(kind="out")), ZERO)))
    days_rows = [{"day": r["date"], "inflow": r["inflow"], "outflow": r["outflow"]} for r in rows]
    inflow, outflow = sum((r["inflow"] for r in days_rows), ZERO), sum((r["outflow"] for r in days_rows), ZERO)
    grain, (keys, labels) = _grain(params), _buckets(params)
    ins, outs = _series(days_rows, keys, grain, "inflow"), _series(days_rows, keys, grain, "outflow")
    running, balance = opening, []
    for i, o in zip(ins, outs, strict=True):
        running += i - o
        balance.append(running)
    cats = defaultdict(list)
    for row in flow["by_category"]:
        cats[row["kind"]].append({"label": row["category__name"], "value": row["total"]})
    forecast = flow.get("forecast", {})
    return _report("Fluxo de caixa", "Entradas e saídas das contas (regime de caixa) e o saldo ao longo do período.", params, [
        kpi("Saldo inicial", opening),
        kpi("Entradas", inflow),
        kpi("Saídas", outflow, good="down"),
        kpi("Saldo final", opening + inflow - outflow, hint=f"variação de {brl(inflow - outflow)} no período"),
        kpi("A receber previsto", forecast.get("receivable", ZERO), hint="parcelas que vencem no período"),
    ], [
        {"type": "bars", "title": f"Entradas e saídas {GRAIN_WORD[grain]}", "span": "full", "format": "money",
         "description": "Azul entrou, laranja saiu. Semanas com saída maior que entrada consomem o saldo.",
         "grain": grain, "x": labels, "series": [{"name": "Entradas", "values": ins}, {"name": "Saídas", "values": outs}]},
        {"type": "line", "title": "Saldo ao fim de cada " + {"day": "dia", "week": "semana", "month": "mês"}[grain],
         "span": "full", "format": "money", "zero": False, "grain": grain, "x": labels, "series": [{"name": "Saldo", "values": balance}]},
        {"type": "ranking", "title": "Entradas por categoria", "span": "half", "format": "money", "limit": 6, "rows": cats["in"]},
        {"type": "ranking", "title": "Saídas por categoria", "span": "half", "format": "money", "limit": 6, "rows": cats["out"]},
        {"type": "table", "title": "Movimento " + GRAIN_WORD[grain], "span": "full", "columns": [
            {"key": "label", "label": "Período"}, {"key": "inflow", "label": "Entradas", "format": "money"},
            {"key": "outflow", "label": "Saídas", "format": "money"}, {"key": "net", "label": "Líquido", "format": "money"},
            {"key": "balance", "label": "Saldo", "format": "money"}],
         "rows": [{"label": period_label(k, grain), "inflow": i, "outflow": o, "net": i - o, "balance": b}
                  for k, i, o, b in zip(keys, ins, outs, balance, strict=True) if i or o][::-1]},
    ], [_choice("financial_account", "Conta", [(a.pk, a.name) for a in cash_flow.visible_accounts(account, store)])])


def ledger_due(account, store, params):
    today = timezone.localdate()
    parts = Installment.all_objects.filter(account=account, status__in=[TitleStatus.OPEN, TitleStatus.PARTIAL],
                                           deleted_at__isnull=True, title__deleted_at__isnull=True)
    parts = parts.filter(title__store=store) if store is not None else parts
    if params.get("kind"):
        parts = parts.filter(title__kind=params["kind"])
    open_amount = ExpressionWrapper(F("amount") - F("paid_amount"), output_field=DecimalField(max_digits=18, decimal_places=2))
    buckets = [("Vencido", Q(due_date__lt=today)), ("Próx. 7 dias", Q(due_date__range=(today, today + timedelta(days=7)))),
               ("8 a 30 dias", Q(due_date__range=(today + timedelta(days=8), today + timedelta(days=30)))),
               ("31 a 60 dias", Q(due_date__range=(today + timedelta(days=31), today + timedelta(days=60)))),
               ("Depois de 60 dias", Q(due_date__gt=today + timedelta(days=60)))]

    def sums(kind):
        qs = parts.filter(title__kind=kind)
        return [qs.filter(q).aggregate(t=Coalesce(Sum(open_amount), ZERO))["t"] for _, q in buckets]

    receivable, payable = sums("receivable"), sums("payable")
    debtors = list(parts.filter(title__kind="receivable", due_date__lt=today).values("title__customer__name").annotate(
        v=Sum(open_amount)).order_by("-v")[:15])
    creditors = list(parts.filter(title__kind="payable").values("title__supplier__name").annotate(v=Sum(open_amount))
                     .order_by("-v")[:15])
    rows = list(parts.select_related("title__customer", "title__supplier").order_by("due_date")[:TABLE_MAX])
    series = [s for s in [{"name": "A receber", "values": receivable}, {"name": "A pagar", "values": payable}]
              if params.get("kind") in (None, "", {"A receber": "receivable", "A pagar": "payable"}[s["name"]])]
    return _report("Contas a pagar e receber", "O que está em aberto, por faixa de vencimento, e quem deve ou a quem se deve.",
                   params, [
                       kpi("Vencido a receber", receivable[0], good="down", hint="cobrar"),
                       kpi("Vencido a pagar", payable[0], good="down", hint="juros e multa correndo"),
                       kpi("A receber em 30 dias", receivable[1] + receivable[2]),
                       kpi("A pagar em 30 dias", payable[1] + payable[2], good="down"),
                       kpi("Saldo previsto (30 dias)", receivable[1] + receivable[2] - payable[1] - payable[2],
                           hint="a receber − a pagar nos próximos 30 dias"),
                   ], [
                       {"type": "bars", "title": "Em aberto por vencimento", "span": "full", "format": "money",
                        "description": "Barras lado a lado por faixa: ajuda a ver se o que entra cobre o que sai.",
                        "x": [b for b, _ in buckets], "series": series},
                       {"type": "ranking", "title": "Clientes com mais vencido", "span": "half", "format": "money", "limit": 8,
                        "description": "Quem cobrar primeiro.",
                        "rows": [{"label": r["title__customer__name"] or "Sem cliente", "value": r["v"]} for r in debtors]},
                       {"type": "ranking", "title": "Fornecedores com mais a pagar", "span": "half", "format": "money", "limit": 8,
                        "rows": [{"label": r["title__supplier__name"] or "Sem fornecedor", "value": r["v"]} for r in creditors]},
                       {"type": "table", "title": "Parcelas em aberto", "span": "full", "columns": [
                           {"key": "due", "label": "Vencimento", "format": "date"}, {"key": "kind", "label": "Tipo"},
                           {"key": "who", "label": "Cliente / fornecedor"}, {"key": "description", "label": "Descrição"},
                           {"key": "open", "label": "Em aberto", "format": "money"},
                           {"key": "late", "label": "Dias de atraso", "format": "number"}],
                        "rows": [{"due": p.due_date, "kind": p.title.get_kind_display(), "description": p.title.description,
                                  "who": (p.title.customer.name if p.title.customer_id else p.title.supplier.name
                                          if p.title.supplier_id else "—"),
                                  "open": p.amount - p.paid_amount, "late": max((today - p.due_date).days, 0)} for p in rows]},
                   ], [_choice("kind", "Tipo", [("receivable", "A receber"), ("payable", "A pagar")])])


def ledger_balances(account, store, params):
    data = cash_flow.balances(account, store, params)
    kinds = dict(FinancialAccount.Kind.choices)
    accounts = {str(a.pk): a for a in FinancialAccount.all_objects.filter(pk__in=[r["id"] for r in data["accounts"]])}
    rows = [{**r, "kind": kinds.get(accounts[str(r["id"])].kind, "Outra") if str(r["id"]) in accounts else "Outra"}
            for r in data["accounts"]]
    if params.get("account_kind"):
        rows = [r for r in rows if str(r["id"]) in accounts and accounts[str(r["id"])].kind == params["account_kind"]]
    by_kind = defaultdict(lambda: ZERO)
    for r in rows:
        by_kind[r["kind"]] += max(r["balance"], ZERO)
    total = sum((r["balance"] for r in rows), ZERO)
    return _report("Saldos por conta", "Quanto há em cada conta bancária, caixa e cofre neste momento.", params, [
        kpi("Saldo total", total),
        kpi("Contas", len(rows), "number"),
        kpi("Maior saldo", max(rows, key=lambda r: r["balance"])["name"] if rows else "—", "text"),
        kpi("Contas negativas", sum(1 for r in rows if r["balance"] < 0), "number", good="down"),
    ], [
        {"type": "ranking", "title": "Saldo por conta", "span": "half", "format": "money",
         "rows": sorted(({"label": r["name"], "value": r["balance"], "sub": r["kind"]} for r in rows), key=lambda r: -r["value"])},
        {"type": "share", "title": "Saldo por tipo de conta", "span": "half", "format": "money",
         "description": "Dinheiro em caixa físico e cofre é dinheiro exposto: o ideal é que seja pouco.",
         "rows": [{"label": k, "value": v} for k, v in by_kind.items() if v > 0]},
        {"type": "table", "title": "Contas", "span": "full", "columns": [
            {"key": "name", "label": "Conta"}, {"key": "kind", "label": "Tipo"},
            {"key": "balance", "label": "Saldo", "format": "money"}], "rows": rows},
    ], [_choice("account_kind", "Tipo de conta", FinancialAccount.Kind.choices)])


# ── Relacionamento ──────────────────────────────────────────────────────────
RECENCY = [("Até 30 dias", 0, 30), ("31 a 60 dias", 31, 60), ("61 a 90 dias", 61, 90), ("91 a 180 dias", 91, 180),
           ("Mais de 180 dias", 181, 10 ** 6)]


def relationship_customers(account, store, params):
    sales = _sales(account, store, params)
    start, end = _window(params)
    identified = sales.filter(customer__isnull=False)
    rows = list(identified.values("customer_id", "customer__name").annotate(
        count=Count("id"), revenue=Sum("total"), last=Max("completed_at"), first=Min("completed_at")).order_by("-revenue"))
    count, _ = _sales_totals(sales)
    returning = sum(1 for r in rows if r["count"] > 1)
    new = Customer.all_objects.filter(account=account, created_at__date__range=(start, end), deleted_at__isnull=True)
    if params.get("customer_group"):
        new = new.filter(groups=params["customer_group"])
    grain, (keys, labels) = _grain(params), _buckets(params)
    new_series = _series(new.annotate(day=TruncDate("created_at")).values("day").annotate(n=Count("id")), keys, grain, "n")
    # Recência: há quantos dias cada cliente comprou pela última vez (todo o histórico até o fim do período).
    ever = _scoped(Sale.all_objects.filter(account=account, status=Sale.Status.COMPLETED, customer__isnull=False,
                                           completed_at__date__lte=end), store)
    if params.get("customer_group"):
        ever = ever.filter(customer__groups=params["customer_group"])
    recency = [0] * len(RECENCY)
    for last in ever.values("customer_id").annotate(last=Max("completed_at")).values_list("last", flat=True):
        days = (end - last.date()).days
        recency[next(i for i, (_, lo, hi) in enumerate(RECENCY) if lo <= days <= hi)] += 1
    anonymous = count - identified.count()
    return _report("Clientes", "Quem compra, quanto, com que frequência e quem está sumindo.", params, [
        kpi("Clientes que compraram", len(rows), "number"),
        kpi("Recorrentes", returning, "number", hint=f"{pt(_pct(returning, len(rows)))}% compraram mais de uma vez"),
        kpi("Novos cadastros", new.count(), "number"),
        kpi("Vendas identificadas", _pct(identified.count(), count), "percent", hint="vendas com cliente informado"),
        kpi("Sumidos (+90 dias)", sum(recency[3:]), "number", good="down", hint="bons para uma campanha de retorno"),
    ], [
        {"type": "ranking", "title": "Os que mais compram", "span": "half", "format": "money", "limit": 8,
         "rows": [{"label": r["customer__name"], "value": r["revenue"], "sub": f"{r['count']} compra(s) · última {r['last']:%d/%m}"}
                  for r in rows[:30]]},
        {"type": "bars", "title": "Há quanto tempo compraram pela última vez", "span": "half", "format": "number",
         "description": "Recência de toda a base: as barras da direita são clientes a reconquistar.",
         "x": [r[0] for r in RECENCY], "series": [{"name": "Clientes", "values": recency}]},
        {"type": "share", "title": "Vendas por tipo de cliente", "span": "half", "format": "number",
         "description": "Venda sem cliente informado não gera relacionamento (nem campanha).", "rows": [
             r for r in [{"label": "Recorrente", "value": sum(r["count"] for r in rows if r["count"] > 1)},
                         {"label": "Comprou uma vez", "value": sum(1 for r in rows if r["count"] == 1)},
                         {"label": "Não identificado", "value": anonymous}] if r["value"]]},
        {"type": "bars", "title": f"Novos clientes {GRAIN_WORD[grain]}", "span": "half", "format": "number",
         "grain": grain, "x": labels, "series": [{"name": "Novos clientes", "values": new_series}]},
        {"type": "table", "title": "Clientes", "span": "full", "columns": [
            {"key": "name", "label": "Cliente"}, {"key": "count", "label": "Compras", "format": "number"},
            {"key": "revenue", "label": "Total", "format": "money"}, {"key": "ticket", "label": "Ticket médio", "format": "money"},
            {"key": "first", "label": "Primeira no período", "format": "date"},
            {"key": "last", "label": "Última compra", "format": "date"}],
         "rows": [{"name": r["customer__name"], "count": r["count"], "revenue": r["revenue"], "ticket": _ticket(r["revenue"], r["count"]),
                   "first": r["first"].date(), "last": r["last"].date()} for r in rows[:TABLE_MAX]]},
    ], _sales_filters(account, store, "customer_group", "channel", "seller"))


# ── Relacionamento: curva ABC de clientes e avaliações ──────────────────────
def relationship_customers_abc(account, store, params):
    from starrp.services import report_cross as rx

    measure = params.get("measure") or "revenue"
    sales = _sales(account, store, params).filter(customer__isnull=False)
    rows = list(sales.values("customer_id", "customer__name").annotate(
        count=Count("id"), revenue=Sum("total"), last=Max("completed_at")))
    margins = {r["sale__customer_id"]: (r["revenue"] or 0) - (r["cost"] or 0) for r in _items(sales, params).values(
        "sale__customer_id").annotate(revenue=Sum("total"), cost=Sum(COST))}
    for r in rows:
        r["name"], r["margin"], r["ticket"] = r["customer__name"], margins.get(r["customer_id"], ZERO), _ticket(r["revenue"], r["count"])
    key = {"revenue": "revenue", "margin": "margin", "frequency": "count"}[measure]
    rows.sort(key=lambda r: -Decimal(r[key] or 0))
    total = sum((Decimal(r[key] or 0) for r in rows), ZERO)
    running, classes = ZERO, {"A": [], "B": [], "C": []}
    for index, r in enumerate(rows, start=1):
        running += Decimal(r[key] or 0)
        r["position"], r["share"], r["cumulative"] = index, _pct(r[key], total), _pct(running, total)
        r["abc"] = "A" if r["cumulative"] <= 80 or index == 1 else "B" if r["cumulative"] <= 95 else "C"
        r["last"] = r["last"].date()
        classes[r["abc"]].append(r)
    fmt = "number" if measure == "frequency" else "money"
    word = {"revenue": "faturamento", "margin": "margem", "frequency": "número de compras"}[measure]
    share = [{"label": f"Classe {k}", "value": sum((Decimal(r[key] or 0) for r in v), ZERO)} for k, v in classes.items()]
    revenue_a = sum((r["revenue"] for r in classes["A"]), ZERO)
    return _report("Curva ABC de clientes", f"Classifica os clientes pelo {word}: A = até 80% do total, B = os próximos 15%, "
                   "C = o resto.", params, [
                       kpi("Clientes que compraram", len(rows), "number"),
                       kpi("Clientes A", len(classes["A"]), "number",
                           hint=f"{pt(_pct(len(classes['A']), len(rows)))}% dos clientes fazem {pt(_pct(share[0]['value'], total))}%"),
                       kpi("Ticket médio dos A", _ticket(revenue_a, sum(r["count"] for r in classes["A"]))),
                       kpi("Clientes C", len(classes["C"]), "number", hint="potencial para crescer"),
                   ], [
                       {"type": "share", "title": f"{word.capitalize()} por classe", "span": "half", "format": fmt,
                        "description": "Poucos clientes A costumam carregar a maior parte do resultado.", "rows": share},
                       {"type": "share", "title": "Quantidade de clientes por classe", "span": "half", "format": "number",
                        "rows": [{"label": f"Classe {k}", "value": len(v)} for k, v in classes.items()]},
                       {"type": "ranking", "title": f"Os clientes que mais pesam no {word}", "span": "full", "format": fmt, "limit": 10,
                        "rows": [{"label": r["name"], "value": r[key], "sub": f"{r['count']} compra(s) · {pt(r['cumulative'])}% acumulado",
                                  "group": f"Classe {r['abc']}"} for r in rows[:20]]},
                       rx.compare("Cada classe: satisfação, entrega e frequência", rx.CUSTOMER_METRICS,
                                  rx.customer_class_rows(account, store, params),
                                  "Cruzamento com as avaliações e as entregas (mais em Cruzamentos › Clientes × satisfação)."),
                       {"type": "table", "title": "Curva completa", "span": "full", "tabs": {"key": "abc", "label": "Classe", "sum": "revenue"},
                        "columns": [
                            {"key": "position", "label": "#", "format": "number"}, {"key": "name", "label": "Cliente"},
                            {"key": "count", "label": "Compras", "format": "number"},
                            {"key": "revenue", "label": "Faturamento", "format": "money"},
                            {"key": "margin", "label": "Margem", "format": "money"},
                            {"key": "ticket", "label": "Ticket médio", "format": "money"},
                            {"key": "last", "label": "Última compra", "format": "date"},
                            {"key": "share", "label": "%", "format": "percent"},
                            {"key": "cumulative", "label": "% acum.", "format": "percent"}, {"key": "abc", "label": "Classe"}],
                        "rows": rows[:TABLE_MAX]},
                   ], [_choice("measure", "Classificar por", [("revenue", "Faturamento"), ("margin", "Margem bruta"),
                                                               ("frequency", "Número de compras")]),
                       *_sales_filters(account, store, "customer_group", "channel", "seller")])


def relationship_reviews(account, store, params):
    from starrp.models import Review
    from starrp.services import report_cross as rx

    start, end = _window(params)
    base = _scoped(Review.all_objects.filter(account=account, deleted_at__isnull=True), store)
    if params.get("kind"):
        base = base.filter(kind=params["kind"])
    if params.get("category"):
        base = base.filter(product__category_id=params["category"])
    status = params.get("status")
    counted = base.filter(status=status) if status else base.exclude(status=Review.Status.REJECTED)
    period = counted.filter(created_at__date__range=(start, end))
    p_start, p_end = _window(_previous(params))
    before = counted.filter(created_at__date__range=(p_start, p_end))

    def avg(qs):
        n = qs.count()
        return (Decimal(sum(qs.values_list("rating", flat=True))) / n).quantize(Decimal("0.1")) if n else ZERO

    products, deliveries = period.filter(kind="product"), period.filter(kind="delivery")
    total = period.count()
    promoters = period.filter(rating__gte=4).count()
    dist = {kind: [period.filter(kind=kind, rating=n).count() for n in range(1, 6)] for kind in ("product", "delivery")}
    grain, (keys, labels) = _grain(params), _buckets(params)
    sums, counts = defaultdict(lambda: ZERO), defaultdict(int)
    for created, rating in period.values_list("created_at", "rating"):
        k = _bucket(timezone.localtime(created).date(), grain)
        sums[k] += rating
        counts[k] += 1
    trend = [(sums[k] / counts[k]).quantize(Decimal("0.1")) if counts[k] else None for k in keys]
    by_product = list(products.values("product__name").annotate(n=Count("id"), total=Sum("rating")))
    for r in by_product:
        r["avg"] = (Decimal(r["total"]) / r["n"]).quantize(Decimal("0.1"))
    best = sorted(by_product, key=lambda r: (-r["avg"], -r["n"]))[:10]
    worst = sorted(by_product, key=lambda r: (r["avg"], -r["n"]))[:10]
    rows = list(period.select_related("product", "sale", "customer").order_by("-created_at")[:TABLE_MAX])
    labels_status = dict(Review.Status.choices)
    return _report("Avaliações", "O que os clientes acharam dos produtos e da entrega (nota de 1 a 5 estrelas).", params, [
        kpi("Nota média dos produtos", avg(products), "decimal", previous=avg(before.filter(kind="product")) or None,
            hint=f"{products.count()} avaliação(ões)"),
        kpi("Nota média da entrega", avg(deliveries), "decimal", previous=avg(before.filter(kind="delivery")) or None,
            hint=f"{deliveries.count()} avaliação(ões)"),
        kpi("Avaliações recebidas", total, "number", previous=before.count()),
        kpi("Satisfeitos (4 e 5 estrelas)", _pct(promoters, total), "percent"),
        kpi("Aguardando moderação", base.filter(status=Review.Status.PENDING).count(), "number", good="down",
            hint="aprove ou rejeite em Vendas › Avaliações"),
    ], [
        {"type": "bars", "title": "Quantas estrelas", "span": "half", "format": "number",
         "description": "Distribuição das notas: muita nota 1 e 2 pede atenção imediata.",
         "x": ["1 estrela", "2 estrelas", "3 estrelas", "4 estrelas", "5 estrelas"],
         "series": [{"name": "Produtos", "values": dist["product"]}, {"name": "Entrega", "values": dist["delivery"]}]},
        # Só os períodos com avaliação (semana sem nota não é nota zero); escala de 0 a 5.
        {"type": "line", "title": f"Nota média {GRAIN_WORD[grain]}", "span": "half", "format": "decimal",
         "description": "Só os períodos que tiveram avaliação.", "grain": grain,
         "x": [lbl for lbl, t in zip(labels, trend, strict=True) if t is not None],
         "series": [{"name": "Nota média", "values": [t for t in trend if t is not None]}]},
        {"type": "ranking", "title": "Produtos mais bem avaliados", "span": "half", "format": "decimal", "limit": 6,
         "rows": [{"label": r["product__name"], "value": r["avg"], "sub": f"{r['n']} avaliação(ões)"} for r in best]},
        {"type": "ranking", "title": "Produtos com pior avaliação", "span": "half", "format": "decimal", "limit": 6,
         "description": "Defeito, descrição errada ou expectativa: leia os comentários.",
         "rows": [{"label": r["product__name"], "value": r["avg"], "sub": f"{r['n']} avaliação(ões)"} for r in worst]},
        rx.compare("Nota por classe de cliente", [m for m in rx.CUSTOMER_METRICS if m["key"] in
                                                   ("customers", "rating", "delivery_rating", "satisfied")],
                   rx.customer_class_rows(account, store, params), "Quem é cliente A avalia melhor ou pior que o C?", span="half"),
        rx.compare("Nota: entrega no prazo × com atraso", [m for m in rx.DELIVERY_METRICS if m["key"] in
                                                         ("deliveries", "delivery_rating", "rating")],
                   rx.delivery_rows(account, store, params), "O atraso derruba a nota?", span="half"),
        {"type": "table", "title": "Avaliações do período", "span": "full", "columns": [
            {"key": "date", "label": "Quando", "format": "date"}, {"key": "kind", "label": "Tipo"},
            {"key": "what", "label": "Produto / venda"}, {"key": "name", "label": "Cliente"},
            {"key": "rating", "label": "Nota", "format": "number"}, {"key": "comment", "label": "Comentário"},
            {"key": "verified", "label": "Compra verificada"}, {"key": "status", "label": "Situação"}],
         "rows": [{"date": timezone.localtime(r.created_at).date(), "kind": r.get_kind_display(),
                   "what": r.product.name if r.product_id else f"Venda {r.sale.number}" if r.sale_id else "—",
                   "name": r.public_name, "rating": r.rating, "comment": r.comment,
                   "verified": "Sim" if r.verified_purchase else "Não", "status": labels_status.get(r.status, r.status)}
                  for r in rows]},
    ], [_choice("kind", "Tipo", Review.Kind.choices), _choice("status", "Situação", Review.Status.choices),
        f_categories(account)])


# ── Logística: entregas ─────────────────────────────────────────────────────
def _add_business_days(day, days):
    while days > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days -= 1
    return day


def delivery_state(sale, today=None):
    """A entrega da venda contra o prazo prometido (venda + dias úteis da tabela de frete):
    `on_time`, `late` (entregue depois do prazo), `late_open` (prazo vencido e não entregue)
    ou `open` (a caminho, dentro do prazo, ou sem prazo informado)."""
    from starrp.services.sales import DELIVERY_KEY

    today = today or timezone.localdate()
    info = (sale.metafields or {}).get(DELIVERY_KEY) or {}
    sold = timezone.localtime(sale.completed_at).date()
    lead = info.get("lead_days")
    promised = _add_business_days(sold, int(lead)) if lead not in (None, "") else None
    delivered = timezone.localtime(sale.delivered_at).date() if sale.delivered_at else None
    delay = (delivered - promised).days if delivered and promised else (today - promised).days if promised else None
    if delivered:
        state = "late" if promised and delivered > promised else "on_time"
    elif promised and today > promised and sale.fulfillment_status not in ("cancelled", "returned"):
        state = "late_open"
    else:
        state = "open"
    return {"sold": sold, "promised": promised, "delivered": delivered, "delay": delay, "state": state}


def logistics_deliveries(account, store, params):
    from starrp.models import Review
    from starrp.services import report_cross as rx
    from starrp.services.sales import DELIVERY_KEY

    sales = _sales(account, store, params).filter(shipping_address__isnull=False).select_related(
        "shipping_address", "customer")
    if params.get("fulfillment"):
        sales = sales.filter(fulfillment_status=params["fulfillment"])
    if params.get("city"):
        sales = sales.filter(shipping_address__city=params["city"])
    today = timezone.localdate()
    ratings = dict(Review.all_objects.filter(sale__in=sales, kind="delivery", deleted_at__isnull=True).exclude(
        status=Review.Status.REJECTED).values_list("sale_id", "rating"))
    status_label = dict(Sale._meta.get_field("fulfillment_status").choices)
    rows, on_time, late, open_late, days_taken = [], 0, 0, 0, []
    grain, (keys, labels) = _grain(params), _buckets(params)
    per = {k: {"on_time": 0, "late": 0, "open": 0} for k in keys}
    for sale in sales:
        info = (sale.metafields or {}).get(DELIVERY_KEY) or {}
        d = delivery_state(sale, today)
        sold, promised, delivered, delay = d["sold"], d["promised"], d["delivered"], d["delay"]
        if delivered:
            days_taken.append((delivered - sold).days)
        on_time += d["state"] == "on_time"
        late += d["state"] == "late"
        open_late += d["state"] == "late_open"
        per[_bucket(sold, grain)]["open" if d["state"] in ("open", "late_open") else d["state"]] += 1
        address = sale.shipping_address
        rows.append({"sale": sale.number, "date": sold, "customer": sale.customer.name if sale.customer_id else sale.customer_name,
                     "place": " · ".join(filter(None, [address.district, address.city])), "city": address.city,
                     "table": info.get("table_name") or "—", "freight": sale.freight, "promised": promised,
                     "delivered": delivered, "delay": max(delay, 0) if delay is not None else None,
                     "status": status_label.get(sale.fulfillment_status, sale.fulfillment_status),
                     "rating": ratings.get(sale.pk)})
    count = len(rows)
    delivered_count = on_time + late
    freight = sum((r["freight"] or ZERO for r in rows), ZERO)
    by_place, by_table, by_status = defaultdict(int), defaultdict(lambda: ZERO), defaultdict(int)
    for r in rows:
        by_place[r["place"] or "Sem bairro"] += 1
        by_table[r["table"]] += r["freight"] or ZERO
        by_status[r["status"]] += 1
    rated = [r["rating"] for r in rows if r["rating"]]
    cities = sorted({r["city"] for r in rows if r["city"]})
    return _report("Entregas", "Prazo prometido × entregue, frete cobrado, para onde se entrega e a nota da entrega.", params, [
        kpi("Vendas com entrega", count, "number"),
        kpi("Entregues no prazo", _pct(on_time, delivered_count), "percent", hint=f"{on_time} de {delivered_count} entregues"),
        kpi("Atrasadas ainda abertas", open_late, "number", good="down", hint="passaram do prazo e não foram entregues"),
        kpi("Tempo médio até entregar", (Decimal(sum(days_taken)) / len(days_taken)).quantize(Decimal("0.1")) if days_taken else ZERO,
            "decimal", good="down", hint="dias corridos entre a venda e a entrega"),
        kpi("Frete cobrado", freight, hint=f"média de {brl(freight / count) if count else brl(0)} por entrega"),
        kpi("Nota da entrega", (Decimal(sum(rated)) / len(rated)).quantize(Decimal("0.1")) if rated else ZERO, "decimal",
            hint=f"{len(rated)} avaliação(ões)"),
    ], [
        {"type": "bars", "title": f"Entregas {GRAIN_WORD[grain]} (pela data da venda)", "span": "full", "format": "number",
         "stacked": True, "description": "No prazo, com atraso e ainda abertas (inclui as que nem saíram).", "grain": grain,
         "x": labels, "series": [{"name": "No prazo", "values": [per[k]["on_time"] for k in keys]},
                                 {"name": "Com atraso", "values": [per[k]["late"] for k in keys]},
                                 {"name": "Abertas", "values": [per[k]["open"] for k in keys]}]},
        {"type": "share", "title": "Situação das entregas", "span": "half", "format": "number",
         "rows": [{"label": k, "value": v} for k, v in sorted(by_status.items(), key=lambda kv: -kv[1])]},
        {"type": "ranking", "title": "Para onde mais se entrega", "span": "half", "format": "number", "limit": 8,
         "description": "Bairro · cidade: ajuda a montar rotas e revisar as faixas de frete.",
         "rows": [{"label": k, "value": v} for k, v in sorted(by_place.items(), key=lambda kv: -kv[1])]},
        {"type": "ranking", "title": "Frete cobrado por tabela", "span": "half", "format": "money", "limit": 6,
         "rows": [{"label": k, "value": v} for k, v in sorted(by_table.items(), key=lambda kv: -kv[1])]},
        {"type": "bars", "title": "Nota da entrega", "span": "half", "format": "number",
         "x": ["1 estrela", "2 estrelas", "3 estrelas", "4 estrelas", "5 estrelas"],
         "series": [{"name": "Avaliações", "values": [rated.count(n) for n in range(1, 6)]}]},
        rx.compare("No prazo × com atraso: nota e recompra", rx.DELIVERY_METRICS, rx.delivery_rows(account, store, params),
                   "\"Voltaram a comprar\" = o cliente fez outra compra depois desta."),
        {"type": "table", "title": "Entregas", "span": "full", "columns": [
            {"key": "sale", "label": "Venda", "format": "number"}, {"key": "date", "label": "Venda em", "format": "date"},
            {"key": "customer", "label": "Cliente"}, {"key": "place", "label": "Bairro · cidade"},
            {"key": "table", "label": "Tabela"}, {"key": "freight", "label": "Frete", "format": "money"},
            {"key": "promised", "label": "Prometido para", "format": "date"},
            {"key": "delivered", "label": "Entregue em", "format": "date"},
            {"key": "delay", "label": "Dias de atraso", "format": "number"}, {"key": "status", "label": "Situação"},
            {"key": "rating", "label": "Nota", "format": "number"}],
         "rows": sorted(rows, key=lambda r: r["date"], reverse=True)[:TABLE_MAX]},
    ], [_choice("fulfillment", "Situação", Sale._meta.get_field("fulfillment_status").choices),
        _choice("city", "Cidade", [(c, c) for c in cities]), *_sales_filters(account, store, "channel", "seller")])


# ── Movimento: cancelamentos e devoluções ───────────────────────────────────
def movement_cancellations(account, store, params):
    from starrp.models import SaleReturn, SaleReturnItem

    start, end = _window(params)
    cancelled = _scoped(Sale.all_objects.filter(account=account, status=Sale.Status.CANCELLED,
                                                cancelled_at__date__range=(start, end)), store)
    returns = _scoped(SaleReturn.all_objects.filter(account=account, status=SaleReturn.Status.COMPLETED,
                                                    completed_at__date__range=(start, end)), store)
    if params.get("seller"):
        cancelled = cancelled.filter(seller_id=params["seller"])
        returns = returns.filter(sale__seller_id=params["seller"])
    if params.get("channel"):
        cancelled = cancelled.filter(channel=params["channel"])
        returns = returns.filter(sale__channel=params["channel"])
    _, revenue = _sales_totals(_sales(account, store, params))
    cancelled_value = cancelled.aggregate(t=Coalesce(Sum("total"), ZERO))["t"]
    returned_value = returns.aggregate(t=Coalesce(Sum("total"), ZERO))["t"]
    reasons = defaultdict(lambda: [0, ZERO])
    for reason, total in cancelled.values_list("cancel_reason", "total"):
        key = (reason or "").strip().split("\n")[0][:70] or "Sem motivo informado"
        reasons[key][0] += 1
        reasons[key][1] += total
    by_product = list(SaleReturnItem.all_objects.filter(sale_return__in=returns).values("sale_item__description").annotate(
        q=Sum("quantity"), v=Sum("total")).order_by("-v"))
    refund_label = dict(SaleReturn.Refund.choices)
    by_refund = list(returns.values("refund_method").annotate(v=Sum("total")).order_by("-v"))
    grain, (keys, labels) = _grain(params), _buckets(params)
    c_series = _series(cancelled.annotate(day=TruncDate("cancelled_at")).values("day").annotate(v=Sum("total")), keys, grain, "v")
    r_series = _series(returns.annotate(day=TruncDate("completed_at")).values("day").annotate(v=Sum("total")), keys, grain, "v")
    by_seller = list(cancelled.filter(seller__isnull=False).values("seller__first_name", "seller__username").annotate(
        n=Count("id")).order_by("-n"))
    return _report("Cancelamentos e devoluções", "O que deixou de virar receita: vendas canceladas e mercadoria devolvida.",
                   params, [
                       kpi("Vendas canceladas", cancelled.count(), "number", good="down"),
                       kpi("Valor cancelado", cancelled_value, good="down"),
                       kpi("Devoluções", returns.count(), "number", good="down"),
                       kpi("Valor devolvido", returned_value, good="down"),
                       kpi("Taxa de devolução", _pct(returned_value, revenue), "percent", good="down", hint="sobre o faturamento do período"),
                   ], [
                       {"type": "bars", "title": f"Cancelado e devolvido {GRAIN_WORD[grain]}", "span": "full", "format": "money",
                        "grain": grain, "x": labels,
                        "series": [{"name": "Cancelado", "values": c_series}, {"name": "Devolvido", "values": r_series}]},
                       {"type": "ranking", "title": "Motivos de cancelamento", "span": "half", "format": "number", "limit": 8,
                        "rows": [{"label": k, "value": v[0], "sub": brl(v[1])} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1][0])]},
                       {"type": "ranking", "title": "Produtos mais devolvidos", "span": "half", "format": "money", "limit": 8,
                        "description": "Devolução repetida do mesmo produto: defeito, tamanho ou descrição errada.",
                        "rows": [{"label": r["sale_item__description"], "value": r["v"], "sub": f"{pt(r['q'].normalize())} un."}
                                 for r in by_product]},
                       {"type": "share", "title": "Como a devolução foi paga", "span": "half", "format": "money",
                        "rows": [{"label": refund_label.get(r["refund_method"], r["refund_method"]), "value": r["v"]} for r in by_refund]},
                       {"type": "ranking", "title": "Cancelamentos por vendedor", "span": "half", "format": "number", "limit": 6,
                        "rows": [{"label": r["seller__first_name"] or r["seller__username"], "value": r["n"]} for r in by_seller]},
                       {"type": "table", "title": "Vendas canceladas", "span": "full", "columns": [
                           {"key": "number", "label": "Venda", "format": "number"}, {"key": "date", "label": "Cancelada em", "format": "date"},
                           {"key": "total", "label": "Valor", "format": "money"}, {"key": "reason", "label": "Motivo"}],
                        "rows": [{"number": n, "date": timezone.localtime(d).date(), "total": t, "reason": r or "—"}
                                 for n, d, t, r in cancelled.order_by("-cancelled_at").values_list(
                                     "number", "cancelled_at", "total", "cancel_reason")[:TABLE_MAX]]},
                   ], _sales_filters(account, store, "seller", "channel"))


# Cruzamentos (um assunto explicado por outro): usam as funções daqui, por isso vêm no fim.
from starrp.services import report_cross, report_promotions  # noqa: E402

# slug → (função, permissão, módulo). A tela usa o mesmo slug (frontend/src/reports/catalog.ts).
BOOK = {
    "vendas": (movement_sales, "reports.view", "base"),
    "horarios": (movement_hours, "reports.view", "base"),
    "recebimentos": (movement_payments, "reports.view", "base"),
    "vendedores": (movement_sellers, "reports.view", "base"),
    "filiais": (movement_branches, "reports.view", "base"),
    "curva-abc": (goods_abc, "reports.view", "base"),
    "categorias": (goods_categories, "reports.view", "base"),
    "posicao-de-estoque": (goods_stock, "stock.view", "stock"),
    "entradas-e-saidas": (goods_movements, "stock.view", "stock"),
    "erros-de-entrada": (goods_receiving_errors, "stock.view", "stock"),
    "dre": (ledger_dre, "finance.view", "finance"),
    "fluxo-de-caixa": (ledger_cash_flow, "finance.view", "finance"),
    "vencimentos": (ledger_due, "finance.view", "finance"),
    "saldos": (ledger_balances, "finance.view", "finance"),
    "clientes": (relationship_customers, "reports.view", "base"),
    "curva-abc-clientes": (relationship_customers_abc, "reports.view", "base"),
    "avaliacoes": (relationship_reviews, "reports.view", "base"),
    "entregas": (logistics_deliveries, "reports.view", "base"),
    "cancelamentos": (movement_cancellations, "reports.view", "base"),
    "cruzamento-clientes": (report_cross.cross_customers, "reports.view", "base"),
    "cruzamento-entregas": (report_cross.cross_deliveries, "reports.view", "base"),
    "cruzamento-vendedores": (report_cross.cross_sellers, "reports.view", "base"),
    "cruzamento-produtos": (report_cross.cross_products, "reports.view", "base"),
    "cruzamento-descontos": (report_cross.cross_discounts, "reports.view", "base"),
    "descontos": (report_promotions.overview, "reports.view", "base"),
    "promocoes-de-produto": (report_promotions.products, "reports.view", "base"),
    "cupons": (report_promotions.coupons, "reports.view", "base"),
}
