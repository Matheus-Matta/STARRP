"""NF-e de entrada, parte 1: importar o XML e casar os itens com os produtos.

Casamento automático, nesta ordem:
  1. o que o operador já confirmou antes para este fornecedor (`SupplierProduct`);
  2. o EAN comercial da nota (`cEAN`) num código de barras do produto → fator 1;
  3. o EAN tributável (`cEANTrib`, a unidade) → fator = qTrib / qCom
     (a nota vende "1 CX" e tributa "12 UN": entram 12 no estoque).
O que o operador confirma vira `SupplierProduct` e casa sozinho na próxima nota.

Voltar passos: desvincular / voltar a usar um item, descartar a conferência
(rascunho da entrada) e desfazer o recebimento (estorna o estoque e cancela as
contas a pagar). Mexer num vínculo com a conferência aberta descarta o rascunho
(ele não moveu estoque) e a entrada nasce de novo com os itens certos.
"""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import only_digits
from starrp.models import InboundNFe, InboundNFeItem, ProductBarcode, Supplier, SupplierProduct
from starrp.services import catalog, nfe_xml

ADDRESS = ("street", "number", "district", "city", "city_ibge", "state", "zip_code")


def _supplier(account_id, emitter):
    document = only_digits(emitter["document"])
    supplier = Supplier.all_objects.filter(account_id=account_id, document=document, deleted_at__isnull=True).first()
    if supplier is None:
        supplier = Supplier.all_objects.create(
            account_id=account_id, person_type="J" if len(document) == 14 else "F", document=document,
            name=emitter["name"][:180] or document, legal_name=emitter["legal_name"][:180],
            state_registration=emitter["state_registration"][:20], phone=emitter["phone"][:32],
            **{k: (emitter[k] or "")[:Supplier._meta.get_field(k).max_length] for k in ADDRESS},
        )
    return supplier


def _recipient_ok(store, config, recipient):
    """A nota tem que ser para o CNPJ da loja ou dos dados fiscais dela."""
    accepted = {only_digits(store.cnpj), only_digits(config.cnpj) if config else ""} - {""}
    return not accepted or not recipient or recipient in accepted


@transaction.atomic
def import_xml(store, content, user, *, config=None, nsu=""):
    """XML completo da nota (upload ou SEFAZ). Se a nota já existe só como resumo
    (veio da distribuição antes da ciência), completa ela em vez de duplicar."""
    data = nfe_xml.parse(content)
    if len(data.access_key) != 44:
        raise BusinessError("Chave de acesso inválida no XML.", code="nfe_invalid")
    config = config or store.fiscal_config
    if not _recipient_ok(store, config, data.recipient_document):
        raise BusinessError(f"Esta nota é para o CNPJ {data.recipient_document}, não para a filial {store.name}.",
                            code="nfe_other_recipient")
    existing = InboundNFe.all_objects.select_for_update().filter(
        account_id=store.account_id, access_key=data.access_key, deleted_at__isnull=True).first()
    if existing is not None and existing.xml_status == InboundNFe.XmlStatus.AVAILABLE:
        raise StateConflict(f"Esta nota já foi importada (NF-e {existing.number}).", code="nfe_duplicate")
    supplier = _supplier(store.account_id, data.emitter)
    fields = {
        "number": data.number, "series": data.series, "issued_at": data.issued_at, "supplier": supplier,
        "supplier_document": only_digits(data.emitter["document"]), "supplier_name": data.emitter["name"][:180],
        "recipient_document": data.recipient_document, "products_total": data.products_total, "total": data.total,
        "xml_status": InboundNFe.XmlStatus.AVAILABLE, "full_xml": content.decode("utf-8", errors="replace"),
        "installments": data.installments, "fiscal_config": config,
    }
    if existing is not None:
        nfe = existing
        for name, value in fields.items():
            setattr(nfe, name, value)
        if data.status_code == "100" and nfe.fiscal_status == InboundNFe.FiscalStatus.UNKNOWN:
            nfe.fiscal_status = InboundNFe.FiscalStatus.AUTHORIZED
        nfe.save()
    else:
        try:
            nfe = InboundNFe.all_objects.create(
                account_id=store.account_id, store=store, access_key=data.access_key, nsu=nsu, created_by=user,
                fiscal_status=InboundNFe.FiscalStatus.AUTHORIZED if data.status_code == "100" else
                InboundNFe.FiscalStatus.UNKNOWN, **fields,
            )
        except IntegrityError:
            raise StateConflict("Esta nota já foi importada.", code="nfe_duplicate") from None
    for item in data.items:
        InboundNFeItem.all_objects.create(
            account_id=store.account_id, nfe=nfe, item_number=item.number, supplier_code=item.supplier_code,
            barcode=item.barcode, taxable_barcode=item.taxable_barcode, description=item.description,
            ncm=item.ncm, cest=item.cest, cfop=item.cfop, unit=item.unit, quantity=item.quantity,
            unit_value=item.unit_value, taxable_unit=item.taxable_unit, taxable_quantity=item.taxable_quantity,
            taxable_unit_value=item.taxable_unit_value, total=item.total, discount=item.discount,
            freight=item.freight, insurance=item.insurance, other_expenses=item.other_expenses,
            tax_data=item.taxes, lots=item.lots,
        )
    auto_match(nfe)
    _entry_when_ready(nfe, user)
    return nfe


