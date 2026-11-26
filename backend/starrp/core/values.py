"""Valores soltos vindos do cliente fora de um serializer (fila offline, ações com corpo livre).

O formato errado vira recusa clara (422) ou "não achou", nunca erro 500: um 500 na fila do PDV é reenviado para sempre.
"""
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from starrp.core.errors import BusinessError


def user_pk(value):
    """Id de usuário (inteiro); o que não é id não acha ninguém (0)."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    text = str(value)
    return int(text) if text.isascii() and text.isdigit() and len(text) < 15 else 0


def moment(value):
    """Data e hora com fuso, ou None."""
    try:
        when = parse_datetime(str(value or ""))
        if when is not None and timezone.is_naive(when):
            when = timezone.make_aware(when)
    except (ValueError, OverflowError):  # "2026-99-99T00:00:00Z"
        return None
    return when


def money(value):
    """Número finito, nunca negativo e que cabe no banco."""
    try:
        number = Decimal(str(0 if value in (None, "") else value))
    except InvalidOperation:
        raise BusinessError("Valor inválido.", code="invalid_number") from None
    if not number.is_finite() or number < 0 or number > Decimal("1e11"):
        raise BusinessError("Valor inválido.", code="invalid_number")
    return number
