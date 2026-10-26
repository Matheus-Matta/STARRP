"""Confirmação e cancelamento de documentos de estoque.

Rascunho pode tudo; confirmado vira imutável e só se desfaz por estorno
(movimento inverso). O documento confirmado é a prova do que moveu.

Entrada de NF-e tem duas etapas antes de mover o estoque:
  1. conferência (`check`): o que foi contado vira a quantidade do item;
  2. aprovação (`post`): só depois da conferência. A diferença conferida (faltou,
     avariado...) entra ajustada e fica registrada em `ReceivingDivergence`.
"""
import uuid
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import (
    BinBalance, ConferenceMode, DivergenceReason, ReceivingDivergence, StockDocument, StockLot, StockMovement,
)
from starrp.services import stock

Kind = StockDocument.Kind
EXIT_KINDS = {
    StockDocument.ExitReason.CONSUMPTION: StockMovement.Kind.CONSUMPTION,
    StockDocument.ExitReason.LOSS: StockMovement.Kind.LOSS,
    StockDocument.ExitReason.EXPIRATION: StockMovement.Kind.EXPIRATION,
}


def _new_lot(item, warehouse, quantity_hint):
    return StockLot.all_objects.create(
        account_id=item.account_id,
        variant=item.variant,
        warehouse=warehouse,
        code=f"L{uuid.uuid4().hex[:8].upper()}",
        lot_number=item.lot_number,
        manufactured_at=item.manufactured_at,
        expires_at=item.expires_at,
        initial_quantity=quantity_hint,
        quantity=Decimal("0"),
        unit_cost=item.unit_cost,
    )


def _entry(item, doc, kind, user):
    lot = None
    if item.variant.track_lots:
        if not item.expires_at and not item.lot_number:
            raise BusinessError(f"{item.variant.display_name} exige lote ou validade na entrada.")
        lot = _new_lot(item, doc.warehouse, item.quantity)
    stock.move(item.variant, doc.warehouse, item.quantity, kind, lot=lot, bin=item.bin, unit_cost=item.unit_cost,
               source_key=f"doc:{item.pk}", document_item=item, operator=user)


def _exit(item, doc, kind, user, warehouse=None):
    return stock.move(item.variant, warehouse or doc.warehouse, -item.quantity, kind, lot=item.lot, bin=item.bin,
                      source_key=f"doc:{item.pk}", document_item=item, operator=user)


def _transfer(item, doc, user):
    if doc.destination_id is None or doc.destination_id == doc.warehouse_id:
        raise BusinessError("Transferência exige um depósito de destino diferente da origem.")
    for index, out in enumerate(_exit(item, doc, StockMovement.Kind.TRANSFER_OUT, user)):
        lot = None
        if out.lot_id:
            lot = _new_lot(item, doc.destination, -out.quantity)
            lot.lot_number, lot.expires_at = out.lot.lot_number, out.lot.expires_at
            lot.save(update_fields=["lot_number", "expires_at"])
        stock.move(item.variant, doc.destination, -out.quantity, StockMovement.Kind.TRANSFER_IN, lot=lot,
                   bin=item.destination_bin, unit_cost=out.unit_cost, source_key=f"doc:{item.pk}:in{index}",
                   document_item=item, operator=user)


def _relocation(item, doc, user):
    """Mesmo depósito, outro endereço: sai de `bin` e entra em `destination_bin`.
    O saldo do depósito não muda; o kardex registra as duas pontas."""
    if not doc.warehouse.uses_bins:
        raise BusinessError("Movimentação entre endereços exige depósito com WMS.")
    if not item.bin or not item.destination_bin or item.bin_id == item.destination_bin_id:
        raise BusinessError(f"{item.variant.display_name}: informe endereço de origem e de destino diferentes.")
    outs = stock.move(item.variant, doc.warehouse, -item.quantity, StockMovement.Kind.RELOCATION, lot=item.lot,
                      bin=item.bin, source_key=f"doc:{item.pk}", document_item=item, operator=user)
    for index, out in enumerate(outs):
        stock.move(item.variant, doc.warehouse, -out.quantity, StockMovement.Kind.RELOCATION, lot=out.lot,
                   bin=item.destination_bin, unit_cost=out.unit_cost, source_key=f"doc:{item.pk}:in{index}",
                   document_item=item, operator=user)


def _check_bins(item, doc):
    """O endereço precisa ser do depósito do documento (o de destino, na transferência)."""
    if item.bin_id and item.bin.warehouse_id != doc.warehouse_id:
        raise BusinessError(f"Endereço {item.bin.code} não pertence ao depósito {doc.warehouse}.")
    target = doc.destination_id if doc.kind == Kind.TRANSFER else doc.warehouse_id
    if item.destination_bin_id and item.destination_bin.warehouse_id != target:
        raise BusinessError(f"Endereço {item.destination_bin.code} não pertence ao depósito de destino.")


