"""Etiquetas: produto/gôndola, lote, endereço (WMS) e volume, em HTML pronto para imprimir.

O HTML usa `@page` no tamanho da etiqueta (mm), e o navegador imprime direto na
térmica (rolo) ou numa folha com várias colunas. Código de barras e QR saem em
SVG: nítidos em qualquer resolução de impressora.

Preço da etiqueta de produto = preço VIGENTE (com promoção, `services.pricing`):
etiqueta de gôndola com preço diferente do caixa é o reclamação mais comum no varejo.
"""
import io
from dataclasses import dataclass
from decimal import Decimal

import barcode
import qrcode
import qrcode.image.svg
from barcode.writer import SVGWriter
from django.utils.html import escape

from starrp.core.text import br_date, brl
from starrp.models import LabelTemplate, ProductVariant, ProductVolume, StockLot, StorageBin
from starrp.services import pricing
from starrp.services.barcodes import ean_check_digit_ok

DEFAULT_FIELDS = {
    LabelTemplate.Subject.PRODUCT: ["name", "price", "barcode", "sku"],
    LabelTemplate.Subject.LOT: ["name", "lot_number", "expires_at", "barcode"],
    LabelTemplate.Subject.BIN: ["bin", "warehouse", "barcode"],
    LabelTemplate.Subject.VOLUME: ["name", "volume", "contents", "barcode"],
}


@dataclass
class Label:
    code: str  # o que o leitor vai ler
    values: dict


def _svg_barcode(code, kind):
    if kind == LabelTemplate.Code.QR:
        return qrcode.make(code, image_factory=qrcode.image.svg.SvgPathImage, box_size=10).to_string(
            encoding="unicode")
    use_ean = kind == LabelTemplate.Code.EAN13 and code.isdigit() and len(code) == 13 and ean_check_digit_ok(code)
    out = io.BytesIO()
    symbology = barcode.get("ean13", code[:12], writer=SVGWriter()) if use_ean else barcode.get(
        "code128", code, writer=SVGWriter())
    symbology.write(out, options={"write_text": True, "module_height": 8, "font_size": 6, "text_distance": 3,
                                  "quiet_zone": 2})
    svg = out.getvalue().decode("utf-8")
    return svg[svg.index("<svg"):]  # sem o cabeçalho XML: vai embutido no HTML


def product_label(variant, store_id=None):
    quote = pricing.quote(variant, store_id)
    primary = variant.barcodes.filter(deleted_at__isnull=True).order_by("-is_primary").first()
    promo = quote.unit_price < quote.list_price
    return Label(primary.code if primary else variant.sku, {
        "name": variant.display_name, "sku": variant.sku, "unit": variant.unit,
        "price": brl(quote.unit_price) + (f"/{variant.unit.lower()}" if variant.sold_by_weight else ""),
        "compare_at": brl(quote.list_price) if promo else "",
    })


def lot_label(lot):
    return Label(lot.code, {
        "name": lot.variant.display_name, "sku": lot.variant.sku, "lot_number": lot.lot_number or lot.code,
        "expires_at": br_date(lot.expires_at), "manufactured_at": br_date(lot.manufactured_at),
        "quantity": f"{lot.initial_quantity.normalize()} {lot.variant.unit}",
    })


def bin_label(bin):
    return Label(bin.code, {"bin": bin.code, "warehouse": bin.warehouse.name,
                            "detail": " · ".join(p for p in (bin.aisle, bin.rack, bin.level) if p)})


def volume_label(volume):
    """Caixa "Vol 2/3": sem código próprio, a etiqueta usa SKU + número da caixa."""
    total = volume.variant.volumes.filter(deleted_at__isnull=True).count()
    return Label(volume.barcode or f"{volume.variant.sku}-V{volume.number}", {
        "name": volume.variant.display_name, "sku": volume.variant.sku,
        "volume": f"Vol {volume.number}/{total}", "contents": volume.description,
    })


LABELS = {"name": "", "sku": "SKU ", "lot_number": "Lote ", "expires_at": "Val. ", "manufactured_at": "Fab. ",
          "quantity": "", "warehouse": "", "detail": "", "unit": "", "contents": ""}


def _render_one(label, template, fields):
    parts = []
    for name in fields:
        if name == "barcode":
            parts.append(f'<div class="code">{_svg_barcode(label.code, template.code_type)}</div>')
        elif name == "price":
            old = label.values.get("compare_at")
            parts.append(f'<div class="price">{f"<s>{escape(old)}</s> " if old else ""}{escape(label.values["price"])}</div>')
        elif name in ("bin", "volume"):
            parts.append(f'<div class="bin">{escape(label.values[name])}</div>')
        elif name == "custom":
            parts.append(f'<div class="small">{escape(template.custom_text)}</div>')
        elif label.values.get(name):
            parts.append(f'<div class="{"name" if name == "name" else "small"}">'
                         f'{LABELS.get(name, "")}{escape(label.values[name])}</div>')
    return f'<div class="label">{"".join(parts)}</div>'


def render(template, labels):
    """`labels`: lista de (Label, cópias). Devolve o HTML da página de impressão."""
    fields = template.fields or DEFAULT_FIELDS[template.subject]
    width, height, margin = template.width_mm, template.height_mm, template.margin_mm
    body = "".join(_render_one(label, template, fields) for label, copies in labels for _ in range(max(copies, 1)))
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Etiquetas</title><style>
@page {{ size: {width * template.columns}mm {height}mm; margin: 0; }}
body {{ margin: 0; font-family: Arial, sans-serif; font-size: {template.font_size_pt}pt; }}
.sheet {{ display: grid; grid-template-columns: repeat({template.columns}, {width}mm); }}
.label {{ width: {width}mm; height: {height}mm; padding: {margin}mm; box-sizing: border-box; overflow: hidden;
  display: flex; flex-direction: column; justify-content: space-between; page-break-inside: avoid; }}
.name {{ font-weight: bold; line-height: 1.1; max-height: 2.3em; overflow: hidden; }}
.price {{ font-size: 2em; font-weight: bold; }} .price s {{ font-size: .5em; font-weight: normal; }}
.bin {{ font-size: 2.4em; font-weight: bold; text-align: center; }}
.small {{ font-size: .85em; }} .code svg {{ width: 100%; height: auto; max-height: {(height * Decimal("0.45")).quantize(Decimal("0.1"))}mm; }}
</style></head><body onload="window.print()"><div class="sheet">{body}</div></body></html>"""


def labels_for(subject, rows, store_id=None):
    """Monta as etiquetas a partir de [{"id", "copies"}] do tipo `subject`."""
    loaders = {
        LabelTemplate.Subject.PRODUCT: (ProductVariant, lambda obj: product_label(obj, store_id)),
        LabelTemplate.Subject.LOT: (StockLot, lot_label),
        LabelTemplate.Subject.BIN: (StorageBin, bin_label),
        LabelTemplate.Subject.VOLUME: (ProductVolume, volume_label),
    }
    model, build = loaders[subject]
    objects = {str(obj.pk): obj for obj in model.objects.filter(pk__in=[r["id"] for r in rows])}
    return [(build(objects[str(r["id"])]), int(r.get("copies", 1))) for r in rows if str(r["id"]) in objects]