def _by_barcode(account_id, code):
    if not code:
        return None
    found = ProductBarcode.all_objects.filter(account_id=account_id, code=code, deleted_at__isnull=True).select_related(
        "variant").first()
    return found.variant if found else None


def match_item(item, supplier):
    """(variante, fator) para um item da nota, ou (None, 1) se não casou."""
    link = SupplierProduct.all_objects.filter(
        supplier=supplier, supplier_code=item.supplier_code, deleted_at__isnull=True, confirmed=True
    ).select_related("variant").first() if supplier and item.supplier_code else None
    if link is not None:
        return link.variant, link.conversion_factor
    variant = _by_barcode(item.account_id, item.barcode)
    if variant is not None:
        return variant, Decimal("1")
    variant = _by_barcode(item.account_id, item.taxable_barcode)
    if variant is not None and item.quantity:
        return variant, (item.taxable_quantity / item.quantity).quantize(Decimal("0.000001"))
    return None, Decimal("1")


def auto_match(nfe):
    matched = 0
    for item in nfe.items.filter(variant__isnull=True, ignored=False):
        variant, factor = match_item(item, nfe.supplier)
        if variant is not None:
            item.variant, item.conversion_factor = variant, factor
            item.save(update_fields=["variant", "conversion_factor", "updated_at"])
            matched += 1
    return matched


def _received(nfe):
    return nfe.receiving in (InboundNFe.Receiving.RECEIVED, InboundNFe.Receiving.DIVERGENT)


def _editable(nfe, user):
    """Vínculos só mudam antes do recebimento; a conferência aberta é descartada."""
    if _received(nfe):
        raise StateConflict("Nota já recebida: desfaça o recebimento para mexer nos itens.",
                            code="nfe_already_received")
    discard_entry(nfe, user, quiet=True)


@transaction.atomic
def map_item(item, variant, factor, user):
    """O operador confirma o vínculo: grava no item e APRENDE para a próxima nota."""
    factor = Decimal(factor)
    if factor <= 0:
        raise BusinessError("O fator de conversão precisa ser maior que zero.")
    _editable(item.nfe, user)
    item.variant, item.conversion_factor, item.ignored = variant, factor, False
    item.save(update_fields=["variant", "conversion_factor", "ignored", "updated_at"])
    supplier = item.nfe.supplier
    if supplier and item.supplier_code:
        SupplierProduct.all_objects.update_or_create(
            supplier=supplier, supplier_code=item.supplier_code, deleted_at=None,
            defaults={"account_id": item.account_id, "variant": variant, "conversion_factor": factor,
                      "supplier_barcode": item.barcode, "supplier_description": item.description[:255],
                      "purchase_unit": item.unit, "confirmed": True, "updated_by": user},
        )
    _entry_when_ready(item.nfe, user)
    return item