def _inventory(item, doc, user):
    """Contagem: grava o saldo do sistema como esperado e move só a diferença.
    Com endereço, a contagem é DAQUELE endereço (e lote, se informado)."""
    if item.bin_id:
        row = BinBalance.all_objects.filter(bin=item.bin, variant=item.variant, lot=item.lot).first()
        current = row.quantity if row else Decimal("0")
    else:
        current = stock.available(item.variant, doc.warehouse)
    item.expected_quantity = current
    item.save(update_fields=["expected_quantity", "updated_at"])
    delta = item.quantity - current
    if delta:
        stock.move(item.variant, doc.warehouse, delta, StockMovement.Kind.ADJUSTMENT, allow_negative=True,
                   lot=item.lot, bin=item.bin, source_key=f"doc:{item.pk}", document_item=item, operator=user)


def _spread(lines, counted):
    """Divide o contado de uma variante entre as linhas dela (lotes), na ordem,
    até o esperado de cada uma; a sobra vai para a última."""
    for index, line in enumerate(lines):
        expected = line.expected_quantity if line.expected_quantity is not None else line.quantity
        line.quantity = counted if index == len(lines) - 1 else min(expected, counted)
        counted -= line.quantity
    return lines


def _manual_allowed(doc):
    from starrp.services import logistics_settings

    if not logistics_settings.for_store(doc.store_id).allow_manual_conference:
        raise BusinessError("A conferência manual está desligada nesta filial (Logística › Configurações de "
                            "logística): leia os códigos.", code="manual_conference_disabled")


def _manual(doc, lines):
    """Conferência manual: cada linha esperada vem marcada `ok` (bateu) ou com a diferença
    (`arrived` chegaram, `accepted` entram no estoque, `reason` obrigatório)."""
    answers = {str(line.get("item")): line for line in lines}
    items = list(doc.items.filter(deleted_at__isnull=True, expected_quantity__isnull=False))
    missing = [i.variant.display_name for i in items if str(i.pk) not in answers]
    if missing:
        raise BusinessError("Marque todos os itens: " + ", ".join(missing[:10]), code="conference_incomplete")
    for item in items:
        line = answers[str(item.pk)]
        if line.get("ok"):
            item.quantity = item.arrived_quantity = item.expected_quantity
            item.divergence_reason, item.divergence_notes = "", ""
        else:
            reason = str(line.get("reason") or "")
            if reason not in DivergenceReason.values:
                raise BusinessError(f"Informe o motivo da diferença em {item.variant.display_name}.",
                                    code="divergence_reason_required")
            try:
                arrived, accepted = Decimal(str(line["arrived"])), Decimal(str(line["accepted"]))
            except (KeyError, InvalidOperation):
                raise BusinessError(f"Informe quantos chegaram e quantos entram em {item.variant.display_name}.",
                                    code="divergence_quantity_required") from None
            if arrived < 0 or accepted < 0:
                raise BusinessError("Quantidade não pode ser negativa.")
            item.arrived_quantity, item.quantity = arrived, accepted
            item.divergence_reason, item.divergence_notes = reason, str(line.get("notes") or "")[:255]
        item.total_cost = (item.quantity * (item.unit_cost or 0)).quantize(Decimal("0.01"))
        item.save(update_fields=["quantity", "arrived_quantity", "divergence_reason", "divergence_notes",
                                 "total_cost", "updated_at"])


@transaction.atomic
def check(document, user, codes=None, lines=None):
    """Conclui a conferência.
    - `codes` (leituras do coletor/câmera): o contado de cada produto vira a quantidade
      das linhas dele. Código desconhecido ou produto fora do documento barra.
    - `lines` (conferência manual, se a Logística permitir): item a item, correto ou
      com a diferença (motivo, quantos chegaram, quantos entram).
    - nenhum dos dois: vale o que está digitado no documento (na entrada de NF-e, só
      com a conferência manual permitida)."""
    from starrp.services import volumes

    doc = StockDocument.all_objects.select_for_update().get(pk=document.pk)
    if doc.status != StockDocument.Status.DRAFT:
        raise StateConflict("Só rascunho pode ser conferido.")
    if lines is not None:
        _manual_allowed(doc)
        _manual(doc, lines)
        mode = ConferenceMode.MANUAL
    elif codes is None:
        if doc.inbound_nfe_id:
            _manual_allowed(doc)
        mode = ConferenceMode.TYPED
    else:
        mode = ConferenceMode.SCAN
    if codes is not None:
        result = volumes.conference(doc, codes)
        if result["unknown_codes"]:
            raise BusinessError("Códigos não encontrados: " + ", ".join(result["unknown_codes"][:10]),
                                code="conference_unknown")
        extra = [row["description"] for row in result["rows"] if row["unexpected"]]
        if extra:
            raise BusinessError("Produtos fora do documento: " + ", ".join(extra[:10]), code="conference_unexpected")
        counted = {row["variant"]: row["counted_quantity"] for row in result["rows"]}
        lines = {}
        for item in doc.items.filter(deleted_at__isnull=True).order_by("created_at"):
            lines.setdefault(str(item.variant_id), []).append(item)
        for variant, group in lines.items():
            for line in _spread(group, counted.get(variant, Decimal("0"))):
                line.total_cost = (line.quantity * (line.unit_cost or 0)).quantize(Decimal("0.01"))
                line.arrived_quantity = line.quantity
                line.divergence_reason = _auto_reason(line)
                line.save(update_fields=["quantity", "arrived_quantity", "divergence_reason", "total_cost",
                                         "updated_at"])
    doc.conference_mode, doc.checked_at, doc.checked_by = mode, timezone.now(), user
    doc.save(update_fields=["conference_mode", "checked_at", "checked_by", "updated_at"])
    return doc


