"""Venda aberta: criar, lançar/alterar/cancelar itens, descontos, cupom e totais.

Toda escrita trava a venda (`select_for_update`) e relê o estado depois do
lock. Totais são recalculados aqui e só aqui. Pagamento e conclusão ficam em
`services.checkout`.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from starrp.core.errors import BusinessError, CouponRejected, StateConflict
from starrp.models import Sale, SaleChannel, SaleItem
from starrp.services import coupons, numbering, pricing
from starrp.services.approvals import authorize, authorize_discount

CENTS = Decimal("0.01")


def cents(value):
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def lock_open(sale):
    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.OPEN:
        raise StateConflict("A venda não está aberta.", code="sale_locked")
    return sale


@transaction.atomic
def park(sale, user, note=""):
    """Guarda o pedido para terminar depois (ou para o caixa cobrar).

    Só pedido com itens e SEM pagamento: dinheiro já lançado não fica "solto" num
    pedido parado — conclua a venda ou estorne o pagamento antes.
    """
    sale = lock_open(sale)
    if not sale.items.filter(status=SaleItem.Status.ACTIVE).exists():
        raise BusinessError("Pedido vazio não é guardado: lance ao menos um item.", code="sale_empty")
    if sale.paid_amount > 0:
        raise StateConflict("Este pedido já tem pagamento lançado: conclua a venda ou estorne o pagamento.",
                            code="sale_has_payment")
    sale.status, sale.parked_at, sale.parked_by = Sale.Status.DRAFT, timezone.now(), user
    if note:
        sale.notes = f"{sale.notes}\n{note}".strip()
    sale.save(update_fields=["status", "parked_at", "parked_by", "notes", "updated_at"])
    return sale


@transaction.atomic
def resume(sale, user, cash_session=None):
    """Retoma um pedido guardado: volta a ser a venda aberta de quem retomou (no turno dele)."""
    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.DRAFT:
        raise StateConflict("Este pedido não está guardado (já foi retomado, concluído ou cancelado).",
                            code="sale_not_draft")
    sale.status, sale.operator, sale.updated_by = Sale.Status.OPEN, user, user
    if cash_session is not None:
        sale.cash_session = cash_session
    sale.save(update_fields=["status", "operator", "cash_session", "updated_by", "updated_at"])
    return sale


@transaction.atomic
def create(store, user, *, channel=SaleChannel.POS, terminal=None, seller=None, customer=None,
           customer_document="", customer_name="", cash_session=None):
    return Sale.all_objects.create(
        account_id=store.account_id,
        store=store,
        number=numbering.next_number(store, "sale"),
        channel=channel,
        terminal=terminal,
        cash_session=cash_session,
        operator=user,
        seller=seller,
        customer=customer,
        customer_document=customer_document or (customer.document if customer else ""),
        customer_name=customer_name or (customer.name if customer else ""),
        created_by=user,
    )


def _check_sellable(variant):
    product = variant.product
    for row in (product, variant):
        if not row.is_active or row.deleted_at is not None:
            raise BusinessError(f"{variant.display_name} está inativo.", code="product_inactive")


def _discount_percent(discount, gross):
    return (Decimal(discount) / gross * 100) if gross else Decimal("0")


@transaction.atomic
def add_item(sale, variant, quantity, user, *, seller=None, discount=Decimal("0"), unit_price=None,
             approval=None, metafields=None, parent_item=None):
    sale = lock_open(sale)
    _check_sellable(variant)
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise BusinessError("Quantidade precisa ser maior que zero.")
    quote = pricing.quote(variant, sale.store_id)
    price = quote.unit_price
    if parent_item is not None:
        # Serviço do item: o preço é o da regra (não é "alterar preço", não pede gerente).
        price = _service_price(sale, variant, parent_item)
        unit_price = None
    elif unit_price is not None and Decimal(unit_price) != price:
        authorize(user, sale.account, sale.store, "sales.price_override", approval)
        price = Decimal(unit_price)
    gross = cents(quantity * price)
    if discount:
        authorize_discount(user, sale.account, sale.store, _discount_percent(discount, gross), approval)
    position = (sale.items.aggregate(m=Max("position"))["m"] or 0) + 1
    item = SaleItem.all_objects.create(
        account_id=sale.account_id,
        sale=sale,
        position=position,
        variant=variant,
        description=variant.display_name,
        sku=variant.sku,
        unit=variant.unit,
        quantity=quantity,
        list_price=quote.list_price,
        unit_price=price,
        discount=cents(discount),
        total=max(gross - cents(discount), Decimal("0")),
        unit_cost=unit_cost_of(variant),
        promotion=quote.promotion if unit_price is None else None,
        seller=seller,
        metafields=metafields or {},
        parent_item=parent_item,
        created_by=user,
    )
    recalculate(sale)
    return item


def _service_price(sale, variant, parent):
    from starrp.services.service_rules import price_for

    if parent.sale_id != sale.pk or not parent.is_active or parent.parent_item_id:
        raise BusinessError("O serviço precisa ir num item ativo desta venda.", code="service_parent_invalid")
    if variant.product.type != variant.product.Type.SERVICE:
        raise BusinessError(f"{variant.display_name} não é um serviço.", code="not_a_service")
    if parent.services.filter(variant=variant, status=SaleItem.Status.ACTIVE).exists():
        raise StateConflict(f"{variant.display_name} já está neste item.", code="service_duplicated")
    price = price_for(variant, parent.variant.product)
    if price is None:
        raise BusinessError(f"{variant.display_name} não é oferecido para {parent.description}.",
                            code="service_not_offered")
    return price


@transaction.atomic
def update_item(item, user, *, quantity=None, discount=None, approval=None):
    sale = lock_open(item.sale)
    item = SaleItem.all_objects.select_for_update().get(pk=item.pk)
    if not item.is_active:
        raise StateConflict("Item cancelado não pode ser alterado.")
    if quantity is not None:
        if Decimal(quantity) <= 0:
            raise BusinessError("Quantidade precisa ser maior que zero.")
        item.quantity = Decimal(quantity)
    gross = cents(item.quantity * item.unit_price)
    if discount is not None:
        authorize_discount(user, sale.account, sale.store, _discount_percent(discount, gross), approval)
        item.discount = cents(discount)
    item.total = max(gross - item.discount, Decimal("0"))
    item.updated_by = user
    item.save()
    if quantity is not None:  # 2 guarda-roupas = 2 montagens: o serviço acompanha o item
        for service in item.services.filter(status=SaleItem.Status.ACTIVE):
            service.quantity = item.quantity
            service.total = max(cents(service.quantity * service.unit_price) - service.discount, Decimal("0"))
            service.save(update_fields=["quantity", "total", "updated_at"])
    recalculate(sale)
    return item


@transaction.atomic
def cancel_item(item, user, reason="", approval=None):
    sale = lock_open(item.sale)
    item = SaleItem.all_objects.select_for_update().get(pk=item.pk)
    if not item.is_active:
        raise StateConflict("Item já cancelado.")
    authorize(user, sale.account, sale.store, "sales.cancel_item", approval)
    item.status, item.cancelled_at, item.cancelled_by, item.cancel_reason = (
        SaleItem.Status.CANCELLED, timezone.now(), user, reason
    )
    item.save()
    # Saiu o produto, saem os serviços dele (montagem sem o guarda-roupa não existe).
    item.services.filter(status=SaleItem.Status.ACTIVE).update(
        status=SaleItem.Status.CANCELLED, cancelled_at=item.cancelled_at, cancelled_by=user,
        cancel_reason=f"Item {item.position} removido: {reason}".strip(": "))
    recalculate(sale)
    return item


FLOW = ["pending", "ready", "shipped", "delivered"]
STEP_FIELDS = {"ready": "ready", "shipped": "shipped", "delivered": "delivered"}


@transaction.atomic
def advance_fulfillment(sale, user, to, note=""):
    """Entrega da venda concluída: pendente → separado → saiu para entrega → entregue.

    Pular etapa preenche as do meio (entregou direto = separou e saiu). Voltar só uma
    etapa por vez e com motivo (marcou "Entregue" por engano); o motivo vai no histórico.
    """
    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.COMPLETED:
        raise StateConflict("A entrega anda depois que a venda é concluída no caixa.", code="sale_not_completed")
    if not sale.shipping_address_id:
        raise BusinessError("Esta venda é de retirada na loja: não tem entrega para acompanhar.", code="no_delivery")
    if to not in FLOW or sale.fulfillment_status not in FLOW:
        raise StateConflict(f"A entrega está '{sale.get_fulfillment_status_display()}' e não muda por aqui.",
                            code="fulfillment_locked")
    current, target = FLOW.index(sale.fulfillment_status), FLOW.index(to)
    if target == current:
        raise StateConflict(f"A entrega já está '{sale.get_fulfillment_status_display()}'.", code="fulfillment_same")
    if target < current:
        if target != current - 1 or not note.strip():
            raise BusinessError("Para voltar a entrega, volte uma etapa e diga o motivo.", code="fulfillment_back")
        for step in FLOW[target + 1:]:
            if step in STEP_FIELDS:
                setattr(sale, f"{STEP_FIELDS[step]}_at", None)
                setattr(sale, f"{STEP_FIELDS[step]}_by", None)
    else:
        now = timezone.now()
        for step in FLOW[current + 1:target + 1]:
            if step in STEP_FIELDS and getattr(sale, f"{STEP_FIELDS[step]}_at") is None:
                setattr(sale, f"{STEP_FIELDS[step]}_at", now)
                setattr(sale, f"{STEP_FIELDS[step]}_by", user)
    sale.fulfillment_status, sale.updated_by = to, user
    sale._change_reason = note.strip()  # simple_history: aparece como nota no histórico
    sale.save()
    return sale


DELIVERY_KEY = "_entrega"  # metacampo do sistema (prefixo "_": a tela de metacampos não edita)


@transaction.atomic
def set_delivery(sale, user, address, table):
    """Entrega no endereço do cliente pela tabela escolhida: o frete entra no total."""
    from starrp.services import freight

    sale = lock_open(sale)
    if sale.customer_id is None:
        raise BusinessError("Identifique o cliente antes de lançar a entrega.", code="customer_required")
    if address.customer_id != sale.customer_id:
        raise BusinessError("Esse endereço não é do cliente da venda.", code="address_mismatch")
    try:
        found = freight.quote(table, address.zip_code)
    except freight.FreightUnavailable as error:
        raise BusinessError(str(error), code="freight_unavailable") from error
    sale.shipping_address, sale.freight = address, found.value
    sale.metafields = {**(sale.metafields or {}), DELIVERY_KEY: {
        "table": str(table.pk), "table_name": table.name, "lead_days": found.lead_days,
        "distance_km": None if found.distance_km is None else str(found.distance_km), "detail": found.detail,
        "zip_code": address.zip_code, "address_label": address.label}}
    sale.updated_by = user
    sale.save(update_fields=["shipping_address", "freight", "metafields", "updated_by", "updated_at"])
    return recalculate(sale)


@transaction.atomic
def clear_delivery(sale, user):
    """Volta para retirada na loja: sem endereço e sem frete."""
    sale = lock_open(sale)
    sale.shipping_address, sale.freight = None, Decimal("0")
    sale.metafields = {k: v for k, v in (sale.metafields or {}).items() if k != DELIVERY_KEY}
    sale.updated_by = user
    sale.save(update_fields=["shipping_address", "freight", "metafields", "updated_by", "updated_at"])
    return recalculate(sale)


@transaction.atomic
def set_metafields(sale, user, values):
    """Metacampos do pedido (os do sistema, com "_", ficam como estão)."""
    from starrp.services import metafields

    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    clean = metafields.clean(sale.account_id, "sale", {k: v for k, v in (values or {}).items() if not k.startswith("_")})
    system = {k: v for k, v in (sale.metafields or {}).items() if k.startswith("_")}
    sale.metafields, sale.updated_by = {**system, **clean}, user
    sale.save(update_fields=["metafields", "updated_by", "updated_at"])
    return sale


@transaction.atomic
def set_discount(sale, user, amount, approval=None):
    sale = lock_open(sale)
    amount = cents(amount)
    approver = authorize_discount(user, sale.account, sale.store, _discount_percent(amount, sale.subtotal), approval)
    sale.discount = amount
    sale.discount_approved_by = approver if amount else None
    sale.save(update_fields=["discount", "discount_approved_by", "updated_at"])
    return recalculate(sale)


@transaction.atomic
def apply_coupon(sale, code):
    sale = lock_open(sale)
    coupon = coupons.find(sale.account_id, code)
    sale.coupon_discount = coupons.evaluate(coupon, sale, sale.subtotal)
    sale.coupon, sale.coupon_code = coupon, coupon.code
    sale.save(update_fields=["coupon", "coupon_code", "coupon_discount", "updated_at"])
    return recalculate(sale)


@transaction.atomic
def remove_coupon(sale):
    sale = lock_open(sale)
    sale.coupon, sale.coupon_code, sale.coupon_discount = None, "", Decimal("0")
    sale.save(update_fields=["coupon", "coupon_code", "coupon_discount", "updated_at"])
    return recalculate(sale)


def recalculate(sale):
    """Subtotal, cupom (reavaliado: sai se a venda deixou de se qualificar) e total."""
    subtotal = sale.items.filter(status=SaleItem.Status.ACTIVE).aggregate(t=Sum("total"))["t"] or Decimal("0")
    sale.subtotal = cents(subtotal)
    if sale.coupon_id:
        try:
            sale.coupon_discount = coupons.evaluate(sale.coupon, sale, sale.subtotal)
        except CouponRejected:
            sale.coupon, sale.coupon_code, sale.coupon_discount = None, "", Decimal("0")
    sale.discount = min(sale.discount, sale.subtotal)
    sale.total = max(sale.subtotal - sale.discount - sale.coupon_discount + sale.freight, Decimal("0"))
    sale.save(update_fields=["subtotal", "discount", "coupon", "coupon_code", "coupon_discount", "total",
                             "updated_at"])
    return sale


def unit_cost_of(variant):
    """Custo para o CMV. Kit não tem estoque próprio: custa a soma dos componentes."""
    if not variant.is_kit:
        return variant.average_cost
    components = variant.product.components.filter(deleted_at__isnull=True).select_related("component")
    return sum((c.component.average_cost * c.quantity for c in components), Decimal("0"))


def net_unit_price(item):
    """Preço pago por unidade com os descontos do cabeçalho rateados: é a base
    da devolução e da comissão (o cliente não recebe de volta o que não pagou)."""
    sale = item.sale
    header = sale.discount + sale.coupon_discount
    share = (item.total / sale.subtotal * header) if sale.subtotal else Decimal("0")
    return cents((item.total - share) / item.quantity) if item.quantity else Decimal("0")

