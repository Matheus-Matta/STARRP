"""A decisão: com o mercado e o CUSTO, qual preço sugerir e se vale a pena aderir.

Referência = mediana das ofertas pareadas (nunca o menor preço: um anúncio errado puxaria
tudo), sem as fora da curva (IQR). Faixa neutra em volta da mediana (padrão ±10%).

- Acima do mercado → sugere a mediana, mas NUNCA abaixo do piso (custo com a margem mínima).
  Piso acima do preço atual = baixar não vale a pena: fica sem sugestão e o motivo diz por quê.
- Abaixo do mercado → sugere subir até o P25 (continua entre os mais baratos), ganhando margem.
- No mercado, mas com margem abaixo da mínima → sugere subir até o piso (sem passar do P75).
- Sem custo cadastrado → sugere pelo mercado, mas "vale a pena?" fica em aberto.
- Poucas ofertas do mesmo produto → só informa.
"""
import statistics
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
SPREAD_REVIEW = Decimal("25")  # % de espalhamento a partir do qual alguém precisa olhar
WEAK_MATCH = Decimal("90")


@dataclass
class Rules:
    min_margin: Decimal = Decimal("20")
    band: Decimal = Decimal("10")
    min_competitors: int = 3
    match_min: Decimal = Decimal("85")

    @classmethod
    def of(cls, account):
        return cls(Decimal(account.price_min_margin), Decimal(account.price_band), account.price_min_competitors,
                   Decimal(account.price_match_min))


def money(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value):
    return f"{value:.1f}%".replace(".", ",")


def margin(price, cost):
    if not price or not cost:
        return None
    return ((price - cost) / price * HUNDRED).quantize(CENT, ROUND_HALF_UP)


def floor_price(cost, min_margin):
    """Menor preço que ainda dá a margem mínima (sobre o preço de venda)."""
    if not cost:
        return None
    return (cost / (1 - min_margin / HUNDRED)).quantize(CENT, ROUND_CEILING)


def _quartiles(prices):
    if len(prices) == 1:
        return prices[0], prices[0], prices[0]
    q1, q2, q3 = statistics.quantiles(prices, n=4, method="inclusive")
    return Decimal(q1), Decimal(q2), Decimal(q3)


def reference(offers, rules):
    """`offers`: [(preço, nota)]. Devolve as usadas e as estatísticas (sem as fora da curva)."""
    paired = sorted(Decimal(price) for price, score in offers if Decimal(score) >= rules.match_min)
    kept = paired
    if len(paired) >= 4:
        q1, _, q3 = _quartiles(paired)
        spread = (q3 - q1) * Decimal("1.5")
        kept = [p for p in paired if q1 - spread <= p <= q3 + spread]
    if not kept:
        return kept, None
    p25, median, p75 = _quartiles(kept)
    return kept, {"min": kept[0], "p25": p25.quantize(CENT), "median": Decimal(median).quantize(CENT),
                  "p75": p75.quantize(CENT), "max": kept[-1],
                  "avg": (sum(kept) / len(kept)).quantize(CENT, ROUND_HALF_UP)}


def decide(price, cost, offers, rules):
    """O que gravar no processo (campos do `PriceCheck`). `offers`: [(preço, nota)]."""
    price, cost = Decimal(price), Decimal(cost or 0)
    kept, stats = reference(offers, rules)
    scores = [Decimal(s) for _, s in offers if Decimal(s) >= rules.match_min]
    floor = floor_price(cost, rules.min_margin)
    out = {
        "current_price": price, "cost": cost, "current_margin": margin(price, cost), "competitors": len(kept),
        "offers_found": len(offers), "floor_price": floor, "suggested_price": None, "suggested_margin": None,
        "worth_it": None, "needs_review": False, "position": "unknown",
        "market_min": None, "market_p25": None, "market_median": None, "market_p75": None, "market_avg": None, "market_max": None,
        "market_rank": None, "price_index": None,
        "dispersion": None, "confidence": (sum(scores) / len(scores)).quantize(CENT) if scores else None,
    }
    if stats:
        out.update(market_min=stats["min"], market_p25=stats["p25"], market_median=stats["median"],
                   market_p75=stats["p75"], market_avg=stats["avg"], market_max=stats["max"],
                   market_rank=sum(other < price for other in kept) + 1)
    if len(kept) < rules.min_competitors or not stats:
        found = f"{len(kept)} oferta{'s' if len(kept) != 1 else ''} do mesmo produto"
        return {**out, "reason": f"Só {found} (mínimo {rules.min_competitors}): sem base para sugerir preço."}

    median = stats["median"]
    index = (price / median).quantize(Decimal("0.001"))
    dispersion = ((stats["p75"] - stats["p25"]) / median * HUNDRED).quantize(CENT)
    band = rules.band / HUNDRED
    position = "above" if index > 1 + band else "below" if index < 1 - band else "inside"
    distance = pct(abs(index - 1) * HUNDRED)
    out.update(price_index=index, dispersion=dispersion, position=position,
               needs_review=dispersion > SPREAD_REVIEW or (out["confidence"] or 0) < WEAK_MATCH)
    has_cost = cost > 0
    floor_note = f" (custo {money(cost)}, margem mínima {pct(rules.min_margin)})" if has_cost else ""

    target, why = None, ""
    if position == "above":
        target = max(median, floor) if has_cost else median
        if target >= price:
            return {**out, "worth_it": False, "reason": (
                f"{distance} acima da mediana do mercado ({money(median)}), mas o menor preço que mantém a margem "
                f"é {money(floor)}{floor_note}: baixar não vale a pena.")}
        why = f"{distance} acima da mediana do mercado ({money(median)})."
    elif position == "below":
        target = max(stats["p25"], floor) if has_cost else stats["p25"]
        if target <= price:
            return {**out, "reason": f"Ótimo preço: {distance} abaixo da mediana ({money(median)}), já é dos mais baratos."}
        why = f"Ótimo preço: {distance} abaixo da mediana ({money(median)}). Dá para subir e continuar entre os mais baratos."
    else:
        if has_cost and floor > price:
            target = min(floor, stats["p75"])
            why = f"No preço do mercado, mas a margem está em {pct(out['current_margin'])}{floor_note}."
        if not target or target <= price:
            note = f" Margem {pct(out['current_margin'])}." if has_cost else ""
            return {**out, "reason": f"No preço do mercado (mediana {money(median)}).{note}"}

    target = target.quantize(CENT)
    new_margin = margin(target, cost) if has_cost else None
    # Subir sempre melhora a margem; baixar só vale se ela continuar acima da mínima.
    worth = (target > price or new_margin >= rules.min_margin) if has_cost else None
    tail = (f" Com {money(target)} a margem vai de {pct(out['current_margin'])} para {pct(new_margin)}."
            if has_cost else " Sem custo cadastrado: confira a margem antes de aprovar.")
    if out["needs_review"]:
        tail += " Mercado espalhado ou pareamento fraco: confira as ofertas."
    return {**out, "suggested_price": target, "suggested_margin": new_margin, "worth_it": worth, "reason": why + tail}
