"""A loja e os terminais (PDVs) dela.

`Store` substitui o par `Restaurant` + `Branch`, que repetiam CNPJ, endereço e
configurações de caixa ("campos espelhados"). Os dados do emitente (CNPJ, IE,
regime, certificado) ficam em `FiscalConfig` ("Dados fiscais"), cadastro próprio
ao qual a loja se vincula: dá para trocar o emitente sem mexer na loja.
"""

from django.contrib.auth.hashers import check_password, make_password
from django.db import models

from starrp.models.base import StoreModel, TenantModel, alive


class AddressFields(models.Model):
    """Endereço no formato da NF-e (o mesmo para loja, cliente e fornecedor)."""

    street = models.CharField(max_length=180, blank=True)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    city_ibge = models.CharField(max_length=7, blank=True, help_text="Código IBGE do município.")
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=9, blank=True)

    class Meta:
        abstract = True


class Store(AddressFields, TenantModel):
    store_lookup = "pk"

    class Kind(models.TextChoices):
        HEADQUARTERS = "headquarters", "Matriz"
        REGIONAL = "regional", "Regional"
        BRANCH = "branch", "Filial"
        DISTRIBUTION = "distribution", "Centro de distribuição"

    name = models.CharField(max_length=160, help_text="Nome fantasia.")
    # Hierarquia: a quem esta unidade responde (filial → regional → matriz).
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.BRANCH)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.SET_NULL,
                               help_text="Unidade a que esta responde (matriz, regional).")
    legal_name = models.CharField(max_length=180, blank=True, help_text="Razão social.")
    cnpj = models.CharField(max_length=18, blank=True)
    state_registration = models.CharField(max_length=20, blank=True)
    municipal_registration = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ForeignKey("starrp.Image", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    # Dados fiscais (emitente) usados na emissão e na busca de notas de entrada.
    fiscal_config = models.ForeignKey(
        "starrp.FiscalConfig", null=True, blank=True, related_name="stores", on_delete=models.SET_NULL,
        verbose_name="Dados fiscais",
    )

    # Hash PBKDF2 — nunca em claro, nunca exposto na API. É da filial (a gaveta é dela), não da regra.
    cash_action_password = models.CharField(max_length=255, blank=True)

    # Regras COMPARTILHADAS (models/rules.py): várias filiais usam a mesma; sem escolha, a padrão da conta.
    rule = models.ForeignKey("starrp.StoreRule", blank=True, related_name="stores", on_delete=models.PROTECT,
                             verbose_name="Regras da filial", help_text="PDV, caixa e venda. Vazio = a padrão.")
    logistics_rule = models.ForeignKey("starrp.LogisticsRule", blank=True, related_name="stores",
                                       on_delete=models.PROTECT, verbose_name="Regras de logística")
    stock_rule = models.ForeignKey("starrp.StockRule", blank=True, related_name="stores",
                                   on_delete=models.PROTECT, verbose_name="Regras de estoque")

    # Servidor local (módulo de sincronização): endereço que os PDVs usam na
    # loja. `cloud_only` ignora o endereço sem precisar apagá-lo.
    local_server_url = models.CharField(max_length=255, blank=True)
    cloud_only = models.BooleanField(default=False)

    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_store_name"),
            models.UniqueConstraint(
                fields=["account", "cnpj"], condition=alive() & ~models.Q(cnpj=""), name="uniq_store_cnpj"
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.deleted_at is None:
            from starrp.services import rules

            for field, model in rules.store_rule_fields().items():  # sempre com uma regra: a padrão
                if getattr(self, f"{field}_id") is None:
                    setattr(self, field, rules.default(model, self.account_id))
                    if kwargs.get("update_fields") is not None:
                        kwargs["update_fields"] = {*kwargs["update_fields"], field}
        super().save(*args, **kwargs)

    def set_cash_action_password(self, raw):
        self.cash_action_password = make_password(raw) if raw else ""

    def check_cash_action_password(self, raw):
        return bool(self.cash_action_password) and check_password(raw, self.cash_action_password)


class Terminal(StoreModel):
    """Uma instalação de PDV (desktop, celular ou navegador).

    A identidade é o UUID que o próprio app gera e guarda — não MAC, IP ou
    user-agent, que não são estáveis. Substitui `PdvTerminal` e os textos soltos
    `station`/`device_identifier` da sessão de caixa.
    """

    class DeviceType(models.TextChoices):
        DESKTOP = "desktop", "PDV desktop"
        MOBILE = "mobile", "PDV móvel"
        WEB = "web", "Navegador"

    installation_id = models.CharField(max_length=120)
    name = models.CharField(max_length=120, blank=True)
    device_type = models.CharField(max_length=10, choices=DeviceType.choices, default=DeviceType.DESKTOP)
    is_primary = models.BooleanField(default=False, help_text="Caixa principal da loja.")
    app_version = models.CharField(max_length=32, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "installation_id"], name="uniq_terminal_installation"),
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        return self.name or f"terminal {self.installation_id[:8]}"
