"""Etiquetas: produto/gôndola, lote, endereço (WMS) e volume, em HTML pronto para imprimir.

O HTML usa `@page` no tamanho da etiqueta (mm), e o navegador imprime direto na
térmica (rolo) ou numa folha com várias colunas. Código de barras e QR saem em
SVG: nítidos em qualquer resolução de impressora.

Preço da etiqueta de produto = preço VIGENTE (com promoção, `services.pricing`):
etiqueta de gôndola com preço diferente do caixa é o reclamação mais comum no varejo.
"""
import re
import unicodedata
from dataclasses import dataclass

import barcode
import qrcode
import qrcode.image.svg
from django.utils.html import escape

from starrp.core.text import br_date, brl
from starrp.models import LabelTemplate, ProductVariant, ProductVolume, StockLot, StorageBin
from starrp.services import pricing
from starrp.services.barcodes import ean_check_digit_ok

DEFAULT_FIELDS = {
    LabelTemplate.Subject.PRODUCT: ["name", "price", "barcode", "sku"],
    LabelTemplate.Subject.LOT: ["name", "lot_number", "expires_at", "received_at", "barcode"],
    LabelTemplate.Subject.BIN: ["bin", "warehouse", "barcode"],
    LabelTemplate.Subject.VOLUME: ["name", "volume", "contents", "barcode"],
}


@dataclass
class Label:
    code: str  # o que o leitor vai ler
    values: dict


def _bars(modules, height, guards=()):
    """Barras de uma string de módulos ("1011..."): um <rect> por sequência de 1s. `guards`: módulos que
    descem mais (as guardas do EAN-13, como no padrão GS1)."""
    rects = []
    for run in re.finditer(r"1+", modules):
        tall = any(run.start() <= g < run.end() for g in guards)
        rects.append(f'<rect x="{run.start()}" y="0" width="{len(run.group())}" height="{height + (5 if tall else 0)}"/>')
    return "".join(rects)


def _svg_barcode(code, kind):
    """SVG com viewBox (escala sem perder nitidez nem distorcer): EAN-13 no padrão GS1 (1º dígito fora das
    barras, guardas mais longas), Code 128 com o texto embaixo, ou QR."""
    if kind == LabelTemplate.Code.QR:
        svg = qrcode.make(code, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1).to_string(
            encoding="unicode")
        return svg.replace("<svg ", '<svg shape-rendering="crispEdges" ', 1)
    if kind == LabelTemplate.Code.EAN13 and code.isdigit() and len(code) == 13 and ean_check_digit_ok(code):
        modules = barcode.get("ean13", code[:12]).build()[0]
        left, height = 11, 46  # zona de silêncio GS1: 11 módulos à esquerda, 7 à direita
        digits = (f'<text x="{left - 2}" y="{height + 9}" text-anchor="end">{code[0]}</text>'
                  f'<text x="{left + 24}" y="{height + 9}" text-anchor="middle">{code[1:7]}</text>'
                  f'<text x="{left + 71}" y="{height + 9}" text-anchor="middle">{code[7:]}</text>')
        guards = (0, 2, 46, 48, 92, 94)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {left + 95 + 7} {height + 11}" '
                f'shape-rendering="crispEdges"><g transform="translate({left} 0)">{_bars(modules, height, guards)}'
                f'</g><g font-family="Arial, sans-serif" font-size="10" letter-spacing="1.4">{digits}</g></svg>')
    # Code 128 só tem ASCII: SKU com acento ("CAFÉ") sai sem acento; o que sobrar fora vira QR.
    plain = unicodedata.normalize("NFKD", code).encode("ascii", "ignore").decode()
    if not plain or any(ord(c) > 126 or ord(c) < 32 for c in plain):
        return _svg_barcode(code, LabelTemplate.Code.QR)
    modules = barcode.get("code128", plain).build()[0]
    quiet, width = 10, len(modules) + 20
    height = max(34, round(width * 0.28))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height + 13}" shape-rendering="crispEdges">'
            f'<g transform="translate({quiet} 0)">{_bars(modules, height)}</g>'
            f'<text x="{width / 2}" y="{height + 11}" text-anchor="middle" font-family="Arial, sans-serif" '
            f'font-size="10" letter-spacing="0.6">{escape(plain)}</text></svg>')


def barcode_svg(code):
    """Code 128 em SVG (ex.: a chave de acesso da nota no DANFE)."""
    return _svg_barcode(code, LabelTemplate.Code.CODE128)


