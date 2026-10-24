"""Volumes (caixas) na operação: carga para frete e conferência por leitura.

O saldo é sempre em UNIDADES da variante. Volume é a parte física: um
guarda-roupa em 3 caixas só conta como 1 unidade recebida/separada quando as
3 caixas foram lidas. Exemplo de conferência com as leituras
[Vol1, Vol2, Vol3, Vol1, Vol2]:

    Vol 1 = 2 caixas, Vol 2 = 2, Vol 3 = 1   ->   1 unidade completa,
    sobram Vol 1 e Vol 2 de uma segunda unidade (falta o Vol 3).
"""
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal

from starrp.services.barcodes import resolve_code

ZERO = Decimal("0")


def _alive_volumes(variant):
    return [v for v in variant.volumes.all() if v.deleted_at is None]


def _units(quantity):
    """Caixas são inteiras: 2,5 unidades de algo que vem em caixa = 3 caixas."""
    return int(Decimal(quantity).to_integral_value(rounding=ROUND_CEILING))


def shipping_totals(lines):
    """Carga de uma lista de (variante, quantidade): caixas, peso bruto (kg) e m³.

    Variante sem volumes cadastrados conta como uma caixa por unidade, com o
    peso e as medidas da própria variante (o que estiver preenchido).
    """
    boxes, weight, cubic = [], ZERO, ZERO
    for variant, quantity in lines:
        units = _units(quantity)
        volumes = _alive_volumes(variant)
        if not volumes:
            boxes.append(_box(variant, None, len(volumes), units))
            weight += (variant.gross_weight or ZERO) * Decimal(quantity)
            cubic += _cubic(variant) * units
            continue
        for volume in volumes:
            boxes.append(_box(variant, volume, len(volumes), units))
            weight += (volume.gross_weight or ZERO) * units
            cubic += volume.cubic_meters * units
    return {
        "boxes": boxes,
        "box_count": sum(box["quantity"] for box in boxes),
        "gross_weight": weight.quantize(Decimal("0.001")),
        "cubic_meters": cubic.quantize(Decimal("0.0001")),
    }


def _box(variant, volume, total, units):
    return {
        "variant": str(variant.pk), "description": variant.display_name, "sku": variant.sku,
        "volume": volume.number if volume else None, "of": total or None,
        "label": f"Vol {volume.number}/{total}" if volume else "",
        "contents": volume.description if volume else "", "barcode": volume.barcode if volume else "",
        "quantity": units,
    }


def _cubic(variant):
    sizes = (variant.height_cm, variant.width_cm, variant.length_cm)
    if None in sizes:
        return ZERO
    return sizes[0] * sizes[1] * sizes[2] / Decimal(1_000_000)


def count_scans(account_id, codes):
    """Leituras -> unidades completas por variante. Código não reconhecido volta em `unknown`.

    Código da variante (EAN/SKU) vale 1 unidade inteira; código de volume vale
    uma caixa, e a unidade fecha quando há uma de cada caixa.
    """
    whole, boxes, found, unknown = defaultdict(int), defaultdict(lambda: defaultdict(int)), {}, []
    for code in codes:
        result = resolve_code(account_id, code)
        if result is None:
            unknown.append(code)
            continue
        found[result.variant.pk] = result.variant
        if result.volume is not None:
            boxes[result.variant.pk][result.volume.number] += 1
        else:
            whole[result.variant.pk] += 1
    counts = {}
    for pk, variant in found.items():
        numbers = [v.number for v in _alive_volumes(variant)]
        read = boxes.get(pk, {})
        complete = min((read.get(n, 0) for n in numbers), default=0) if read else 0
        loose = {n: read.get(n, 0) - complete for n in numbers if read.get(n, 0) - complete > 0}
        counts[pk] = {"variant": variant, "units": whole[pk] + complete, "loose_volumes": loose,
                      "missing_volumes": [n for n in numbers if loose and n not in loose]}
    return counts, unknown


def conference(document, codes):
    """Confere um documento de estoque (recebimento/separação) contra as leituras.

    Devolve uma linha por variante: esperado, contado (unidades completas),
    diferença e as caixas soltas — o que o conferente precisa procurar.
    """
    expected = defaultdict(lambda: ZERO)
    variants = {}
    for item in document.items.filter(deleted_at__isnull=True).select_related("variant__product"):
        expected[item.variant_id] += item.quantity
        variants[item.variant_id] = item.variant
    counts, unknown = count_scans(document.account_id, codes)
    rows = []
    for pk in list(variants) + [pk for pk in counts if pk not in variants]:
        count = counts.get(pk, {})
        variant = variants.get(pk) or count["variant"]
        counted = Decimal(count.get("units", 0))
        rows.append({
            "variant": str(pk), "description": variant.display_name, "sku": variant.sku,
            "expected_quantity": expected[pk], "counted_quantity": counted,
            "difference_quantity": counted - expected[pk],
            "loose_volumes": [f"Vol {n}" for n in sorted(count.get("loose_volumes", {}))],
            "missing_volumes": [f"Vol {n}" for n in count.get("missing_volumes", [])],
            "unexpected": pk not in variants,
        })
    ok = not unknown and all(row["difference_quantity"] == 0 and not row["loose_volumes"] for row in rows)
    return {"document": document.number, "ok": ok, "rows": rows, "unknown_codes": unknown}
