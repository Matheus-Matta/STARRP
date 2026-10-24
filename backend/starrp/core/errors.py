"""Erros de domínio que o CLIENTE precisa reconhecer pelo `code`.

Regra: 400 = entrada errada (o PDV corrige e reenvia); 409 = conflito de
estado (reenviar o mesmo corpo nunca resolve); 422 = regra de negócio recusou.
Um conflito devolvido como 400 vira laço infinito na fila do PDV.
"""
from rest_framework import status
from rest_framework.exceptions import APIException


class BusinessError(APIException):
    """Regra de negócio recusou a operação (o corpo está correto)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "A operação não é permitida pelas regras do sistema."
    default_code = "business_rule"

    def __init__(self, detail=None, code=None):
        super().__init__(detail=detail, code=code or self.default_code)


class StateConflict(BusinessError):
    """O estado atual do registro impede a operação (venda já concluída...)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflito com o estado atual do registro."
    default_code = "conflict"


class LimitReached(StateConflict):
    default_detail = "Limite do plano atingido."
    default_code = "limit_reached"


class ApprovalRequired(BusinessError):
    """Precisa de autorização de um superior (desconto acima do limite...)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Esta operação exige autorização de um gerente."
    default_code = "approval_required"


class CouponRejected(BusinessError):
    default_detail = "Este cupom não pode ser aplicado a esta venda."
    default_code = "coupon_rejected"


class InsufficientStock(BusinessError):
    default_detail = "Estoque insuficiente."
    default_code = "insufficient_stock"
