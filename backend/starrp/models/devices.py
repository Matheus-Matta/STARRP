"""Periféricos: impressoras, balanças e a fila de impressão.

Sem setor de produção (cozinha/bar): no varejo a impressora é do TERMINAL
(cupom, etiqueta, relatório). A balança perdeu o vínculo com comanda/pedido
ativo; a leitura é entregue ao PDV que a pediu.
"""
import uuid

from django.db import models

from starrp.models.base import QuantityField, StoreModel, user_fk


class Printer(StoreModel):
    class Purpose(models.TextChoices):
        RECEIPT = "receipt", "Cupom / recibo"
        LABEL = "label", "Etiquetas"
        REPORT = "report", "Relatórios (A4)"

    class Driver(models.TextChoices):
        BROWSER = "browser", "Navegador (HTML)"
        ESCPOS = "escpos", "ESC/POS"

    class Connection(models.TextChoices):
        WINDOWS = "windows", "Spooler do Windows"
        NETWORK = "network", "Rede (TCP 9100)"
        SERIAL = "serial", "Serial"
        USB = "usb", "USB"

    name = models.CharField(max_length=120)
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.RECEIPT)
    terminal = models.ForeignKey("starrp.Terminal", null=True, blank=True, related_name="printers", on_delete=models.SET_NULL)
    driver = models.CharField(max_length=10, choices=Driver.choices, default=Driver.ESCPOS)
    connection = models.CharField(max_length=10, choices=Connection.choices, default=Connection.WINDOWS)
    endpoint = models.CharField(max_length=255, blank=True, help_text="Nome da fila, porta COM ou caminho.")
    host = models.GenericIPAddressField(null=True, blank=True)
    port = models.PositiveIntegerField(default=9100)
    paper_width_mm = models.PositiveSmallIntegerField(default=80)
    timeout_seconds = models.PositiveSmallIntegerField(default=10)
    auto_print = models.BooleanField(default=True)
    cash_drawer_enabled = models.BooleanField(default=False)
    cash_drawer_pin = models.PositiveSmallIntegerField(default=0, help_text="0 ou 1 (pino do conector RJ-11).")
    cash_drawer_on_ms = models.PositiveSmallIntegerField(default=120)
    cash_drawer_off_ms = models.PositiveSmallIntegerField(default=240)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Scale(StoreModel):
    class Protocol(models.TextChoices):
        GENERIC = "generic", "Genérico"
        TOLEDO = "toledo", "Toledo"
        FILIZOLA = "filizola", "Filizola"
        URANO = "urano", "Urano"

    name = models.CharField(max_length=120)
    terminal = models.ForeignKey("starrp.Terminal", null=True, blank=True, related_name="scales", on_delete=models.SET_NULL)
    protocol = models.CharField(max_length=10, choices=Protocol.choices, default=Protocol.GENERIC)
    port = models.CharField(max_length=64, blank=True)
    reading_max_age_seconds = models.PositiveSmallIntegerField(default=10)
    # Agente que lê a porta serial: só um por vez (lease).
    agent_instance_id = models.CharField(max_length=120, blank=True)
    agent_lease_expires_at = models.DateTimeField(null=True, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ScaleReading(StoreModel):
    class Source(models.TextChoices):
        AGENT = "agent", "Agente da balança"
        MANUAL = "manual", "Digitado"

    scale = models.ForeignKey(Scale, null=True, blank=True, related_name="readings", on_delete=models.SET_NULL)
    weight_kg = QuantityField(max_digits=9)
    tare_kg = QuantityField(max_digits=9)
    is_stable = models.BooleanField(default=True)
    source = models.CharField(max_length=6, choices=Source.choices, default=Source.AGENT)
    sale_item = models.ForeignKey("starrp.SaleItem", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PrintJob(StoreModel):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Recibo de venda"
        CANCELLATION = "cancellation", "Comprovante de cancelamento"
        RETURN_RECEIPT = "return_receipt", "Comprovante de devolução / vale-troca"
        CASH_CLOSING = "cash_closing", "Fechamento de caixa"
        CASH_MOVEMENT = "cash_movement", "Sangria / suprimento"
        FISCAL = "fiscal", "DANFE NFC-e"
        LABEL = "label", "Etiquetas"

    class Status(models.TextChoices):
        PENDING = "pending", "Na fila"
        CLAIMED = "claimed", "Em impressão"
        PRINTED = "printed", "Impresso"
        FAILED = "failed", "Falhou"
        CANCELLED = "cancelled", "Cancelado"

    serial = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    printer = models.ForeignKey(Printer, null=True, blank=True, related_name="jobs", on_delete=models.SET_NULL)
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    sale = models.ForeignKey("starrp.Sale", null=True, blank=True, related_name="print_jobs", on_delete=models.SET_NULL)
    original_job = models.ForeignKey(
        "self", null=True, blank=True, related_name="reprints", on_delete=models.SET_NULL
    )
    payload = models.JSONField(default=dict, blank=True)
    html_content = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    printed_by = user_fk("+")
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["printer", "status"])]
