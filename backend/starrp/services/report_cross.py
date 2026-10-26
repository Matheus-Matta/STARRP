"""Cruzamentos: um assunto explicado por outro ("o que leva cada coisa a cada lugar").

Cada relatório agrupa as vendas por uma dimensão (classe ABC do cliente, entrega no prazo ou
atrasada, vendedor, classe do produto, faixa de desconto) e mede, em cada grupo, o resultado
de outra (nota das avaliações, recompra, margem, devolução, cancelamento). Dois blocos novos:

    {"type": "compare", "metrics": [{"key", "label", "format", "good"}], "rows": [{"label", <key>: valor}]}
    {"type": "insights", "items": [{"text", "tone": "good" | "bad" | "info"}]}

As conclusões ("Clientes A dão nota 4,6; clientes C, 3,8") são escritas a partir dos números,
só quando há base (grupo com dado nos dois lados). As mesmas funções alimentam blocos de
cruzamento dentro dos relatórios comuns (Curva ABC, Avaliações, Entregas, Vendedores).
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from starrp.models import Review, Sale, SaleItem
from starrp.services import report_book as rb

ZERO = Decimal("0")
CLASSES = ("A", "B", "C")


# ── base: classes, notas, recompra ──────────────────────────────────────────
def _abc(values):
    """{chave: valor} → {chave: "A" | "B" | "C"} (A até 80% do total, B até 95%, C o resto)."""
    ordered = sorted(values.items(), key=lambda kv: -Decimal(kv[1] or 0))
    total = sum((Decimal(v or 0) for _, v in ordered), ZERO)
    running, out = ZERO, {}
    for index, (key, value) in enumerate(ordered):
        running += Decimal(value or 0)
        share = running / total * 100 if total else Decimal(100)
        out[key] = "A" if share <= 80 or index == 0 else "B" if share <= 95 else "C"
    return out


def customer_classes(sales):
    return _abc(dict(sales.filter(customer__isnull=False).values_list("customer_id").annotate(t=Sum("total"))))


def product_classes(items):
    return _abc(dict(items.values_list("variant__product_id").annotate(t=Sum("total"))))


def reviews_of(account, store):
    return rb._scoped(Review.all_objects.filter(account=account, deleted_at__isnull=True).exclude(
        status=Review.Status.REJECTED), store)


def avg(values):
    values = [Decimal(v) for v in values if v is not None]
    return (sum(values, ZERO) / len(values)).quantize(Decimal("0.1")) if values else None


def came_back(account, store, pairs):
    """% dos (cliente, momento) em que o cliente comprou de novo DEPOIS daquele momento."""
    pairs = [(c, m) for c, m in pairs if c and m]
    if not pairs:
        return None
    later = defaultdict(list)
    for customer, moment in rb._scoped(Sale.all_objects.filter(
            account=account, status=Sale.Status.COMPLETED, customer_id__in={c for c, _ in pairs}), store).values_list(
            "customer_id", "completed_at"):
        later[customer].append(moment)
    back = sum(1 for c, m in pairs if any(x > m for x in later[c]))
    return rb._pct(back, len(pairs))


def compare(title, metrics, rows, description="", span="full"):
    return {"type": "compare", "title": title, "description": description, "span": span, "metrics": metrics, "rows": rows}


def insights(items, title="O que os números mostram"):
    return {"type": "insights", "title": title, "span": "full", "items": [i for i in items if i]}


def _num(value, fmt="decimal"):
    if value is None:
        return "—"
    if fmt == "percent":
        return f"{rb.pt(Decimal(value).quantize(Decimal('0.1')))}%"
    if fmt == "money":
        return rb.brl(value)
    return rb.pt(Decimal(value).quantize(Decimal("0.1")))


def _gap(rows, key, a, b, what, fmt="decimal", higher_is_good=True, threshold=Decimal("0.3")):
    """Frase comparando dois grupos numa métrica ("A: 4,6 · C: 3,8"), só se os dois têm dado."""
    ra = next((r for r in rows if r["label"] == a), None)
    rb_ = next((r for r in rows if r["label"] == b), None)
    if not ra or not rb_ or ra.get(key) is None or rb_.get(key) is None:
        return None
    va, vb = Decimal(ra[key]), Decimal(rb_[key])
    if abs(va - vb) < threshold:
        return {"text": f"{what}: praticamente igual em {a} ({_num(va, fmt)}) e {b} ({_num(vb, fmt)}).", "tone": "info"}
    better = (va > vb) == higher_is_good
    word = "maior" if va > vb else "menor"
    return {"text": f"{what} {word} em {a}: {_num(va, fmt)} contra {_num(vb, fmt)} em {b}.",
            "tone": "good" if better else "bad"}


def small_base(count, what="avaliações", minimum=10):
    """Aviso de base pequena: conclusão com 3 respostas não vale o mesmo que com 300."""
    if count < minimum:
        return {"text": f"Base ainda pequena ({count} {what}): as conclusões ficam mais confiáveis com mais respostas.",
                "tone": "info"}
    return None


# ── blocos reaproveitados nos relatórios comuns ─────────────────────────────
def customer_class_rows(account, store, params):
    """Por classe ABC de cliente: tamanho, faturamento, ticket, notas, entrega no prazo e recompra."""
    sales = rb._sales(account, store, params).filter(customer__isnull=False)
    classes = customer_classes(sales)
    reviews = reviews_of(account, store).filter(customer_id__in=classes.keys())
    by_class = {k: {"customers": 0, "revenue": ZERO, "sales": 0, "product": [], "delivery": [], "on_time": 0, "delivered": 0}
                for k in CLASSES}
    for cls in classes.values():
        by_class[cls]["customers"] += 1
    for customer, total, count in sales.values_list("customer_id").annotate(t=Sum("total"), n=Count("id")):
        cls = classes.get(customer)
        if cls:
            by_class[cls]["revenue"] += total
            by_class[cls]["sales"] += count
    for customer, kind, rating in reviews.values_list("customer_id", "kind", "rating"):
        by_class[classes[customer]][kind].append(rating)
    today = timezone.localdate()
    for sale in sales.filter(shipping_address__isnull=False):
        state = rb.delivery_state(sale, today)["state"]
        cls = by_class[classes[sale.customer_id]]
        if state in ("on_time", "late"):
            cls["delivered"] += 1
            cls["on_time"] += state == "on_time"
    rows = []
    for cls in CLASSES:
        d = by_class[cls]
        if not d["customers"]:
            continue
        rows.append({"label": f"Classe {cls}", "group": f"Classe {cls}", "customers": d["customers"], "revenue": d["revenue"],
                     "ticket": rb._ticket(d["revenue"], d["sales"]),
                     "frequency": (Decimal(d["sales"]) / d["customers"]).quantize(Decimal("0.1")),
                     "rating": avg(d["product"]), "delivery_rating": avg(d["delivery"]),
                     "satisfied": rb._pct(sum(1 for r in d["product"] + d["delivery"] if r >= 4),
                                          len(d["product"] + d["delivery"])) if d["product"] + d["delivery"] else None,
                     "on_time": rb._pct(d["on_time"], d["delivered"]) if d["delivered"] else None,
                     "reviews": len(d["product"]) + len(d["delivery"])})
    return rows


CUSTOMER_METRICS = [
    {"key": "customers", "label": "Clientes", "format": "number"},
    {"key": "ticket", "label": "Ticket médio", "format": "money", "good": "up"},
    {"key": "frequency", "label": "Compras por cliente", "format": "decimal", "good": "up"},
    {"key": "rating", "label": "Nota dos produtos", "format": "decimal", "good": "up"},
    {"key": "delivery_rating", "label": "Nota da entrega", "format": "decimal", "good": "up"},
    {"key": "satisfied", "label": "Satisfeitos (4–5★)", "format": "percent", "good": "up"},
    {"key": "on_time", "label": "Entregas no prazo", "format": "percent", "good": "up"},
]


def delivery_rows(account, store, params):
    """Entrega no prazo × com atraso × atrasada ainda aberta: notas e se o cliente voltou."""
    sales = rb._sales(account, store, params).filter(shipping_address__isnull=False)
    today = timezone.localdate()
    groups = {"on_time": [], "late": [], "late_open": []}
    for sale in sales:
        state = rb.delivery_state(sale, today)
        if state["state"] in groups:
            groups[state["state"]].append((sale, state))
    reviews = defaultdict(lambda: defaultdict(list))
    for sale_id, kind, rating in reviews_of(account, store).filter(sale__in=sales).values_list("sale_id", "kind", "rating"):
        reviews[sale_id][kind].append(rating)
    labels = {"on_time": "No prazo", "late": "Com atraso", "late_open": "Atrasada, ainda aberta"}
    rows = []
    for key, items in groups.items():
        if not items:
            continue
        sale_ids = [s.pk for s, _ in items]
        rows.append({
            "label": labels[key], "deliveries": len(items),
            "delay": avg([max(st["delay"] or 0, 0) for _, st in items]) if key != "on_time" else Decimal(0),
            "delivery_rating": avg([r for sid in sale_ids for r in reviews[sid]["delivery"]]),
            "rating": avg([r for sid in sale_ids for r in reviews[sid]["product"]]),
            "came_back": came_back(account, store, [(s.customer_id, s.completed_at) for s, _ in items]),
            "ticket": rb._ticket(sum((s.total for s, _ in items), ZERO), len(items)),
        })
    return rows


DELIVERY_METRICS = [
    {"key": "deliveries", "label": "Entregas", "format": "number"},
    {"key": "delay", "label": "Atraso médio (dias)", "format": "decimal", "good": "down"},
    {"key": "delivery_rating", "label": "Nota da entrega", "format": "decimal", "good": "up"},
    {"key": "rating", "label": "Nota dos produtos", "format": "decimal", "good": "up"},
    {"key": "came_back", "label": "Voltaram a comprar", "format": "percent", "good": "up"},
    {"key": "ticket", "label": "Ticket médio", "format": "money", "good": "up"},
]


def product_class_rows(account, store, params):
    """Por classe ABC de produto: margem, nota das avaliações e quanto volta em devolução."""
    from starrp.models import SaleReturnItem

    items = rb._items(rb._sales(account, store, params), params)
    classes = product_classes(items)
    agg = {k: {"products": 0, "revenue": ZERO, "cost": ZERO, "ratings": [], "returned": ZERO} for k in CLASSES}
    for cls in classes.values():
        agg[cls]["products"] += 1
    for product, revenue, cost in items.values_list("variant__product_id").annotate(r=Sum("total"), c=Sum(rb.COST)):
        agg[classes[product]]["revenue"] += revenue or ZERO
        agg[classes[product]]["cost"] += cost or ZERO
    for product, rating in reviews_of(account, store).filter(kind="product", product_id__in=classes.keys()).values_list(
            "product_id", "rating"):
        agg[classes[product]]["ratings"].append(rating)
    for product, total in SaleReturnItem.all_objects.filter(sale_item__in=items, sale_return__status="completed").values_list(
            "sale_item__variant__product_id").annotate(t=Sum("total")):
        if product in classes:
            agg[classes[product]]["returned"] += total
    return [{"label": f"Classe {k}", "group": f"Classe {k}", "products": d["products"], "revenue": d["revenue"],
             "margin_pct": rb._pct(d["revenue"] - d["cost"], d["revenue"]), "rating": avg(d["ratings"]),
             "reviews": len(d["ratings"]), "returns": rb._pct(d["returned"], d["revenue"])}
            for k, d in agg.items() if d["products"]]


PRODUCT_METRICS = [
    {"key": "products", "label": "Produtos", "format": "number"},
    {"key": "revenue", "label": "Faturamento", "format": "money", "good": "up"},
    {"key": "margin_pct", "label": "Margem", "format": "percent", "good": "up"},
    {"key": "rating", "label": "Nota média", "format": "decimal", "good": "up"},
    {"key": "reviews", "label": "Avaliações", "format": "number"},
    {"key": "returns", "label": "Devolução (% do faturado)", "format": "percent", "good": "down"},
]


# ── Relatórios de cruzamento ────────────────────────────────────────────────
def cross_customers(account, store, params):
    rows = customer_class_rows(account, store, params)
    facts = [
        _gap(rows, "rating", "Classe A", "Classe C", "Nota dos produtos"),
        _gap(rows, "delivery_rating", "Classe A", "Classe C", "Nota da entrega"),
        _gap(rows, "on_time", "Classe A", "Classe C", "Entregas no prazo", "percent", threshold=Decimal(5)),
        _gap(rows, "frequency", "Classe A", "Classe C", "Compras por cliente"),
    ]
    facts.append(small_base(sum(r["reviews"] for r in rows)))
    best = max((r for r in rows if r.get("rating") is not None), key=lambda r: r["rating"], default=None)
    if best:
        facts.append({"text": f"A classe mais satisfeita é a {best['label'][-1]} (nota {_num(best['rating'])}, "
                              f"{best['reviews']} avaliação(ões)).", "tone": "info"})
    return rb._report("Clientes × satisfação e entrega", "A classe ABC do cliente (pelo faturamento) cruzada com as notas que ele dá, "
                      "a entrega que recebeu e a frequência de compra.", params, [
        rb.kpi("Clientes classificados", sum(r["customers"] for r in rows), "number"),
        rb.kpi("Nota dos clientes A", next((r["rating"] for r in rows if r["label"] == "Classe A"), None) or ZERO, "decimal"),
        rb.kpi("Nota dos clientes C", next((r["rating"] for r in rows if r["label"] == "Classe C"), None) or ZERO, "decimal"),
        rb.kpi("Avaliações cruzadas", sum(r["reviews"] for r in rows), "number", hint="dos clientes que compraram no período"),
    ], [
        insights(facts),
        compare("Cada classe de cliente, lado a lado", CUSTOMER_METRICS, rows,
                "Verde é o melhor valor da coluna; vermelho, o pior. A classe vem do faturamento no período."),
        {"type": "bars", "title": "Notas por classe de cliente", "span": "half", "format": "decimal",
         "x": [r["label"] for r in rows], "series": [{"name": "Produtos", "values": [r["rating"] or 0 for r in rows]},
                                                     {"name": "Entrega", "values": [r["delivery_rating"] or 0 for r in rows]}]},
        {"type": "bars", "title": "Ticket médio por classe", "span": "half", "format": "money",
         "x": [r["label"] for r in rows], "series": [{"name": "Ticket médio", "values": [r["ticket"] for r in rows]}]},
    ], [*rb._sales_filters(account, store, "customer_group", "channel", "seller")])


def cross_deliveries(account, store, params):
    rows = delivery_rows(account, store, params)
    facts = [
        _gap(rows, "delivery_rating", "No prazo", "Com atraso", "Nota da entrega"),
        _gap(rows, "rating", "No prazo", "Com atraso", "Nota dos produtos (o atraso contamina o produto?)"),
        _gap(rows, "came_back", "No prazo", "Com atraso", "Voltaram a comprar", "percent", threshold=Decimal(5)),
    ]
    facts.append(small_base(sum(r["deliveries"] for r in rows), "entregas"))
    late_open = next((r for r in rows if r["label"] == "Atrasada, ainda aberta"), None)
    if late_open:
        facts.append({"text": f"{late_open['deliveries']} entrega(s) já passaram do prazo e não chegaram: ligue antes que vire "
                              "reclamação.", "tone": "bad"})
    return rb._report("Entrega × satisfação e recompra", "Se a entrega chegou no prazo muda a nota do cliente e a chance de ele "
                      "comprar de novo?", params, [
        rb.kpi("Entregas analisadas", sum(r["deliveries"] for r in rows), "number"),
        rb.kpi("Nota no prazo", next((r["delivery_rating"] for r in rows if r["label"] == "No prazo"), None) or ZERO, "decimal"),
        rb.kpi("Nota com atraso", next((r["delivery_rating"] for r in rows if r["label"] == "Com atraso"), None) or ZERO, "decimal",
               good="down"),
        rb.kpi("Recompra após atraso", next((r["came_back"] for r in rows if r["label"] == "Com atraso"), None) or ZERO, "percent"),
    ], [
        insights(facts),
        compare("No prazo × com atraso", DELIVERY_METRICS, rows,
                "\"Voltaram a comprar\" = o cliente fez outra compra depois desta (em qualquer data até hoje)."),
        {"type": "bars", "title": "Nota por situação da entrega", "span": "full", "format": "decimal",
         "x": [r["label"] for r in rows], "series": [{"name": "Entrega", "values": [r["delivery_rating"] or 0 for r in rows]},
                                                     {"name": "Produtos", "values": [r["rating"] or 0 for r in rows]}]},
    ], [*rb._sales_filters(account, store, "channel", "seller")])


def cross_sellers(account, store, params):
    sales = rb._sales(account, store, params).filter(seller__isnull=False)
    start, end = rb._window(params)
    cancelled = dict(rb._scoped(Sale.all_objects.filter(account=account, status=Sale.Status.CANCELLED, seller__isnull=False,
                                                        cancelled_at__date__range=(start, end)), store)
                     .values_list("seller_id").annotate(n=Count("id")))
    items = rb._items(sales, params)
    margin = {s: (r or 0) - (c or 0) for s, r, c in items.values_list("sale__seller_id").annotate(
        r=Sum("total"), c=Sum(rb.COST))}
    ratings = defaultdict(list)
    for seller, rating in reviews_of(account, store).filter(sale__in=sales).values_list("sale__seller_id", "rating"):
        ratings[seller].append(rating)
    rows = []
    for r in sales.values("seller_id", "seller__first_name", "seller__username").annotate(
            n=Count("id"), revenue=Sum("total"), gross=Sum("subtotal"), disc=Sum("discount")):
        sid = r["seller_id"]
        rows.append({"label": r["seller__first_name"] or r["seller__username"], "sales": r["n"],
                     "ticket": rb._ticket(r["revenue"], r["n"]), "discount": rb._pct(r["disc"] or 0, r["gross"] or 0),
                     "margin_pct": rb._pct(margin.get(sid, ZERO), r["revenue"]),
                     "cancel": rb._pct(cancelled.get(sid, 0), r["n"] + cancelled.get(sid, 0)),
                     "rating": avg(ratings[sid]), "reviews": len(ratings[sid])})
    rows.sort(key=lambda r: -r["sales"])
    facts = []
    if len(rows) >= 2:
        high = max(rows, key=lambda r: r["discount"])
        low = min(rows, key=lambda r: r["discount"])
        if high is not low and high["discount"] - low["discount"] >= 1:
            facts.append({"text": f"{high['label']} dá mais desconto ({_num(high['discount'], 'percent')}) e fica com margem "
                                  f"{_num(high['margin_pct'], 'percent')}; {low['label']} desconta {_num(low['discount'], 'percent')} "
                                  f"e tem margem {_num(low['margin_pct'], 'percent')}.",
                          "tone": "bad" if high["margin_pct"] < low["margin_pct"] else "info"})
        rated = [r for r in rows if r["rating"] is not None]
        if rated:
            top = max(rated, key=lambda r: r["rating"])
            facts.append({"text": f"Os clientes atendidos por {top['label']} dão a melhor nota ({_num(top['rating'])}).", "tone": "good"})
        worst_cancel = max(rows, key=lambda r: r["cancel"])
        if worst_cancel["cancel"] > 0:
            facts.append({"text": f"{worst_cancel['label']} tem a maior taxa de cancelamento ({_num(worst_cancel['cancel'], 'percent')}).",
                          "tone": "bad"})
    return rb._report("Vendedores × desconto, margem e satisfação", "Como cada vendedor vende: quanto desconta, quanto sobra de "
                      "margem, quantas vendas cancela e a nota dos clientes que ele atendeu.", params, [
        rb.kpi("Vendedores", len(rows), "number"),
        rb.kpi("Desconto médio", avg([r["discount"] for r in rows]) or ZERO, "percent", good="down"),
        rb.kpi("Margem média", avg([r["margin_pct"] for r in rows]) or ZERO, "percent"),
        rb.kpi("Nota média dos atendidos", avg([x for v in ratings.values() for x in v]) or ZERO, "decimal"),
    ], [
        insights(facts),
        compare("Cada vendedor, lado a lado", [
            {"key": "sales", "label": "Vendas", "format": "number"},
            {"key": "ticket", "label": "Ticket médio", "format": "money", "good": "up"},
            {"key": "discount", "label": "Desconto", "format": "percent", "good": "down"},
            {"key": "margin_pct", "label": "Margem", "format": "percent", "good": "up"},
            {"key": "cancel", "label": "Cancelamento", "format": "percent", "good": "down"},
            {"key": "rating", "label": "Nota dos clientes", "format": "decimal", "good": "up"},
        ], rows, "Desconto em % do valor cheio; cancelamento em % das vendas do vendedor no período."),
    ], [*rb._sales_filters(account, store, "channel", "category")])


QUADRANTS = {"star": "Estrela: vende e agrada", "alert": "Atenção: vende e não agrada",
             "gem": "Joia escondida: agrada e vende pouco", "review": "Revisar: vende pouco e não agrada"}


def cross_products(account, store, params):
    rows = product_class_rows(account, store, params)
    items = rb._items(rb._sales(account, store, params), params)
    classes = product_classes(items)
    names = dict(items.values_list("variant__product_id", "variant__product__name").distinct())
    revenue = dict(items.values_list("variant__product_id").annotate(t=Sum("total")))
    ratings = defaultdict(list)
    for product, rating in reviews_of(account, store).filter(kind="product", product_id__in=classes.keys()).values_list(
            "product_id", "rating"):
        ratings[product].append(rating)
    table, quad_count = [], defaultdict(int)
    for product, cls in classes.items():
        rating = avg(ratings[product])
        if rating is None:
            continue
        good, sells = rating >= 4, cls == "A"
        quad = "star" if sells and good else "alert" if sells else "gem" if good else "review"
        quad_count[quad] += 1
        table.append({"product": names.get(product, "—"), "abc": cls, "revenue": revenue.get(product, ZERO), "rating": rating,
                      "reviews": len(ratings[product]), "quadrant": QUADRANTS[quad]})
    table.sort(key=lambda r: (-Decimal(r["revenue"]), -r["rating"]))
    facts = [_gap(rows, "rating", "Classe A", "Classe C", "Nota dos produtos"),
             _gap(rows, "returns", "Classe A", "Classe C", "Devolução", "percent", higher_is_good=False, threshold=Decimal(1)),
             _gap(rows, "margin_pct", "Classe A", "Classe C", "Margem", "percent", threshold=Decimal(2))]
    facts.append(small_base(sum(r["reviews"] for r in rows)))
    if quad_count["alert"]:
        facts.append({"text": f"{quad_count['alert']} produto(s) vendem muito mas têm nota abaixo de 4: os primeiros a investigar.",
                      "tone": "bad"})
    if quad_count["gem"]:
        facts.append({"text": f"{quad_count['gem']} produto(s) agradam e vendem pouco: dê vitrine para eles.", "tone": "good"})
    return rb._report("Produtos × qualidade e devolução", "A classe ABC do produto cruzada com a nota das avaliações, a margem e a "
                      "devolução.", params, [
        rb.kpi("Produtos avaliados", len(table), "number"),
        rb.kpi("Estrelas", quad_count["star"], "number", hint="vendem muito e agradam"),
        rb.kpi("Atenção", quad_count["alert"], "number", good="down", hint="vendem muito e não agradam"),
        rb.kpi("Joias escondidas", quad_count["gem"], "number", hint="agradam e vendem pouco"),
    ], [
        insights(facts),
        compare("Cada classe de produto, lado a lado", PRODUCT_METRICS, rows),
        {"type": "share", "title": "Produtos avaliados por quadrante", "span": "half", "format": "number",
         "description": "Vende muito = classe A. Agrada = nota 4 ou mais.",
         "rows": [{"label": QUADRANTS[k], "value": quad_count[k]} for k in QUADRANTS if quad_count[k]]},
        {"type": "ranking", "title": "Vendem muito e não agradam", "span": "half", "format": "decimal", "limit": 6,
         "rows": [{"label": r["product"], "value": r["rating"], "sub": f"{rb.brl(r['revenue'])} · {r['reviews']} avaliação(ões)"}
                  for r in table if r["quadrant"] == QUADRANTS["alert"]]},
        # Abas na mesma ordem (e cor) do gráfico de quadrantes.
        {"type": "table", "title": "Produtos avaliados", "span": "full",
         "tabs": {"key": "quadrant", "label": "", "order": [QUADRANTS[k] for k in QUADRANTS if quad_count[k]]},
         "columns": [{"key": "product", "label": "Produto"}, {"key": "abc", "label": "Classe"},
                     {"key": "revenue", "label": "Faturamento", "format": "money"},
                     {"key": "rating", "label": "Nota", "format": "decimal"},
                     {"key": "reviews", "label": "Avaliações", "format": "number"}, {"key": "quadrant", "label": "Quadrante"}],
         "rows": table},
    ], [*rb._sales_filters(account, store, "category", "brand", "channel")])


DISCOUNT_BANDS = [("Sem desconto", Decimal(0), Decimal(0)), ("Até 5%", Decimal("0.01"), Decimal(5)),
                  ("5% a 10%", Decimal("5.01"), Decimal(10)), ("Acima de 10%", Decimal("10.01"), Decimal(1000))]


def cross_discounts(account, store, params):
    sales = list(rb._sales(account, store, params).values("pk", "customer_id", "completed_at", "total", "subtotal", "discount",
                                                          "coupon_discount"))
    cost = dict(SaleItem.all_objects.filter(sale_id__in=[s["pk"] for s in sales], status=SaleItem.Status.ACTIVE).values_list(
        "sale_id").annotate(c=Sum(rb.COST)))
    ratings = defaultdict(list)
    for sale, rating in reviews_of(account, store).filter(sale_id__in=[s["pk"] for s in sales]).values_list("sale_id", "rating"):
        ratings[sale].append(rating)
    bands = {label: [] for label, _, _ in DISCOUNT_BANDS}
    for s in sales:
        disc = (s["discount"] or 0) + (s["coupon_discount"] or 0)
        pct = rb._pct(disc, s["subtotal"] or 0)
        label = next(lbl for lbl, lo, hi in DISCOUNT_BANDS if lo <= pct <= hi) if pct else "Sem desconto"
        bands[label].append(s)
    rows = []
    for label, group in bands.items():
        if not group:
            continue
        revenue = sum((s["total"] for s in group), ZERO)
        rows.append({"label": label, "sales": len(group), "ticket": rb._ticket(revenue, len(group)),
                     "margin_pct": rb._pct(revenue - sum((cost.get(s["pk"]) or ZERO for s in group), ZERO), revenue),
                     "rating": avg([r for s in group for r in ratings[s["pk"]]]),
                     "came_back": came_back(account, store, [(s["customer_id"], s["completed_at"]) for s in group])})
    discounted = [r for r in rows if r["label"] != "Sem desconto"]
    facts = []
    if discounted and any(r["label"] == "Sem desconto" for r in rows):
        biggest = discounted[-1]["label"]
        facts += [_gap(rows, "margin_pct", "Sem desconto", biggest, "Margem", "percent", threshold=Decimal(2)),
                  _gap(rows, "came_back", biggest, "Sem desconto", "Voltaram a comprar", "percent", threshold=Decimal(5)),
                  _gap(rows, "ticket", biggest, "Sem desconto", "Ticket médio", "money", threshold=Decimal(10))]
    return rb._report("Desconto × margem, ticket e recompra", "O desconto traz o cliente de volta ou só come a margem?", params, [
        rb.kpi("Vendas analisadas", len(sales), "number"),
        rb.kpi("Vendas com desconto", rb._pct(sum(r["sales"] for r in discounted), len(sales)), "percent"),
        rb.kpi("Margem sem desconto", next((r["margin_pct"] for r in rows if r["label"] == "Sem desconto"), ZERO), "percent"),
        rb.kpi("Margem com desconto", avg([r["margin_pct"] for r in discounted]) or ZERO, "percent"),
    ], [
        insights(facts or [{"text": "Ainda não há vendas com e sem desconto suficientes para comparar no período.", "tone": "info"}]),
        compare("Faixas de desconto, lado a lado", [
            {"key": "sales", "label": "Vendas", "format": "number"},
            {"key": "ticket", "label": "Ticket médio", "format": "money", "good": "up"},
            {"key": "margin_pct", "label": "Margem", "format": "percent", "good": "up"},
            {"key": "rating", "label": "Nota", "format": "decimal", "good": "up"},
            {"key": "came_back", "label": "Voltaram a comprar", "format": "percent", "good": "up"},
        ], rows, "Desconto em % do valor cheio da venda (desconto + cupom)."),
    ], [*rb._sales_filters(account, store, "seller", "channel", "category")])