def qr_svg(text):
    return _svg_barcode(text, LabelTemplate.Code.QR)


def product_label(variant, store_id=None, received_at=None):
    quote = pricing.quote(variant, store_id)
    primary = variant.barcodes.filter(deleted_at__isnull=True).order_by("-is_primary").first()
    promo = quote.unit_price < quote.list_price
    return Label(primary.code if primary else variant.sku, {
        "name": variant.display_name, "sku": variant.sku, "unit": variant.unit,
        "price": brl(quote.unit_price), "per": f"/{variant.unit.lower()}" if variant.sold_by_weight else "",
        "compare_at": brl(quote.list_price) if promo else "",
        "received_at": br_date(received_at),
    })


def lot_label(lot):
    return Label(lot.code, {
        "name": lot.variant.display_name, "sku": lot.variant.sku, "lot_number": lot.lot_number or lot.code,
        "expires_at": br_date(lot.expires_at), "manufactured_at": br_date(lot.manufactured_at),
        "received_at": br_date(lot.received_at),
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


# Legenda de cada informação nas etiquetas de logística (lote, volume): fica em cima do valor.
CAPTIONS = {"sku": "Código", "lot_number": "Lote", "expires_at": "Validade", "manufactured_at": "Fabricação",
            "received_at": "Entrada", "quantity": "Quantidade", "contents": "Conteúdo"}


def _price_html(label):
    """Preço no padrão de gôndola: "R$" pequeno, reais grandes, centavos em sobrescrito; promoção com o "de"
    riscado. O `aria-label` guarda o preço inteiro (leitor de tela, busca no HTML)."""
    price = label.values["price"]
    reais, _, cents = price.removeprefix("R$ ").partition(",")
    old = label.values.get("compare_at")
    was = f'<div class="was">de <s>{escape(old)}</s> por</div>' if old else ""
    per = f'<span class="per">{escape(label.values["per"])}</span>' if label.values.get("per") else ""
    # --n: dígitos dos reais. O tamanho do preço se ajusta ao espaço livre (largura e altura do bloco).
    return (f'<div class="pricebox{" promo" if old else ""}">{was}'
            f'<div class="price" aria-label="{escape(price)}" style="--n:{len(reais)}">'
            f'<span class="cur">R$</span><span class="int">{escape(reais)}</span>'
            f'<span class="dec">,{escape(cents)}{per}</span></div></div>')


def _cell(label, name):
    value = label.values.get(name)
    return f'<div class="cell"><span>{CAPTIONS[name]}</span><b>{escape(value)}</b></div>' if value else ""


def _render_one(label, template, fields):
    """Um layout por tipo, como os do varejo brasileiro: gôndola (nome em cima, preço grande à direita,
    EAN embaixo), lote/entrada (grade de campos com legenda), endereço (código grande + QR) e volume
    ("VOL 2/3" em destaque). `fields` liga e desliga o que aparece; a posição é do layout."""
    show = set(fields)
    code = f'<div class="code">{_svg_barcode(label.code, template.code_type)}</div>' if "barcode" in show else ""
    flag = f'<div class="flag">{escape(template.custom_text)}</div>' if "custom" in show and template.custom_text else ""
    name = (f'<div class="name">{escape(label.values["name"])}</div>'
            if "name" in show and label.values.get("name") else "")
    subject = template.subject
    if subject == LabelTemplate.Subject.PRODUCT:
        meta = "".join(f"<div>{prefix}{escape(label.values[key])}</div>"
                       for key, prefix in (("sku", "Cód. "), ("received_at", "Entrada "))
                       if key in show and label.values.get(key))
        price = _price_html(label) if "price" in show else ""
        foot = f'<div class="foot">{code}<div class="meta">{meta}</div></div>' if code or meta else ""
        body = f"{flag}{name}{price}{foot}"
    elif subject == LabelTemplate.Subject.BIN:
        detail = f'<div class="detail">{escape(label.values["detail"])}</div>' if label.values.get("detail") else ""
        wh = f'<div class="wh">{escape(label.values["warehouse"])}</div>' if "warehouse" in show else ""
        big = f'<div class="big" style="--n:{len(label.values["bin"])}">{escape(label.values["bin"])}</div>'
        text = f'<div class="bintext">{wh}{big}{detail}</div>'
        qr = template.code_type == LabelTemplate.Code.QR
        body = f'<div class="binrow">{code if qr else ""}{text}</div>{"" if qr else code}'
    elif subject == LabelTemplate.Subject.VOLUME:
        vol = f'<div class="vol">{escape(label.values["volume"])}</div>' if "volume" in show else ""
        cells = "".join(_cell(label, n) for n in ("sku", "contents") if n in show)
        body = f'{flag}<div class="head">{name}{vol}</div><div class="cells">{cells}</div>{code}'
    else:  # lote / entrada
        cells = "".join(_cell(label, n) for n in fields if n in CAPTIONS)
        body = f'{flag}{name}<div class="cells">{cells}</div>{code}'
    shape = (" tall" if template.height_mm > template.width_mm  # tag de roupa: código embaixo, não ao lado
             else " short" if template.height_mm < 30 else "")  # gôndola pequena: nome em 1 linha
    return f'<div class="label"><div class="box {subject}{shape}">{body}</div></div>'


def render(template, labels, extra_fields=()):
    """`labels`: lista de (Label, cópias). Devolve o HTML da página de impressão. `extra_fields`: campos
    que entram mesmo fora do modelo (a etiqueta do lançamento de estoque sempre leva a data de entrada)."""
    fields = list(template.fields or DEFAULT_FIELDS[template.subject])
    if "barcode" in fields:  # o que entra a mais vai antes do código, junto do texto
        at = fields.index("barcode")
        fields[at:at] = [f for f in extra_fields if f not in fields]
    else:
        fields += [f for f in extra_fields if f not in fields]
    width, height, margin = template.width_mm, template.height_mm, template.margin_mm
    body = "".join(_render_one(label, template, fields) for label, copies in labels for _ in range(max(copies, 1)))
    pad = "1" if height < 30 else "1.6"  # gôndola pequena (40×25): menos respiro
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Etiquetas</title><style>
@page {{ size: {width * template.columns}mm {height}mm; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background: #fff; color: #000; color-scheme: light; }}
body {{ font-family: Arial, Helvetica, sans-serif; font-size: {template.font_size_pt}pt; line-height: 1.15;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.sheet {{ display: grid; grid-template-columns: repeat({template.columns}, {width}mm); }}
.label {{ width: {width}mm; height: {height}mm; padding: {margin}mm; overflow: hidden; break-inside: avoid; }}
.box {{ height: 100%; border: .35mm solid #000; border-radius: 1.2mm; overflow: hidden; display: flex;
  flex-direction: column; }}
.box > * {{ padding-left: {pad}mm; padding-right: {pad}mm; }}
.name {{ flex: none; padding-top: .9mm; padding-bottom: .7mm; font-weight: 700; text-transform: uppercase;
  line-height: 1.12; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  border-bottom: .2mm solid #000; }}
.short .name {{ -webkit-line-clamp: 1; padding-top: .5mm; padding-bottom: .4mm; }}
.short .foot {{ flex-basis: 36%; }}
.flag {{ flex: none; background: #000; color: #fff; text-align: center; font-weight: 800; letter-spacing: .14em;
  text-transform: uppercase; padding-top: .5mm; padding-bottom: .5mm; }}
.code {{ flex: 1 1 0; min-height: 0; display: flex; align-items: center; justify-content: center;
  padding-top: .7mm; padding-bottom: .7mm; }}
.code svg {{ display: block; width: 100%; height: 100%; }}
/* Gôndola */
.pricebox {{ flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; justify-content: center;
  align-items: flex-end; container-type: size; }}
.was {{ font-size: min(.85em, 13cqh); white-space: nowrap; }} .was s {{ font-weight: 700; }}
.price {{ display: flex; align-items: flex-start; font-weight: 800; line-height: .85; letter-spacing: -.02em;
  white-space: nowrap; font-size: min(28cqh, calc(92cqw / (var(--n) * 1.8 + 4.6))); }}
.promo .price {{ font-size: min(26cqh, calc(92cqw / (var(--n) * 1.8 + 4.6))); }}
.price .cur {{ font-size: 1.1em; margin: .35em .25em 0 0; }}
.price .int {{ font-size: 3em; }}
.price .dec {{ font-size: 1.6em; display: flex; flex-direction: column; align-items: flex-start; }}
.price .per {{ font-size: .5em; font-weight: 700; margin-top: .25em; letter-spacing: 0; }}
.foot {{ flex: 0 0 40%; min-height: 0; display: flex; gap: 1.4mm; border-top: .2mm solid #000; }}
.foot .code {{ flex: 1 1 auto; padding-left: 0; padding-right: 0; }}
.foot .meta {{ flex: none; display: flex; flex-direction: column; justify-content: center; align-items: flex-end;
  font-size: .78em; white-space: nowrap; }}
.foot .meta:empty {{ display: none; }}
.tall .foot {{ flex-basis: 42%; flex-direction: column; gap: 0; }}
.tall .foot .meta {{ align-items: center; padding-bottom: .6mm; }}
/* Lote, entrada e volume: grade de campos com legenda */
.cells {{ flex: none; display: grid; grid-template-columns: repeat(auto-fit, minmax(15mm, 1fr)); overflow: hidden;
  border-bottom: .2mm solid #000; padding: 0 !important; }}
.cells:empty {{ display: none; }}
.cell {{ min-width: 0; padding: .45mm .9mm; box-shadow: .2mm 0 0 #000, 0 -.2mm 0 #000; }}
.cell span {{ display: block; font-size: .68em; text-transform: uppercase; letter-spacing: .06em; }}
.cell b {{ display: block; font-size: .95em; line-height: 1.05; overflow-wrap: anywhere; }}
.head {{ flex: none; display: flex; padding: 0 !important; border-bottom: .2mm solid #000; }}
.head .name {{ flex: 1; padding-left: {pad}mm; padding-right: {pad}mm; border-bottom: 0; }}
.vol {{ flex: none; display: flex; align-items: center; padding: 0 2mm; background: #000; color: #fff;
  font-weight: 800; font-size: 1.8em; white-space: nowrap; text-transform: uppercase; }}
/* Endereço */
.binrow {{ flex: 1 1 auto; min-height: 0; display: flex; align-items: stretch; gap: 2.5mm; padding-top: 1.5mm;
  padding-bottom: 1.5mm; }}
.binrow .code {{ flex: none; aspect-ratio: 1; padding: 0; }}
.bintext {{ flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center;
  container-type: inline-size; }}
.bintext .big {{ font-size: min(2.6em, calc(100cqw / (var(--n) * .64))); font-weight: 800; line-height: 1;
  white-space: nowrap; }}
.wh, .detail {{ font-size: .7em; text-transform: uppercase; letter-spacing: .08em; }}
.wh {{ padding-bottom: 1mm; margin-bottom: 1.2mm; border-bottom: .2mm solid #000; }}
.detail {{ margin-top: 1.2mm; }}
</style></head><body onload="window.print()"><div class="sheet">{body}</div></body></html>"""


def default_template(account_id, subject):
    """O modelo padrão do tipo (Estoque › Modelos de etiqueta); sem padrão marcado, o 1º ativo."""
    alive = LabelTemplate.all_objects.filter(account_id=account_id, subject=subject, is_active=True,
                                             deleted_at__isnull=True)
    return alive.filter(is_default=True).first() or alive.order_by("-is_system", "name").first()


def labels_for(subject, rows, store_id=None, received_at=None):
    """Monta as etiquetas a partir de [{"id", "copies"}] do tipo `subject`. `received_at`: data de
    entrada impressa na etiqueta de produto (entrada sem lote)."""
    loaders = {
        LabelTemplate.Subject.PRODUCT: (ProductVariant, lambda obj: product_label(obj, store_id, received_at)),
        LabelTemplate.Subject.LOT: (StockLot, lot_label),
        LabelTemplate.Subject.BIN: (StorageBin, bin_label),
        LabelTemplate.Subject.VOLUME: (ProductVolume, volume_label),
    }
    model, build = loaders[subject]
    objects = {str(obj.pk): obj for obj in model.objects.filter(pk__in=[r["id"] for r in rows])}
    return [(build(objects[str(r["id"])]), int(r.get("copies", 1))) for r in rows if str(r["id"]) in objects]


def stage_template(doc, stage, has_lots):
    """Modo e modelo da etapa ("entry" ou "conference") pela regra de logística da filial do documento:
    o modelo escolhido na regra; apagado, desativado ou vazio, o padrão do tipo."""
    from starrp.services import rules

    rule = rules.of_store("logistics_rule", doc.store_id, doc.account_id)
    if stage == "conference":
        mode, template, subject = rule.conference_labels, rule.conference_label, LabelTemplate.Subject.VOLUME
    else:
        mode = rule.entry_labels
        template, subject = ((rule.entry_lot_label, LabelTemplate.Subject.LOT) if has_lots
                             else (rule.entry_product_label, LabelTemplate.Subject.PRODUCT))
    if template is None or template.deleted_at is not None or not template.is_active:
        template = default_template(doc.account_id, subject)
    return mode, template
