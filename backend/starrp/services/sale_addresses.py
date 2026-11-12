"""Endereços do PEDIDO: entrega e cobrança próprios, herdados do cliente vinculado.

- Ao vincular (ou trocar) o cliente, o pedido copia o endereço padrão dele como ENTREGA e, para a
  COBRANÇA, o mesmo endereço (cliente com "cobrança igual à entrega", o padrão) ou o marcado
  como cobrança. A opção "cobrança igual à entrega" também é herdada.
- Escolher o endereço da entrega (frete) atualiza a entrega do pedido.
- Corrigir no pedido (PDV antes de pagar, retaguarda) muda só o pedido, não o cadastro.
Sem cliente ou sem endereço, o pedido fica sem endereço (nada para confirmar).
"""
from django.db import transaction

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import only_digits
from starrp.models import CustomerAddress, Sale, SaleAddress

FIELDS = ("street", "number", "complement", "district", "city", "city_ibge", "state", "zip_code", "reference")
DELIVERY, BILLING = SaleAddress.Kind.DELIVERY, SaleAddress.Kind.BILLING


def _customer_addresses(customer):
    return list(CustomerAddress.all_objects.filter(customer=customer, deleted_at__isnull=True)
                .order_by("-is_default", "label"))


def _copy(sale, kind, source, user=None):
    """Grava (ou atualiza) o endereço `kind` do pedido a partir de um endereço do cliente."""
    values = {f: getattr(source, f) or "" for f in FIELDS}
    SaleAddress.all_objects.update_or_create(
        sale=sale, kind=kind,
        defaults={**values, "account_id": sale.account_id, "source": source, "recipient": "", "updated_by": user,
                  "deleted_at": None})


@transaction.atomic
def inherit(sale, user=None):
    """Copia do cliente do pedido: entrega = endereço da entrega escolhida ou o padrão; cobrança =
    igual à entrega ou o endereço de cobrança do cliente. Sem cliente: o pedido fica sem endereço."""
    SaleAddress.all_objects.filter(sale=sale).delete()
    customer = sale.customer
    addresses = _customer_addresses(customer) if customer is not None else []
    if not addresses:
        Sale.all_objects.filter(pk=sale.pk).update(billing_same_as_delivery=True)
        sale.billing_same_as_delivery = True
        return
    delivery = next((a for a in addresses if a.pk == sale.shipping_address_id), addresses[0])
    billing = next((a for a in addresses if a.is_billing), None)
    same = customer.billing_same_as_delivery or billing is None or billing.pk == delivery.pk
    _copy(sale, DELIVERY, delivery, user)
    if not same:
        _copy(sale, BILLING, billing, user)
    Sale.all_objects.filter(pk=sale.pk).update(billing_same_as_delivery=same)
    sale.billing_same_as_delivery = same


def follow_delivery(sale, address, user=None):
    """A entrega (frete) foi lançada para `address`: o endereço de entrega do pedido acompanha."""
    _copy(sale, DELIVERY, address, user)


def _clean(data, what):
    data = {f: str((data or {}).get(f) or "").strip() for f in (*FIELDS, "recipient")}
    data["zip_code"] = only_digits(data["zip_code"])
    data["state"] = data["state"].upper()[:2]
    missing = [label for key, label in (("zip_code", "CEP"), ("street", "logradouro"), ("number", "número"),
                                        ("city", "cidade"), ("state", "UF")) if not data[key]]
    if missing:
        raise BusinessError(f"Endereço de {what} incompleto: falta {', '.join(missing)}.", code="address_incomplete")
    if len(data["zip_code"]) != 8:
        raise BusinessError(f"CEP do endereço de {what} tem 8 dígitos.", code="address_zip")
    return data


@transaction.atomic
def save(sale, user, delivery, billing=None, same=True):
    """Correção no pedido: grava a entrega e a cobrança (ou "cobrança igual à entrega")."""
    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    if sale.status == Sale.Status.CANCELLED:
        raise StateConflict("Venda cancelada não muda de endereço.", code="sale_cancelled")
    rows = {DELIVERY: _clean(delivery, "entrega")}
    if not same:
        rows[BILLING] = _clean(billing, "cobrança")
    for kind, values in rows.items():
        current = SaleAddress.all_objects.filter(sale=sale, kind=kind, deleted_at__isnull=True).first()
        source = current.source if current else None
        if source is not None and any((getattr(source, f) or "") != values[f] for f in FIELDS):
            source = None  # corrigido no pedido: não é mais a cópia do cadastro
        SaleAddress.all_objects.update_or_create(
            sale=sale, kind=kind, defaults={**values, "account_id": sale.account_id, "source": source, "updated_by": user,
                                            "deleted_at": None})
    if same:
        SaleAddress.all_objects.filter(sale=sale, kind=BILLING).delete()
    sale.billing_same_as_delivery, sale.updated_by = same, user
    sale.save(update_fields=["billing_same_as_delivery", "updated_by", "updated_at"])
    return sale


def text(address):
    if address is None:
        return ""
    line = ", ".join(filter(None, [address.street, address.number, address.complement]))
    place = " - ".join(filter(None, [address.district, address.city, address.state]))
    zip_code = f"{address.zip_code[:5]}-{address.zip_code[5:]}" if len(address.zip_code or "") == 8 else address.zip_code
    return " · ".join(filter(None, [line, place, zip_code]))


def as_dict(sale):
    """`{delivery, billing, billing_same_as_delivery}`; a cobrança "igual" repete a entrega."""
    rows = {a.kind: a for a in SaleAddress.all_objects.filter(sale=sale, deleted_at__isnull=True)}

    def one(a):
        if a is None:
            return None
        return {**{f: getattr(a, f) for f in FIELDS}, "recipient": a.recipient, "text": text(a),
                "from_customer": a.source_id is not None}

    delivery = one(rows.get(DELIVERY))
    same = sale.billing_same_as_delivery or BILLING not in rows
    return {"delivery": delivery, "billing": delivery if same else one(rows.get(BILLING)),
            "billing_same_as_delivery": same}
