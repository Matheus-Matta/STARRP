"""Regras que as filiais COMPARTILHAM: operação (PDV, caixa, venda), logística e estoque.

Cada conta nasce com uma regra PADRÃO de cada tipo (`services/rules.ensure_defaults`) e
toda filial aponta para uma regra de cada tipo (`Store.rule`, `Store.logistics_rule`,
`Store.stock_rule`). Filial nova (ou sem escolha) fica com a padrão; várias filiais usam
a mesma regra e a filial que trabalha diferente aponta para outra.

Validadores (o sistema nunca fica sem regra):
- uma padrão por conta: marcar outra como padrão desmarca a anterior; desmarcar a padrão
  sem outra no lugar é recusado;
- a padrão, a última regra e a regra em uso por alguma filial não se excluem.
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction

from starrp.core.errors import BusinessError, StateConflict
from starrp.models.base import MoneyField, TenantModel, alive


class SharedRule(TenantModel):
    """Base das regras compartilhadas. `STORE_FIELD`: a FK de `Store` que aponta para ela."""

    STORE_FIELD = None
    KIND_LABEL = "regra"

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False, help_text="Filial nova (ou sem escolha) fica com esta.")

    class Meta:
        abstract = True
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    def _siblings(self):
        return type(self).all_objects.filter(account_id=self.account_id, deleted_at__isnull=True).exclude(pk=self.pk)

    def save(self, *args, **kwargs):
        if self.deleted_at is not None:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            siblings = self._siblings()
            was_default = bool(self.pk) and type(self).all_objects.filter(pk=self.pk, is_default=True).exists()
            if was_default and not self.is_default:
                raise BusinessError(
                    f"Sempre existe uma {self.KIND_LABEL} padrão: marque outra como padrão em vez de desmarcar esta.",
                    code="rule_default_required")
            if not siblings.filter(is_default=True).exists():
                self.is_default = True  # a primeira da conta é sempre a padrão
            if self.is_default:
                siblings.filter(is_default=True).update(is_default=False)
            return super().save(*args, **kwargs)

    def stores_using(self):
        from starrp.models.company import Store

        return Store.all_objects.filter(**{self.STORE_FIELD: self}, deleted_at__isnull=True)

    def check_deletable(self):
        if self.is_default:
            raise StateConflict(f"A {self.KIND_LABEL} padrão não pode ser excluída: marque outra como padrão antes.",
                                code="rule_is_default")
        if not self._siblings().exists():
            raise StateConflict(f"É a única {self.KIND_LABEL}: o sistema precisa de pelo menos uma.",
                                code="rule_last")
        using = list(self.stores_using().values_list("name", flat=True)[:4])
        if using:
            more = "…" if self.stores_using().count() > 4 else ""
            raise StateConflict(f"Em uso pelas filiais {', '.join(using)}{more}: troque a regra delas antes de excluir.",
                                code="rule_in_use")

    def delete(self, using=None, keep_parents=False):
        self.check_deletable()
        return super().delete(using=using, keep_parents=keep_parents)


def _rule_constraints(prefix):
    return [
        models.UniqueConstraint(fields=["account", "name"], condition=alive(), name=f"uniq_{prefix}_name"),
        models.UniqueConstraint(fields=["account"], condition=alive(is_default=True), name=f"uniq_{prefix}_default"),
    ]


class StoreRule(SharedRule):
    """Como a filial opera: PDV, caixa e venda."""

    STORE_FIELD = "rule"
    KIND_LABEL = "regra da filial"

    class ScaleBarcode(models.TextChoices):
        DISABLED = "", "Não usa etiqueta de balança"
        PRICE = "price", "Etiqueta traz o preço"
        WEIGHT = "weight", "Etiqueta traz o peso"

    # Caixa
    require_open_cash_session = models.BooleanField(default=True)
    # Diferença de gaveta que o fechamento aceita sem gerente (moeda caída).
    cash_closing_tolerance = MoneyField(max_digits=8, default=Decimal("0.50"))
    # Caixa parado: a tela do PDV se bloqueia sozinha (volta com a senha do operador).
    pdv_auto_lock = models.BooleanField(default=True, help_text="Bloqueia a tela do caixa parado.")
    pdv_lock_minutes = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(120)], help_text="Minutos parado até bloquear.")

    # Venda
    require_seller = models.BooleanField(default=False, help_text="Exige vendedor em toda venda.")
    auto_print_receipt = models.BooleanField(default=True)
    confirm_address_at_checkout = models.BooleanField(
        default=True, help_text="No PDV, antes de pagar, confirma o endereço de entrega e de cobrança do pedido.")
    ask_print_danfe = models.BooleanField(default=False)
    # Cartão/PIX: o campo do NSU/autorização aparece sempre; obrigatório só com isto ligado.
    require_payment_reference = models.BooleanField(
        default=False, help_text="Só lança cartão/PIX com o NSU/autorização do comprovante.")
    print_cancellation_receipt = models.BooleanField(default=False)
    # Etiqueta de balança (EAN-13 iniciado em 2): PLU + preço ou peso.
    scale_barcode_mode = models.CharField(max_length=10, choices=ScaleBarcode.choices, blank=True)
    scale_barcode_prefix = models.CharField(max_length=2, default="2")

    class Meta(SharedRule.Meta):
        constraints = _rule_constraints("store_rule")


class LogisticsRule(SharedRule):
    """Como a filial recebe e confere mercadoria."""

    STORE_FIELD = "logistics_rule"
    KIND_LABEL = "regra de logística"

    # Conferir o recebimento marcando item a item (correto / incorreto) em vez de ler cada
    # código. Desligado, a entrada da NF-e só é conferida pela leitura (leitor ou câmera).
    allow_manual_conference = models.BooleanField(
        default=False, help_text="Permite conferir o recebimento manualmente, sem ler os códigos.")

    # Etiquetas de cada etapa do recebimento: o modelo já vem escolhido (os pré-prontos do sistema)
    # e "imprime sozinho" não pergunta nada. Modelo vazio = o padrão do tipo em Modelos de etiqueta.
    class LabelPrint(models.TextChoices):
        AUTO = "auto", "Imprime sozinho"
        ASK = "ask", "Pergunta o modelo"
        OFF = "off", "Não imprime"

    entry_labels = models.CharField(max_length=4, choices=LabelPrint.choices, default=LabelPrint.AUTO,
                                    help_text="Ao confirmar ou aprovar a entrada.")
    entry_lot_label = models.ForeignKey(
        "starrp.LabelTemplate", null=True, blank=True, related_name="+", on_delete=models.SET_NULL,
        help_text="Entrada que gera lote (validade ou data de entrada).")
    entry_product_label = models.ForeignKey(
        "starrp.LabelTemplate", null=True, blank=True, related_name="+", on_delete=models.SET_NULL,
        help_text="Entrada sem lote: etiqueta de produto, uma por unidade.")
    conference_labels = models.CharField(max_length=4, choices=LabelPrint.choices, default=LabelPrint.AUTO,
                                         help_text="Ao concluir a conferência do recebimento.")
    conference_label = models.ForeignKey(
        "starrp.LabelTemplate", null=True, blank=True, related_name="+", on_delete=models.SET_NULL,
        help_text="Caixa (volume) ou produto, para identificar o que chegou.")

    # Campo → tipo de etiqueta aceito (o serializer recusa outro; o padrão do sistema preenche).
    LABEL_SUBJECTS = {"entry_lot_label": ("lot",), "entry_product_label": ("product",),
                      "conference_label": ("volume", "product")}

    class Meta(SharedRule.Meta):
        constraints = _rule_constraints("logistics_rule")

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.fill_label_defaults()
        return super().save(*args, **kwargs)

    def fill_label_defaults(self):
        """Modelo vazio ganha o pré-pronto padrão do tipo (lote, produto, volume). Devolve se mudou algo."""
        from starrp.services.labels import default_template

        changed = False
        for field, subjects in self.LABEL_SUBJECTS.items():
            if getattr(self, f"{field}_id") is None:
                template = default_template(self.account_id, subjects[0])
                if template is not None:
                    setattr(self, field, template)
                    changed = True
        return changed


class StockRule(SharedRule):
    """Política de estoque: ordem de saída dos lotes, vencidos e saldo negativo."""

    STORE_FIELD = "stock_rule"
    KIND_LABEL = "regra de estoque"

    class Picking(models.TextChoices):
        FIFO = "fifo", "FIFO - primeiro a entrar"
        FEFO = "fefo", "FEFO - primeiro a vencer"

    picking_strategy = models.CharField(max_length=4, choices=Picking.choices, default=Picking.FEFO)
    expiry_warning_days = models.PositiveSmallIntegerField(default=7)
    block_expired = models.BooleanField(default=True)
    allow_negative_stock = models.BooleanField(default=False)
    # Produto SEM validade também ganha um lote por entrada (com a data de entrada) e a saída tira
    # do mais antigo primeiro: o item não fica esquecido no fundo do estoque.
    fifo_by_entry = models.BooleanField(
        default=True, help_text="Sem validade: guarda a data de entrada e dá saída no mais antigo primeiro.")

    class Meta(SharedRule.Meta):
        constraints = _rule_constraints("stock_rule")
