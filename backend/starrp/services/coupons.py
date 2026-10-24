"""Regras do cupom. A identidade é o CPF/CNPJ da venda (o mesmo da nota).

Cupom restrito a cliente/grupo exige documento por consequência: sem ele não
existe a quem comparar. O mínimo é sobre produtos, sem frete.
"""
from django.db.models import Q

from starrp.core.errors import CouponRejected
from starrp.models import Coupon, CouponRedemption, Customer, Sale


def find(account_id, code):
    coupon = Coupon.all_objects.filter(
        account_id=account_id, code=(code or "").strip().upper(), deleted_at__isnull=True
    ).first()
    if coupon is None:
        raise CouponRejected("Cupom não encontrado.", code="coupon_not_found")
    return coupon


def _customer_for(sale):
    if sale.customer_id:
        return sale.customer
    if sale.customer_document:
        return Customer.all_objects.filter(
            account_id=sale.account_id, document=sale.customer_document, deleted_at__isnull=True
        ).first()
    return None


def _redemptions(coupon, sale):
    return CouponRedemption.all_objects.filter(coupon=coupon, deleted_at__isnull=True).exclude(sale=sale)


def _check_identity(coupon, sale, customer):
    restricted = coupon.customers.exists() or coupon.customer_groups.exists()
    if (coupon.requires_document or restricted or coupon.usage_limit_per_customer) and not sale.customer_document:
        raise CouponRejected("Este cupom exige CPF/CNPJ na venda.", code="coupon_requires_document")
    if restricted:
        if customer is None:
            raise CouponRejected("Cupom exclusivo para clientes selecionados.")
        allowed = coupon.customers.filter(pk=customer.pk).exists() or customer.groups.filter(
            pk__in=coupon.customer_groups.values("pk")
        ).exists()
        if not allowed:
            raise CouponRejected("Cupom exclusivo para clientes selecionados.")
    if coupon.usage_limit_per_customer:
        used = _redemptions(coupon, sale).filter(document=sale.customer_document).count()
        if used >= coupon.usage_limit_per_customer:
            raise CouponRejected("Este CPF/CNPJ já usou o cupom o máximo de vezes.")
    if coupon.first_purchase_only:
        previous = Sale.all_objects.filter(account_id=sale.account_id, status=Sale.Status.COMPLETED).filter(
            Q(customer_document=sale.customer_document) | Q(customer=customer) if customer else
            Q(customer_document=sale.customer_document)
        ).exclude(pk=sale.pk)
        if previous.exists():
            raise CouponRejected("Cupom válido só na primeira compra.")


def evaluate(coupon, sale, subtotal):
    """Valor que o cupom abate nesta venda, ou `CouponRejected` com o motivo."""
    if not coupon.is_active:
        raise CouponRejected("Cupom fora da validade ou desativado.")
    if coupon.store_id and coupon.store_id != sale.store_id:
        raise CouponRejected("Cupom não vale nesta loja.")
    if coupon.channels and sale.channel not in coupon.channels:
        raise CouponRejected("Cupom não vale neste canal de venda.")
    if subtotal < coupon.min_subtotal:
        raise CouponRejected(f"Cupom exige compra mínima de R$ {coupon.min_subtotal}.")
    if not coupon.combines_with_promotions and sale.items.filter(promotion__isnull=False, status="active").exists():
        raise CouponRejected("Cupom não acumula com produtos em promoção.")
    if coupon.usage_limit and _redemptions(coupon, sale).count() >= coupon.usage_limit:
        raise CouponRejected("Cupom esgotado.")
    _check_identity(coupon, sale, _customer_for(sale))
    return coupon.discount_for(subtotal, sale.freight)


def redeem(sale):
    if not sale.coupon_id:
        return None
    return CouponRedemption.all_objects.create(
        account_id=sale.account_id, coupon_id=sale.coupon_id, sale=sale, customer=_customer_for(sale),
        document=sale.customer_document, amount=sale.coupon_discount,
    )