def _auto_reason(line):
    if line.expected_quantity is None or line.quantity == line.expected_quantity:
        return ""
    return DivergenceReason.MISSING if line.quantity < line.expected_quantity else DivergenceReason.EXTRA


def _register_divergences(doc, items, user):
    """Aprovou com diferença: cada linha vira um registro de erro de entrada."""
    for item in items:
        if item.expected_quantity is None:
            continue
        arrived = item.arrived_quantity if item.arrived_quantity is not None else item.quantity
        if item.quantity == item.expected_quantity and arrived == item.expected_quantity:
            continue
        ReceivingDivergence.all_objects.create(
            account_id=doc.account_id, store_id=doc.store_id, document=doc, document_item=item,
            inbound_nfe_id=doc.inbound_nfe_id, supplier_id=doc.supplier_id, variant_id=item.variant_id,
            expected_quantity=item.expected_quantity, arrived_quantity=arrived, accepted_quantity=item.quantity,
            reason=item.divergence_reason or _auto_reason(item) or DivergenceReason.OTHER,
            notes=item.divergence_notes, mode=doc.conference_mode, checked_by=doc.checked_by or user,
            created_by=user,
        )


@transaction.atomic
def post(document, user):
    doc = StockDocument.all_objects.select_for_update().get(pk=document.pk)
    if doc.status != StockDocument.Status.DRAFT:
        raise StateConflict("Só rascunho pode ser confirmado.")
    if doc.inbound_nfe_id and doc.checked_at is None:
        raise BusinessError("Conclua a conferência antes de aprovar a entrada da nota.", code="conference_required")
    items = list(doc.items.select_related("variant__product", "lot", "bin", "destination_bin"))
    if not items:
        raise BusinessError("O documento não tem itens.")
    for item in items:
        _check_bins(item, doc)
        if doc.kind == Kind.RELOCATION:
            _relocation(item, doc, user)
        elif doc.kind == Kind.ENTRY:
            _entry(item, doc, StockMovement.Kind.PURCHASE, user)
        elif doc.kind == Kind.EXIT:
            _exit(item, doc, EXIT_KINDS.get(doc.exit_reason, StockMovement.Kind.CONSUMPTION), user)
        elif doc.kind == Kind.SUPPLIER_RETURN:
            _exit(item, doc, StockMovement.Kind.SUPPLIER_RETURN, user)
        elif doc.kind == Kind.TRANSFER:
            _transfer(item, doc, user)
        elif doc.kind == Kind.ADJUSTMENT:
            stock.move(item.variant, doc.warehouse, item.quantity, StockMovement.Kind.ADJUSTMENT,
                       allow_negative=True, source_key=f"doc:{item.pk}", document_item=item, operator=user)
        elif doc.kind == Kind.INVENTORY:
            _inventory(item, doc, user)
    _register_divergences(doc, items, user)
    doc.status, doc.posted_at, doc.posted_by = StockDocument.Status.POSTED, timezone.now(), user
    doc.save(update_fields=["status", "posted_at", "posted_by", "updated_at"])
    if doc.inbound_nfe_id:
        from starrp.services.nfe_receiving import on_entry_posted

        on_entry_posted(doc)
    return doc


@transaction.atomic
def cancel(document, user, reason=""):
    doc = StockDocument.all_objects.select_for_update().get(pk=document.pk)
    if doc.status == StockDocument.Status.CANCELLED:
        raise StateConflict("Documento já cancelado.")
    if doc.status == StockDocument.Status.POSTED:
        movements = StockMovement.all_objects.filter(document_item__document=doc, reversal_of__isnull=True)
        for movement in movements.exclude(kind=StockMovement.Kind.REVERSAL):
            stock.reverse(movement, operator=user, reason=reason or f"Cancelamento do documento {doc.number}")
    was_posted = doc.status == StockDocument.Status.POSTED
    # Desfeito o lançamento, o erro de entrada dele deixa de valer (a nova aprovação registra de novo).
    doc.divergences.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
    doc.status, doc.cancelled_at, doc.cancelled_by = StockDocument.Status.CANCELLED, timezone.now(), user
    doc.save(update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"])
    if doc.inbound_nfe_id and was_posted:
        from starrp.services.nfe_receiving import on_entry_cancelled

        on_entry_cancelled(doc)
    return doc
