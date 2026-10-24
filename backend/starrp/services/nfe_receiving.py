"""NF-e de entrada, parte 2: virar entrada de estoque e contas a pagar.

Custo de compra por item = produtos − desconto + frete + seguro + outras
despesas + IPI + ICMS-ST, dividido pela quantidade JÁ CONVERTIDA para a
unidade de estoque (1 CX de 12 a R$ 24,00 → 12 UN a R$ 2,00).

Fluxo: a nota chega (SEFAZ ou upload) → itens casados pelo EAN → a entrada
nasce em RASCUNHO sozinha (`auto_entry`) → CONFERÊNCIA (o conferente lê os
códigos; a quantidade contada vai para `quantity`, a da nota fica em
`expected_quantity`) → APROVAÇÃO (confirmar move o estoque e gera as contas a
pagar das duplicatas). Divergência fica visível em `InboundNFe.receiving`.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import (
    FinancialTitle, InboundNFe, Installment, StockDocument, StockDocumentItem, SupplierProduct,
)
from starrp.services import numbering, stock
from starrp.services.ledger import category

FOUR = Decimal("0.0001")


def purchase_cost(item):
    taxes = item.tax_data or {}
    extra = Decimal(taxes.get("ipi", "0")) + Decimal(taxes.get("icms_st", "0"))
    return item.total - item.discount + item.freight + item.insurance + item.other_expenses + extra


def _lines(item):
    """Uma linha por lote da nota (rastro); sem rastro, uma linha só."""
    factor = item.conversion_factor
    stock_qty = (item.quantity * factor).quantize(Decimal("0.001"))
    unit_cost = (purchase_cost(item) / stock_qty).quantize(FOUR) if stock_qty else Decimal("0")
    base = {"variant": item.variant, "unit_cost": unit_cost, "nfe_item": item}
    if not item.lots:
        return [{**base, "quantity": stock_qty}]
    lines, remaining = [], stock_qty
    for lot in item.lots:
        qty = min((Decimal(lot["quantity"]) * factor).quantize(Decimal("0.001")), remaining)
        remaining -= qty
        lines.append({**base, "quantity": qty, "lot_number": lot["number"][:60],
                      "manufactured_at": lot["manufactured_at"], "expires_at": lot["expires_at"]})
    if remaining > 0:
        lines.append({**base, "quantity": remaining})
    return lines


def _payables(nfe, user):
    if not nfe.installments or FinancialTitle.all_objects.filter(inbound_nfe=nfe, deleted_at__isnull=True).exists():
        return None
    total = sum(Decimal(dup["amount"]) for dup in nfe.installments)
    title = FinancialTitle.all_objects.create(
        account_id=nfe.account_id, store_id=nfe.store_id, kind=FinancialTitle.Kind.PAYABLE,
        description=f"NF-e {nfe.number} - {nfe.supplier_name}"[:255], supplier=nfe.supplier,
        document_number=nfe.number, issue_date=(nfe.issued_at or timezone.now()).date(), total=total,
        inbound_nfe=nfe, created_by=user, category=category(nfe.account_id, "suppliers"),
    )
    for index, dup in enumerate(nfe.installments, start=1):
        Installment.all_objects.create(
            account_id=nfe.account_id, title=title, number=index, amount=Decimal(dup["amount"]),
            due_date=dup["due_date"] or timezone.localdate(), created_by=user,
        )
    return title


def open_entry(nfe):
    """A entrada viva (rascunho ou confirmada) desta nota, se houver."""
    return StockDocument.all_objects.filter(inbound_nfe=nfe, deleted_at__isnull=True).exclude(
        status=StockDocument.Status.CANCELLED).first()


def auto_entry(nfe, user=None):
    """Nota completa, autorizada e com todos os itens vinculados → entrada em
    rascunho no depósito padrão da loja, pronta para a conferência.
    Desligado nos dados fiscais (`dfe_auto_entry`), a pessoa gera pelo botão."""
    config = nfe.fiscal_config or nfe.store.fiscal_config
    if config is not None and not config.dfe_auto_entry:
        return None
    if (nfe.xml_status != InboundNFe.XmlStatus.AVAILABLE or nfe.ignored_at
            or nfe.fiscal_status in (InboundNFe.FiscalStatus.CANCELLED, InboundNFe.FiscalStatus.DENIED)):
        return None
    items = nfe.items.filter(ignored=False)
    if not items.exists() or items.filter(variant__isnull=True).exists() or open_entry(nfe):
        return None
    warehouse = stock.default_warehouse(nfe.store)
    return build_entry(nfe, warehouse, user) if warehouse else None


@transaction.atomic
def build_entry(nfe, warehouse, user, *, bin=None):
    """Entrada em rascunho a partir da nota. Se já existe um rascunho, devolve ele
    (no depósito pedido): gerar de novo não duplica."""
    nfe = InboundNFe.all_objects.select_for_update().get(pk=nfe.pk)
    if nfe.fiscal_status in (InboundNFe.FiscalStatus.CANCELLED, InboundNFe.FiscalStatus.DENIED):
        raise StateConflict("Nota cancelada/denegada na SEFAZ não entra no estoque.", code="nfe_cancelled")
    if nfe.ignored_at:
        raise StateConflict("Nota marcada como ignorada.")
    if warehouse.store_id != nfe.store_id:
        raise BusinessError("O depósito precisa ser da loja destinatária da nota.")
    existing = open_entry(nfe)
    if existing is not None and existing.status == StockDocument.Status.DRAFT:
        if existing.warehouse_id != warehouse.pk:
            existing.warehouse = warehouse
            existing.save(update_fields=["warehouse", "updated_at"])
        return existing
    if existing is not None:
        raise StateConflict("Esta nota já tem uma entrada de estoque.", code="nfe_already_received")
    items = list(nfe.items.filter(ignored=False).select_related("variant__product"))
    pending = [f"{i.item_number} - {i.description}" for i in items if i.variant_id is None]
    if pending:
        raise BusinessError("Vincule os itens antes de receber: " + "; ".join(pending[:10]), code="nfe_unmapped")
    doc = StockDocument.all_objects.create(
        account_id=nfe.account_id, store_id=nfe.store_id, kind=StockDocument.Kind.ENTRY,
        number=numbering.next_number(nfe.store, "stock_document"), warehouse=warehouse, supplier=nfe.supplier,
        inbound_nfe=nfe, external_number=nfe.number, effective_date=timezone.localdate(),
        reason=f"Entrada da NF-e {nfe.number} série {nfe.series}", created_by=user,
    )
    for item in items:
        for line in _lines(item):
            StockDocumentItem.all_objects.create(
                account_id=nfe.account_id, document=doc, expected_quantity=line["quantity"], bin=bin,
                total_cost=(line["quantity"] * line["unit_cost"]).quantize(Decimal("0.01")), **line,
            )
    return doc


def on_entry_posted(doc):
    """Aprovada a entrada: situação da nota, último custo do fornecedor e as
    duplicatas viram contas a pagar (só agora: rascunho cancelado não deixa conta)."""
    nfe = doc.inbound_nfe
    if nfe.store.account.has_module("finance"):
        _payables(nfe, doc.posted_by)
    rows = list(doc.items.select_related("nfe_item"))
    divergent = any(r.expected_quantity is not None and r.quantity != r.expected_quantity for r in rows)
    nfe.receiving = InboundNFe.Receiving.DIVERGENT if divergent else InboundNFe.Receiving.RECEIVED
    nfe.save(update_fields=["receiving", "updated_at"])
    for row in rows:
        if row.nfe_item and row.nfe_item.supplier_code and nfe.supplier_id:
            SupplierProduct.all_objects.filter(
                supplier_id=nfe.supplier_id, supplier_code=row.nfe_item.supplier_code, deleted_at__isnull=True
            ).update(last_cost=row.unit_cost, last_purchase_at=timezone.now())


def on_entry_cancelled(doc):
    nfe = doc.inbound_nfe
    nfe.receiving = InboundNFe.Receiving.NOT_STARTED
    nfe.save(update_fields=["receiving", "updated_at"])
