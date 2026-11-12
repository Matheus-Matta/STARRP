"""A pesquisa da equipe: preços de concorrentes informados na tela ou por planilha.

Planilha: uma linha por preço, com colunas produto (SKU ou código de barras), concorrente e preço;
data e link são opcionais. A linha com problema é devolvida com o motivo e as outras entram.
Cada preço salvo recalcula o processo do produto sem consultar nenhuma fonte externa.
"""
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.models import CompetitorPrice, ProductBarcode, ProductVariant
from starrp.services.cosmos.attachments import AttachmentError, parse
from starrp.services.market import tracker

PRODUCT = {"sku", "produto", "codigo", "codigo de barras", "gtin", "ean"}
COMPETITOR = {"concorrente", "loja", "site"}
PRICE = {"preco", "valor", "preco do concorrente"}
DAY = {"data", "dia"}
LINK = {"link", "url"}
ERRORS_SHOWN = 50


def _plain(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def _column(columns, names):
    return next((i for i, name in enumerate(columns) if _plain(name) in names), None)


def _money(value):
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        text = str(value).replace("R$", "").strip()
        if "," in text:  # 1.234,56
            text = text.replace(".", "").replace(",", ".")
        number = Decimal(text)
    if number <= 0:
        raise InvalidOperation
    return number.quantize(Decimal("0.01"))


def _day(value):
    if value in (None, ""):
        return timezone.localdate()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError


def _variant(account, code):
    code = str(code).strip()
    variant = ProductVariant.all_objects.filter(account=account, sku__iexact=code, deleted_at__isnull=True).first()
    if variant:
        return variant
    barcode = (ProductBarcode.all_objects.filter(account=account, code=code, deleted_at__isnull=True)
               .select_related("variant").first())
    return barcode.variant if barcode and barcode.variant.deleted_at is None else None


def recalculate(variants):
    """Refaz a conta destes produtos com os preços da equipe (conta com o rastreamento ligado)."""
    for variant in variants:
        if variant.account.price_tracking_enabled:
            tracker.check_variant(variant, fresh={"manual"})


def import_sheet(account, user, name, raw):
    try:
        sheet = parse(name, raw)
    except AttachmentError as error:
        raise BusinessError(str(error), code="price_sheet_invalid") from error
    columns = sheet["columns"]
    product, competitor, price = (_column(columns, PRODUCT), _column(columns, COMPETITOR), _column(columns, PRICE))
    if product is None or competitor is None or price is None:
        raise BusinessError("A planilha precisa das colunas: produto (SKU ou código de barras), concorrente e preço.",
                            code="price_sheet_columns")
    day, link = _column(columns, DAY), _column(columns, LINK)
    touched, created, errors = {}, 0, []
    for number, row in enumerate(sheet["rows"], start=2):
        variant = _variant(account, row[product])
        if variant is None:
            errors.append({"linha": number, "erro": f"Produto não encontrado: {row[product]}"})
            continue
        if not str(row[competitor]).strip():
            errors.append({"linha": number, "erro": "Falta o concorrente."})
            continue
        try:
            value = _money(row[price])
        except (InvalidOperation, ValueError):
            errors.append({"linha": number, "erro": f"Preço inválido: {row[price]}"})
            continue
        try:
            seen = _day(row[day]) if day is not None else timezone.localdate()
        except ValueError:
            errors.append({"linha": number, "erro": f"Data inválida: {row[day]}"})
            continue
        CompetitorPrice.all_objects.create(
            account=account, variant=variant, competitor=str(row[competitor]).strip()[:120], price=value,
            observed_on=seen, url=str(row[link]).strip()[:500] if link is not None else "", created_by=user)
        touched[variant.pk] = variant
        created += 1
    recalculate(touched.values())
    return {"imported": created, "products": len(touched), "errors": errors[:ERRORS_SHOWN], "error_count": len(errors)}