@transaction.atomic
def product_from_item(item, user, *, price=None):
    """Cadastra o produto simples a partir do item da nota (nome, NCM, CEST, EAN) e vincula.
    Devolve a variante (a única, a padrão)."""
    sku = f"{only_digits(item.nfe.supplier_document)[-4:]}-{item.supplier_code}"[:60]
    code = item.taxable_barcode or item.barcode
    variant = catalog.create_simple(
        item.account_id, user, name=item.description[:180], sku=sku, price=Decimal(price or 0),
        barcodes=[code] if code else [], ncm=item.ncm, cest=item.cest,
    )
    factor = (item.taxable_quantity / item.quantity) if item.taxable_barcode and item.quantity else Decimal("1")
    map_item(item, variant, factor, user)
    return variant


def _entry_when_ready(nfe, user):
    """Vinculou o último item pendente: a entrada já nasce para conferência."""
    from starrp.services.nfe_receiving import auto_entry

    auto_entry(nfe, user)


@transaction.atomic
def ignore_item(item, reason, user=None):
    _editable(item.nfe, user)
    item.ignored, item.ignored_reason, item.variant = True, reason[:255], None
    item.save(update_fields=["ignored", "ignored_reason", "variant", "updated_at"])
    _entry_when_ready(item.nfe, user)
    return item


@transaction.atomic
def unignore_item(item, user=None):
    """Item ignorado volta a entrar no estoque (e tenta casar sozinho de novo)."""
    _editable(item.nfe, user)
    item.ignored, item.ignored_reason = False, ""
    item.variant, item.conversion_factor = match_item(item, item.nfe.supplier)
    item.save(update_fields=["ignored", "ignored_reason", "variant", "conversion_factor", "updated_at"])
    _entry_when_ready(item.nfe, user)
    return item


@transaction.atomic
def unmap_item(item, user=None, *, forget=True):
    """Desfaz o vínculo do item. `forget`: o vínculo aprendido com o fornecedor também
    sai, para a próxima nota não casar errado de novo."""
    _editable(item.nfe, user)
    supplier = item.nfe.supplier
    if forget and supplier and item.supplier_code and item.variant_id:
        SupplierProduct.all_objects.filter(supplier=supplier, supplier_code=item.supplier_code,
                                           variant_id=item.variant_id, deleted_at__isnull=True).update(
            confirmed=False, updated_at=timezone.now())
    item.variant, item.conversion_factor = None, Decimal("1")
    item.save(update_fields=["variant", "conversion_factor", "updated_at"])
    return item


@transaction.atomic
def discard_entry(nfe, user, *, quiet=False):
    """Volta da conferência para os vínculos: cancela a entrada em RASCUNHO (não moveu estoque)."""
    from starrp.models import StockDocument
    from starrp.services import stock_documents
    from starrp.services.nfe_receiving import open_entry

    doc = open_entry(nfe)
    if doc is None or doc.status != StockDocument.Status.DRAFT:
        if quiet:
            return None
        raise StateConflict("Esta nota não tem conferência em andamento.", code="nfe_no_draft")
    return stock_documents.cancel(doc, user, "Conferência descartada: vínculos da nota em revisão")


@transaction.atomic
def undo_receipt(nfe, user, reason):
    """Desfaz o recebimento: cancela a entrada aprovada (cada movimento ganha um estorno)
    e as contas a pagar da nota. A nota volta para "gerar entrada"."""
    from starrp.models import StockDocument
    from starrp.services import stock_documents
    from starrp.services.nfe_receiving import open_entry

    if len(reason.strip()) < 5:
        raise BusinessError("Explique por que o recebimento está sendo desfeito.", code="reason_required")
    doc = open_entry(nfe)
    if doc is None or doc.status != StockDocument.Status.POSTED:
        raise StateConflict("Esta nota não foi recebida.", code="nfe_not_received")
    return stock_documents.cancel(doc, user, f"Recebimento da NF-e {nfe.number} desfeito: {reason.strip()}")


def restore(nfe):
    """Nota ignorada volta para o fluxo."""
    nfe.ignored_at, nfe.ignored_by, nfe.ignored_reason = None, None, ""
    nfe.save(update_fields=["ignored_at", "ignored_by", "ignored_reason", "updated_at"])
    return nfe

