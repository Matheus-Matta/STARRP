"""Promoções: o desconto se paga? Três relatórios, todos com veredito escrito.

- Visão geral: quanto se abriu mão por origem (promoção de produto, cupom, desconto manual) e
  o resultado de cada uma (ticket, margem, recompra, nota).
- Promoções de produto: por regra da tabela de desconto, vendeu mais POR DIA e o LUCRO POR DIA
  subiu (contra os dias sem a promoção, nos mesmos produtos)? Veredito: compensou, vendeu mais e
  lucrou menos, não aumentou as vendas, prejuízo (margem negativa) ou sem base para comparar.
- Cupons: por cupom, lucro das vendas com ele, se o cliente voltou (e quanto gastou depois),
  novos clientes e o retorno por R$ 1 de desconto. Veredito: fideliza e dá lucro, dá lucro mas
  não fideliza, fideliza no prejuízo, não se paga.

Desconto de promoção = (preço cheio − preço cobrado) × quantidade nos itens com promoção;
manual = o da venda + o das linhas; cupom = o abatido pelo cupom. Lucro bruto = o que entrou
em mercadoria (sem frete) − custo.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Min, Sum
from django.utils import timezone

from starrp.models import Sale, SaleItem
from starrp.services import report_book as rb
from starrp.services import report_cross as rx

ZERO = Decimal("0")


def _sale_rows(sales):
    """Uma linha por venda: total, custo, os três descontos e o cliente."""
    rows = {s["pk"]: {**s, "cost": ZERO, "promo": ZERO, "line_discount": ZERO}
            for s in sales.values("pk", "number", "customer_id", "customer_name", "seller__first_name", "completed_at",
                                  "total", "freight", "subtotal", "discount", "coupon_discount", "coupon_code")}
    for sale_id, qty, list_price, unit_price, discount, cost, promo in SaleItem.all_objects.filter(
            sale_id__in=rows.keys(), status=SaleItem.Status.ACTIVE).values_list(
            "sale_id", "quantity", "list_price", "unit_price", "discount", "unit_cost", "promotion_id"):
        r = rows[sale_id]
        r["cost"] += (cost or ZERO) * qty
        r["line_discount"] += discount or ZERO
        if promo and list_price > unit_price:
            r["promo"] += (list_price - unit_price) * qty
    for r in rows.values():
        r["manual"] = (r["discount"] or ZERO) + r["line_discount"]
        r["coupon"] = r["coupon_discount"] or ZERO
        r["profit"] = (r["total"] or ZERO) - (r["freight"] or ZERO) - r["cost"]
        r["source"] = ("cupom" if r["coupon"] else "manual" if r["manual"] else "promo" if r["promo"] else "none")
    return list(rows.values())


SOURCES = {"promo": "Promoção de produto", "cupom": "Cupom", "manual": "Desconto manual", "none": "Sem desconto"}


AFTER_DAYS = 60


def _later(account, store, pairs, skip=()):
    """O que os clientes gastaram nos 60 dias depois do PRIMEIRO uso (um cliente conta uma vez;
    as vendas de `skip` — as próprias com cupom — ficam de fora)."""
    first = {}
    for customer, moment in pairs:
        if customer and (customer not in first or moment < first[customer]):
            first[customer] = moment
    total = ZERO
    for customer, moment, value, pk in rb._scoped(Sale.all_objects.filter(
            account=account, status=Sale.Status.COMPLETED, customer_id__in=first.keys()), store).values_list(
            "customer_id", "completed_at", "total", "pk"):
        start = first[customer]
        if pk not in skip and start < moment <= start + timedelta(days=AFTER_DAYS):
            total += value
    return total


def _loss_rows(sales):
    """Vendas em que o que entrou (sem frete) não pagou o custo: a lista "deram prejuízo"."""
    out = [{"number": s["number"], "date": timezone.localtime(s["completed_at"]).date(),
            "customer": s["customer_name"] or "—", "seller": s["seller__first_name"] or "—", "kind": SOURCES[s["source"]],
            "given": s["promo"] + s["coupon"] + s["manual"], "revenue": s["total"] - (s["freight"] or ZERO),
            "cost": s["cost"], "loss": -s["profit"]} for s in sales if s["profit"] < 0]
    return sorted(out, key=lambda r: -r["loss"])


def overview(account, store, params):
    sales = _sale_rows(rb._sales(account, store, params))
    reviews = defaultdict(list)
    for sale_id, rating in rx.reviews_of(account, store).filter(sale_id__in=[s["pk"] for s in sales]).values_list(
            "sale_id", "rating"):
        reviews[sale_id].append(rating)
    gross = sum((s["subtotal"] or ZERO) + s["promo"] for s in sales)  # valor cheio (antes da promoção)
    given = {k: sum((s[k] for s in sales), ZERO) for k in ("promo", "coupon", "manual")}
    total_given = sum(given.values(), ZERO)
    rows = []
    for key, label in SOURCES.items():
        group = [s for s in sales if s["source"] == key]
        if not group:
            continue
        revenue = sum((s["total"] - (s["freight"] or ZERO) for s in group), ZERO)
        rows.append({"label": label, "sales": len(group), "ticket": rb._ticket(revenue, len(group)),
                     "given": sum((s["promo"] + s["coupon"] + s["manual"] for s in group), ZERO),
                     "margin_pct": rb._pct(sum((s["profit"] for s in group), ZERO), revenue),
                     "came_back": rx.came_back(account, store, [(s["customer_id"], s["completed_at"]) for s in group]),
                     "rating": rx.avg([r for s in group for r in reviews[s["pk"]]])})
    grain, (keys, labels) = rb._grain(params), rb._buckets(params)
    per = {k: defaultdict(lambda: ZERO) for k in ("promo", "coupon", "manual")}
    for s in sales:
        bucket = rb._bucket(timezone.localtime(s["completed_at"]).date(), grain)
        for k in per:
            per[k][bucket] += s[k]
    none = next((r for r in rows if r["label"] == SOURCES["none"]), None)
    facts = []
    for r in rows:
        if r is none or not none:
            continue
        facts.append(rx._gap([r, none], "margin_pct", r["label"], none["label"], "Margem", "percent", threshold=Decimal(2)))
        facts.append(rx._gap([r, none], "came_back", r["label"], none["label"], "Voltaram a comprar", "percent",
                             threshold=Decimal(5)))
    losses = _loss_rows(sales)
    if losses:
        facts.insert(0, {"text": f"{len(losses)} venda(s) deram prejuízo (o desconto passou da margem): perda de "
                                 f"{rb.brl(sum((r['loss'] for r in losses), ZERO))}. Veja a lista no fim.", "tone": "bad"})
    facts.append({"text": f"No período a loja abriu mão de {rb.brl(total_given)} ({rb.pt(rb._pct(total_given, gross))}% do valor "
                          f"cheio) em descontos.", "tone": "info"})
    return rb._report("Descontos: visão geral", "Quanto a loja abriu mão em promoção, cupom e desconto manual — e o que cada um "
                      "devolveu em margem, ticket e recompra.", params, [
        rb.kpi("Total em descontos", total_given, good="down", hint=f"{rb.pt(rb._pct(total_given, gross))}% do valor cheio"),
        rb.kpi("Em promoções de produto", given["promo"], good="down"),
        rb.kpi("Em cupons", given["coupon"], good="down"),
        rb.kpi("Em desconto manual", given["manual"], good="down"),
        rb.kpi("Vendas com algum desconto", rb._pct(sum(1 for s in sales if s["source"] != "none"), len(sales)), "percent"),
        rb.kpi("Vendas que deram prejuízo", len(_loss_rows(sales)), "number", good="down",
               hint=f"perda de {rb.brl(sum((r['loss'] for r in _loss_rows(sales)), ZERO))}"),
    ], [
        rx.insights(facts),
        rx.compare("Cada tipo de desconto × resultado", [
            {"key": "sales", "label": "Vendas", "format": "number"},
            {"key": "given", "label": "Desconto dado", "format": "money", "good": "down"},
            {"key": "ticket", "label": "Ticket médio", "format": "money", "good": "up"},
            {"key": "margin_pct", "label": "Margem", "format": "percent", "good": "up"},
            {"key": "came_back", "label": "Voltaram a comprar", "format": "percent", "good": "up"},
            {"key": "rating", "label": "Nota", "format": "decimal", "good": "up"},
        ], rows, "Uma venda conta no tipo principal: cupom › desconto manual › promoção de produto."),
        {"type": "share", "title": "De onde vem o desconto", "span": "half", "format": "money",
         "rows": [{"label": SOURCES[k if k != "coupon" else "cupom"], "value": v} for k, v in given.items() if v]},
        {"type": "bars", "title": f"Desconto concedido {rb.GRAIN_WORD[grain]}", "span": "half", "format": "money", "stacked": True,
         "grain": grain, "x": labels, "series": [{"name": SOURCES["promo"], "values": [per["promo"][k] for k in keys]},
                                                 {"name": SOURCES["cupom"], "values": [per["coupon"][k] for k in keys]},
                                                 {"name": SOURCES["manual"], "values": [per["manual"][k] for k in keys]}]},
        {"type": "table", "title": "Vendas que deram prejuízo", "span": "full", "empty": "Nenhuma venda deu prejuízo no período: o desconto nunca passou da margem.", "columns": [
            {"key": "number", "label": "Venda", "format": "number"}, {"key": "date", "label": "Data", "format": "date"},
            {"key": "customer", "label": "Cliente"}, {"key": "seller", "label": "Vendedor"}, {"key": "kind", "label": "Desconto"},
            {"key": "given", "label": "Desconto dado", "format": "money"}, {"key": "revenue", "label": "Recebido", "format": "money"},
            {"key": "cost", "label": "Custo", "format": "money"}, {"key": "loss", "label": "Prejuízo", "format": "money"}],
         "rows": _loss_rows(sales)},
    ], rb._sales_filters(account, store, "channel", "seller", "category"))


# ── promoções de produto ────────────────────────────────────────────────────
def _active_days(promotion, start, end):
    """Dias do período em que a regra valeu (a janela dela e a da tabela)."""
    begins = [d for d in (promotion.starts_at, promotion.table.starts_at) if d]
    ends = [d for d in (promotion.ends_at, promotion.table.ends_at) if d]
    first = max([start, *[timezone.localtime(d).date() for d in begins]])
    last = min([end, *[timezone.localtime(d).date() for d in ends]])
    return max((last - first).days + 1, 0)


VERDICTS = {"won": "Compensou: o lucro por dia subiu", "volume": "Prejuízo: vendeu mais, mas lucrou menos",
            "flat": "Prejuízo: não vendeu mais e lucrou menos", "loss": "Prejuízo: vendeu abaixo do custo",
            "nobase": "Sem base para comparar"}
# Prejuízo = a loja ganhou MENOS do que ganharia sem a promoção (ou vendeu abaixo do custo).
LOSSES = ("volume", "flat", "loss")


def products(account, store, params):
    from starrp.models import Promotion

    start, end = rb._window(params)
    period_days = (end - start).days + 1
    items = rb._items(rb._sales(account, store, params), params)
    promo_items = items.filter(promotion__isnull=False)
    promotions = {p.pk: p for p in Promotion.all_objects.filter(pk__in=promo_items.values("promotion_id")).select_related("table")}
    product_ids = set(promo_items.values_list("variant__product_id", flat=True))
    names = dict(items.filter(variant__product_id__in=product_ids).values_list("variant__product_id", "variant__product__name").distinct())

    def agg(qs):
        out = defaultdict(lambda: {"units": ZERO, "revenue": ZERO, "cost": ZERO, "given": ZERO})
        for product, units, revenue, cost, given in qs.values_list("variant__product_id").annotate(
                u=Sum("quantity"), r=Sum("total"), c=Sum(rb.COST),
                g=Sum((F("list_price") - F("unit_price")) * F("quantity"))):
            out[product] = {"units": units or ZERO, "revenue": revenue or ZERO, "cost": cost or ZERO, "given": max(given or ZERO, ZERO)}
        return out

    normal = agg(items.filter(promotion__isnull=True, variant__product_id__in=product_ids))
    table, by_rule = [], defaultdict(lambda: {"units": ZERO, "profit": ZERO, "given": ZERO, "revenue": ZERO,
                                              "n_units": ZERO, "n_profit": ZERO, "days": 0, "n_days": 0, "products": 0})
    verdicts = defaultdict(int)
    for promo_id, promotion in promotions.items():
        days = max(_active_days(promotion, start, end), 1)
        n_days = max(period_days - days, 0)
        for product, d in agg(promo_items.filter(promotion_id=promo_id)).items():
            n = normal.get(product, {"units": ZERO, "revenue": ZERO, "cost": ZERO})
            profit, n_profit = d["revenue"] - d["cost"], n["revenue"] - n["cost"]
            per_day = (d["units"] / days, profit / days)
            n_per_day = (n["units"] / n_days, n_profit / n_days) if n_days and n["units"] else (None, None)
            if profit < 0:
                verdict = "loss"
            elif n_per_day[0] is None:
                verdict = "nobase"
            elif per_day[1] > n_per_day[1]:
                verdict = "won"
            elif per_day[0] > n_per_day[0]:
                verdict = "volume"
            else:
                verdict = "flat"
            verdicts[verdict] += 1
            # Ganho/perda da promoção em R$: (lucro/dia com − lucro/dia sem) × dias com a promoção;
            # sem base para comparar, só o lucro negativo (vendeu abaixo do custo) conta como perda.
            impact = ((per_day[1] - n_per_day[1]) * days if n_per_day[1] is not None
                      else profit if profit < 0 else None)
            table.append({"promotion": promotion.name, "product": names.get(product, "—"), "units": d["units"],
                          "impact": impact.quantize(Decimal("0.01")) if impact is not None else None,
                          "units_day": per_day[0].quantize(Decimal("0.01")),
                          "n_units_day": n_per_day[0].quantize(Decimal("0.01")) if n_per_day[0] is not None else None,
                          "profit_day": per_day[1].quantize(Decimal("0.01")),
                          "n_profit_day": n_per_day[1].quantize(Decimal("0.01")) if n_per_day[1] is not None else None,
                          "margin_pct": rb._pct(profit, d["revenue"]), "n_margin_pct": rb._pct(n_profit, n["revenue"]) if n["revenue"] else None,
                          "given": d["given"], "verdict": VERDICTS[verdict]})
            rule = by_rule[promotion.name]
            rule["units"] += d["units"]
            rule["profit"] += profit
            rule["given"] += d["given"]
            rule["revenue"] += d["revenue"]
            rule["n_units"] += n["units"]
            rule["n_profit"] += n_profit
            rule["days"], rule["n_days"] = days, n_days
            rule["products"] += 1
            if impact is not None:
                rule["impact"] = rule.get("impact", ZERO) + impact
    rows = []
    for name, r in by_rule.items():
        rows.append({"label": name, "products": r["products"], "given": r["given"],
                     "units_day": (r["units"] / r["days"]).quantize(Decimal("0.01")),
                     # Sem venda fora da promoção não há base: "—", e nenhuma conclusão.
                     "n_units_day": (r["n_units"] / r["n_days"]).quantize(Decimal("0.01")) if r["n_days"] and r["n_units"] else None,
                     "profit_day": (r["profit"] / r["days"]).quantize(Decimal("0.01")),
                     "n_profit_day": (r["n_profit"] / r["n_days"]).quantize(Decimal("0.01")) if r["n_days"] and r["n_units"] else None,
                     "margin_pct": rb._pct(r["profit"], r["revenue"]),
                     "impact": r["impact"].quantize(Decimal("0.01")) if "impact" in r else None})
    rows.sort(key=lambda r: -r["given"])
    losers = sorted((t for t in table if t["verdict"] in [VERDICTS[k] for k in LOSSES]),
                    key=lambda t: t["impact"] if t["impact"] is not None else ZERO)
    lost = -sum((t["impact"] for t in losers if t["impact"] is not None and t["impact"] < 0), ZERO)
    facts = []
    for r in rows[:6]:
        if r["n_profit_day"] is None:
            continue
        up = r["profit_day"] > r["n_profit_day"]
        facts.append({"text": f"{r['label']}: {rb.pt(r['units_day'])} un./dia com a promoção contra {rb.pt(r['n_units_day'])} sem; "
                              f"lucro de {rb.brl(r['profit_day'])}/dia contra {rb.brl(r['n_profit_day'])}/dia.",
                      "tone": "good" if up else "bad"})
    if losers:
        facts.insert(0, {"text": f"{len(losers)} produto(s) deram prejuízo: a loja ganhou {rb.brl(lost)} a menos do que "
                                 f"ganharia sem a promoção. Veja a lista \"Deram prejuízo\".", "tone": "bad"})
    else:
        facts.insert(0, {"text": "Nenhuma promoção deu prejuízo no período (entre os produtos com base para comparar).",
                         "tone": "good"})
    if verdicts["loss"]:
        facts.append({"text": f"{verdicts['loss']} produto(s) foram vendidos abaixo do custo na promoção.", "tone": "bad"})
    if not facts:
        facts.append({"text": "Ainda não há dias com e sem promoção nos mesmos produtos para comparar.", "tone": "info"})
    total_given = sum((r["given"] for r in rows), ZERO)
    return rb._report("Promoções de produto: vale a pena?", "Cada regra da tabela de desconto: vendeu mais por dia e o lucro por dia "
                      "subiu, comparado aos dias sem a promoção nos mesmos produtos?", params, [
        rb.kpi("Desconto em promoções", total_given, good="down"),
        rb.kpi("Compensaram", verdicts["won"], "number", hint="produtos com lucro por dia maior"),
        rb.kpi("Deram prejuízo", len(losers), "number", good="down", hint="lucraram menos que sem a promoção"),
        rb.kpi("Perda com promoções", lost, good="down", hint="o que deixou de ganhar"),
        rb.kpi("Sem base para comparar", verdicts["nobase"], "number", hint="só venderam com a promoção"),
    ], [
        rx.insights(facts),
        rx.compare("Cada promoção: com × sem", [
            {"key": "products", "label": "Produtos", "format": "number"},
            {"key": "given", "label": "Desconto dado", "format": "money"},
            {"key": "units_day", "label": "Un./dia com", "format": "decimal", "good": "up"},
            {"key": "n_units_day", "label": "Un./dia sem", "format": "decimal"},
            {"key": "profit_day", "label": "Lucro/dia com", "format": "money", "good": "up"},
            {"key": "n_profit_day", "label": "Lucro/dia sem", "format": "money"},
            {"key": "margin_pct", "label": "Margem com", "format": "percent", "good": "up"},
            {"key": "impact", "label": "Ganho / perda", "format": "money", "good": "up"},
        ], rows, "\"Sem\" = os mesmos produtos nos dias do período em que a promoção não valia. \"Ganho / perda\" = quanto a "
                 "promoção rendeu a mais (ou a menos) do que se os produtos tivessem ficado sem ela."),
        {"type": "ranking", "title": "Deram prejuízo", "span": "full", "format": "money", "limit": 10,
         "empty": "Nenhuma promoção deu prejuízo no período.",
         "description": "Quanto cada produto deixou de ganhar com a promoção (ou perdeu vendendo abaixo do custo).",
         "rows": [{"label": t["product"], "value": -(t["impact"] or ZERO), "sub": f"{t['promotion']} · {t['verdict'][10:]}",
                   "group": "Prejuízo"} for t in losers]},
        {"type": "share", "title": "Veredito por produto", "span": "half", "format": "number",
         "rows": [{"label": VERDICTS[k], "value": verdicts[k]} for k in VERDICTS if verdicts[k]]},  # mesma ordem/cor das abas
        {"type": "ranking", "title": "Desconto dado por promoção", "span": "half", "format": "money", "limit": 6,
         "rows": [{"label": r["label"], "value": r["given"], "sub": f"margem {rb.pt(r['margin_pct'])}%"} for r in rows]},
        {"type": "table", "title": "Produto a produto", "span": "full",
         "tabs": {"key": "verdict", "label": "", "order": [VERDICTS[k] for k in VERDICTS if verdicts[k]]},
         "columns": [{"key": "promotion", "label": "Promoção"}, {"key": "product", "label": "Produto"},
                     {"key": "units", "label": "Un. na promoção", "format": "quantity"},
                     {"key": "units_day", "label": "Un./dia com", "format": "decimal"},
                     {"key": "n_units_day", "label": "Un./dia sem", "format": "decimal"},
                     {"key": "profit_day", "label": "Lucro/dia com", "format": "money"},
                     {"key": "n_profit_day", "label": "Lucro/dia sem", "format": "money"},
                     {"key": "margin_pct", "label": "Margem com", "format": "percent"},
                     {"key": "n_margin_pct", "label": "Margem sem", "format": "percent"},
                     {"key": "given", "label": "Desconto dado", "format": "money"},
                     {"key": "impact", "label": "Ganho / perda", "format": "money"}, {"key": "verdict", "label": "Veredito"}],
         "rows": sorted(table, key=lambda r: -r["given"])},
    ], rb._sales_filters(account, store, "category", "brand", "channel"))


# ── cupons ──────────────────────────────────────────────────────────────────
COUPON_VERDICTS = {"both": "Fideliza e dá lucro", "profit": "Dá lucro, não fideliza", "loyal": "Fideliza, mas no prejuízo",
                   "bad": "Não se paga"}


def coupons(account, store, params):
    sales = rb._sales(account, store, params)
    rows_by_sale = {s["pk"]: s for s in _sale_rows(sales)}
    with_coupon = [s for s in rows_by_sale.values() if s["coupon"]]
    without = [s for s in rows_by_sale.values() if not s["coupon"]]
    base_back = rx.came_back(account, store, [(s["customer_id"], s["completed_at"]) for s in without])
    base_ticket = rb._ticket(sum((s["total"] for s in without), ZERO), len(without))
    firsts = {}
    for customer, first in rb._scoped(Sale.all_objects.filter(account=account, status=Sale.Status.COMPLETED,
                                                              customer__isnull=False), store).values_list("customer_id").annotate(
            f=Min("completed_at")):
        firsts[customer] = first
    by_code = defaultdict(list)
    for s in with_coupon:
        by_code[s["coupon_code"] or "—"].append(s)
    rows, verdicts = [], defaultdict(int)
    for code, group in by_code.items():
        given = sum((s["coupon"] for s in group), ZERO)
        profit = sum((s["profit"] for s in group), ZERO)
        pairs = [(s["customer_id"], s["completed_at"]) for s in group]
        back = rx.came_back(account, store, pairs)
        after = _later(account, store, pairs, skip={s["pk"] for s in with_coupon})
        after_profit = (after * (sum((s["profit"] for s in without), ZERO) / sum((s["total"] for s in without), ZERO))
                        if without and sum((s["total"] for s in without), ZERO) else ZERO)
        ret = ((profit + after_profit) / given).quantize(Decimal("0.01")) if given else None
        # Fideliza = volta tanto quanto (ou mais que) quem compra sem cupom; dá lucro = a venda ficou no azul.
        loyal = back is not None and base_back is not None and back >= base_back
        verdict = "both" if loyal and profit > 0 else "profit" if profit > 0 else "loyal" if loyal else "bad"
        verdicts[verdict] += 1
        rows.append({"label": code, "result": (profit + after_profit).quantize(Decimal("0.01")),
                     "losses": sum(1 for s in group if s["profit"] < 0),
                     "uses": len(group), "customers": len({s["customer_id"] for s in group if s["customer_id"]}),
                     "new": sum(1 for s in group if s["customer_id"] and firsts.get(s["customer_id"]) == s["completed_at"]),
                     "given": given, "ticket": rb._ticket(sum((s["total"] for s in group), ZERO), len(group)),
                     "margin_pct": rb._pct(profit, sum((s["total"] - (s["freight"] or ZERO) for s in group), ZERO)),
                     "came_back": back, "after": after, "return": ret, "verdict": COUPON_VERDICTS[verdict]})
    rows.sort(key=lambda r: -r["uses"])
    baseline = {"label": "Sem cupom", "uses": len(without), "customers": len({s["customer_id"] for s in without if s["customer_id"]}),
                "given": ZERO, "ticket": base_ticket,
                "margin_pct": rb._pct(sum((s["profit"] for s in without), ZERO),
                                      sum((s["total"] - (s["freight"] or ZERO) for s in without), ZERO)),
                "came_back": base_back}
    facts = []
    # "O que mais devolve" só entre cupons com 3+ usos (1 uso barato dá um retorno enorme e enganoso).
    best = max((r for r in rows if r["return"] is not None and r["uses"] >= 3), key=lambda r: r["return"], default=None)
    if best:
        facts.append({"text": f"{best['label']} é o que mais devolve: cada R$ 1 de desconto trouxe {rb.brl(best['return'])} de lucro "
                              f"(na venda e nas compras dos {AFTER_DAYS} dias seguintes).", "tone": "good"})
    for r in rows[:5]:
        if r["came_back"] is not None and base_back is not None:
            diff = r["came_back"] - base_back
            if abs(diff) >= 10:
                facts.append({"text": f"Quem usou {r['label']} voltou a comprar {'mais' if diff > 0 else 'menos'} "
                                      f"({rb.pt(r['came_back'])}%) do que quem comprou sem cupom ({rb.pt(base_back)}%).",
                              "tone": "good" if diff > 0 else "bad"})
    coupon_losses = _loss_rows(with_coupon)
    if coupon_losses:
        facts.insert(0, {"text": f"{len(coupon_losses)} venda(s) com cupom deram prejuízo (o cupom passou da margem): perda de "
                                 f"{rb.brl(sum((r['loss'] for r in coupon_losses), ZERO))}.", "tone": "bad"})
    else:
        facts.insert(0, {"text": "Nenhuma venda com cupom deu prejuízo no período.", "tone": "good"})
    worst = [r for r in rows if r["verdict"] == COUPON_VERDICTS["bad"]]
    if worst:
        facts.append({"text": f"Não se pagam no período: {', '.join(r['label'] for r in worst[:4])}.", "tone": "bad"})
    facts.append(rx.small_base(len(with_coupon), "usos de cupom"))
    return rb._report("Cupons: fidelizam e dão lucro?", "Cada cupom usado: lucro na venda, se o cliente voltou (e quanto gastou "
                      "depois), clientes novos e quanto cada R$ 1 de desconto devolveu.", params, [
        rb.kpi("Usos de cupom", len(with_coupon), "number"),
        rb.kpi("Desconto em cupons", sum((r["given"] for r in rows), ZERO), good="down"),
        rb.kpi("Recompra com cupom", rx.came_back(account, store, [(s["customer_id"], s["completed_at"]) for s in with_coupon]) or ZERO,
               "percent", hint=f"sem cupom: {rb.pt(base_back or 0)}%"),
        rb.kpi("Clientes novos via cupom", sum(r["new"] for r in rows), "number", hint="a 1ª compra deles foi com cupom"),
        rb.kpi("Fidelizam e dão lucro", verdicts["both"], "number", hint=f"de {len(rows)} cupom(ns) usados"),
        rb.kpi("Vendas com cupom no prejuízo", len(coupon_losses), "number", good="down",
               hint=f"perda de {rb.brl(sum((r['loss'] for r in coupon_losses), ZERO))}"),
    ], [
        rx.insights(facts),
        rx.compare("Cada cupom × compra sem cupom", [
            {"key": "uses", "label": "Usos", "format": "number"},
            {"key": "given", "label": "Desconto dado", "format": "money", "good": "down"},
            {"key": "ticket", "label": "Ticket médio", "format": "money", "good": "up"},
            {"key": "margin_pct", "label": "Margem", "format": "percent", "good": "up"},
            {"key": "came_back", "label": "Voltaram a comprar", "format": "percent", "good": "up"},
            {"key": "return", "label": "Lucro por R$ 1 de desconto", "format": "money", "good": "up"},
            {"key": "losses", "label": "Vendas no prejuízo", "format": "number", "good": "down"},
        ], [*rows, baseline], f"\"Lucro por R$ 1\" soma o lucro da venda com cupom e o das compras dos {AFTER_DAYS} dias "
                               "seguintes (estimado pela margem média das vendas sem cupom)."),
        {"type": "share", "title": "Veredito dos cupons", "span": "half", "format": "number",
         "rows": [{"label": COUPON_VERDICTS[k], "value": verdicts[k]} for k in COUPON_VERDICTS if verdicts[k]]},  # mesma ordem/cor das abas
        {"type": "ranking", "title": f"Gasto nos {AFTER_DAYS} dias depois do cupom", "span": "half", "format": "money", "limit": 6,
         "description": "O que os clientes do cupom compraram nas visitas seguintes (cada cliente conta uma vez).",
         "rows": [{"label": r["label"], "value": r["after"], "sub": f"{r['customers']} cliente(s)"} for r in rows]},
        {"type": "table", "title": "Cupons usados", "span": "full",
         "tabs": {"key": "verdict", "label": "", "order": [COUPON_VERDICTS[k] for k in COUPON_VERDICTS if verdicts[k]]},
         "columns": [{"key": "label", "label": "Cupom"}, {"key": "uses", "label": "Usos", "format": "number"},
                     {"key": "customers", "label": "Clientes", "format": "number"},
                     {"key": "new", "label": "Novos", "format": "number"},
                     {"key": "given", "label": "Desconto dado", "format": "money"},
                     {"key": "ticket", "label": "Ticket", "format": "money"},
                     {"key": "margin_pct", "label": "Margem", "format": "percent"},
                     {"key": "came_back", "label": "Voltaram", "format": "percent"},
                     {"key": "after", "label": f"Gasto em {AFTER_DAYS} dias", "format": "money"},
                     {"key": "return", "label": "Lucro por R$ 1", "format": "money"},
                     {"key": "result", "label": "Lucro trazido", "format": "money"},
                     {"key": "losses", "label": "Vendas no prejuízo", "format": "number"}, {"key": "verdict", "label": "Veredito"}],
         "rows": rows},
        {"type": "table", "title": "Vendas com cupom que deram prejuízo", "span": "full", "empty": "Nenhuma venda com cupom deu prejuízo no período: o cupom nunca passou da margem.", "columns": [
            {"key": "number", "label": "Venda", "format": "number"}, {"key": "date", "label": "Data", "format": "date"},
            {"key": "customer", "label": "Cliente"}, {"key": "seller", "label": "Vendedor"}, {"key": "kind", "label": "Desconto"},
            {"key": "given", "label": "Desconto dado", "format": "money"}, {"key": "revenue", "label": "Recebido", "format": "money"},
            {"key": "cost", "label": "Custo", "format": "money"}, {"key": "loss", "label": "Prejuízo", "format": "money"}],
         "rows": _loss_rows(with_coupon)},
    ], rb._sales_filters(account, store, "channel", "seller", "customer_group"))

