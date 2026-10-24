"""Caixa: o caixa físico, a sessão (turno) e as movimentações.

Nomes corrigidos: no StarChef o caixa físico era `CashStation` e a SESSÃO se
chamava `CashRegister`. Aqui `CashRegister` é o caixa e `CashSession` o turno.
Abertura e fechamento são campos da sessão — não movimentos duplicados.
O esperado em gaveta = abertura + movimentos aprovados em dinheiro.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from starrp.models.base import MoneyField, StoreModel, alive, user_fk

FINAL_SESSION_STATUSES = ("closed", "cancelled")


class CashRegister(StoreModel):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40)
    operators = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="cash_registers")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["store", "code"], condition=alive(), name="uniq_cash_register_code"),
        ]

    def __str__(self):
        return f"{self.store} - {self.name}"


class CashSession(StoreModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        PENDING_APPROVAL = "pending_approval", "Aguardando aprovação do gerente"
        CLOSED = "closed", "Fechado"
        CANCELLED = "cancelled", "Cancelado"

    register = models.ForeignKey(CashRegister, related_name="sessions", on_delete=models.PROTECT)
    terminal = models.ForeignKey("starrp.Terminal", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    # Retrato do nome do terminal: renomeá-lo não reescreve a auditoria.
    terminal_label = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="cash_sessions_opened", on_delete=models.PROTECT)
    opened_at = models.DateTimeField(auto_now_add=True)
    opening_amount = MoneyField()
    closed_by = user_fk("cash_sessions_closed")
    closed_at = models.DateTimeField(null=True, blank=True)
    expected_amount = MoneyField(help_text="Calculado no fechamento.")
    counted_amount = MoneyField(null=True, blank=True, default=None, help_text="Contado pelo operador.")
    difference = MoneyField(help_text="Contado - esperado.")
    closing_report = models.JSONField(default=dict, blank=True, help_text="Totais por forma de pagamento.")
    approved_by = user_fk("+")
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            # A trava real: duas aberturas simultâneas leem "livre" antes de
            # gravar; só o índice parcial decide sem corrida.
            models.UniqueConstraint(
                fields=["register"],
                condition=Q(deleted_at__isnull=True) & ~Q(status__in=FINAL_SESSION_STATUSES),
                name="uniq_active_session_per_register",
            ),
        ]

    def __str__(self):
        return f"Caixa {self.register} {self.opened_at:%d/%m/%Y %H:%M}"

    @property
    def is_finished(self):
        return self.status in FINAL_SESSION_STATUSES


class CashMovement(StoreModel):
    class Kind(models.TextChoices):
        SALE = "sale", "Venda em dinheiro"
        WITHDRAWAL = "withdrawal", "Sangria"
        SUPPLY = "supply", "Suprimento"
        REFUND = "refund", "Devolução em dinheiro"
        ADJUSTMENT = "adjustment", "Ajuste"

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando aprovação"
        APPROVED = "approved", "Aprovado"
        CANCELLED = "cancelled", "Cancelado"

    # Sinal de cada tipo na gaveta. O valor é sempre gravado positivo.
    SIGN = {Kind.SALE: 1, Kind.SUPPLY: 1, Kind.WITHDRAWAL: -1, Kind.REFUND: -1, Kind.ADJUSTMENT: 1}

    session = models.ForeignKey(CashSession, related_name="movements", on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)
    amount = MoneyField()
    payment = models.ForeignKey("starrp.Payment", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    sale_return = models.ForeignKey(
        "starrp.SaleReturn", null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="cash_movements", on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPROVED, db_index=True)
    approved_by = user_fk("+")
    approved_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    destination = models.CharField(max_length=255, blank=True, help_text="Para onde foi a sangria.")

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["session", "kind", "status"])]

    @property
    def signed_amount(self):
        return self.amount * self.SIGN.get(self.kind, 1)


class CashDiscrepancy(StoreModel):
    """Dinheiro que entrou sem venda registrada (pico de movimento).

    Registro ADMINISTRATIVO, separado de venda e nota: não se emite NFC-e de
    venda que não existiu para "fechar" o caixa. A regularização é do contador.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        REVIEWED = "reviewed", "Analisada"
        REGULARIZED = "regularized", "Regularizada"
        CANCELLED = "cancelled", "Cancelada"

    session = models.ForeignKey(CashSession, related_name="discrepancies", on_delete=models.PROTECT)
    amount = MoneyField()
    by_payment_method = models.JSONField(default=list, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolved_by = user_fk("+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
