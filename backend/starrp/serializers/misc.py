"""Serializers dos domínios declarativos (cadastro + leitura), sem regra própria."""
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer, tenant_serializer
from starrp.core.text import only_digits
from starrp.models import (
    Asset, AssetDisposal, AssetMovement, AuditLog, Brand, Category, Coupon, DiscountTable, FiscalConfig, FiscalProfile, FiscalSeries,
    ImportJob, InboundNFe, InboundNFeItem, Integration, Invoice, InvoiceItem, NFeEvent, NFeIssue, Notification,
    Plan, Printer, PrintJob, Product, Promotion, PromotionProduct, Scale, ScaleReading, Subscription, SyncConflict,
    Store, SyncEvent, SyncNode, SyncRun,
)

# Promoções
PromotionSerializer = tenant_serializer(Promotion, exclude=["products"])


class RuleProductSerializer(serializers.Serializer):
    """Produto da regra (alvo "Produtos"), com o "por" do encarte opcional."""

    product = TenantPrimaryKeyField(Product)
    promotional_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    compare_at_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)


class RuleSerializer(serializers.Serializer):
    """Regra DENTRO da tabela de desconto. A ordem da lista é a prioridade (1ª = topo)."""

    id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=140)
    target = serializers.ChoiceField(choices=Promotion.Target.choices, default=Promotion.Target.CATEGORIES)
    kind = serializers.ChoiceField(choices=Promotion.Kind.choices, default=Promotion.Kind.PERCENT)
    value = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    categories = TenantPrimaryKeyField(Category, many=True, required=False)
    brands = TenantPrimaryKeyField(Brand, many=True, required=False)
    products = RuleProductSerializer(many=True, required=False)
    is_enabled = serializers.BooleanField(default=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        target, kind, value = attrs["target"], attrs["kind"], attrs["value"]
        if kind == Promotion.Kind.PERCENT and value > 100:
            raise serializers.ValidationError({"value": "Percentual vai até 100."})
        need = {"categories": "Escolha ao menos uma categoria.", "brands": "Escolha ao menos uma marca.",
                "products": "Adicione ao menos um produto."}
        if target in need and not attrs.get(target):
            raise serializers.ValidationError({target: need[target]})
        ids = [row["product"].pk for row in attrs.get("products") or []]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({"products": "O mesmo produto aparece duas vezes na regra."})
        if attrs.get("starts_at") and attrs.get("ends_at") and attrs["starts_at"] > attrs["ends_at"]:
            raise serializers.ValidationError({"ends_at": "O fim vem antes do começo."})
        return attrs


class DiscountTableSerializer(TenantSerializer):
    """Tabela de desconto COM as regras dentro (`rules`, lista completa): o que sai da lista é
    excluído e a ordem é a prioridade. Ex.:
        {"name": "Liquida verão", "rules": [{"name": "Moda praia -20%", "target": "categories",
          "kind": "percent", "value": "20", "categories": ["<id>"]}]}
    """

    rules = RuleSerializer(many=True, required=False, write_only=True)  # a saída é montada em to_representation
    rule_count = serializers.SerializerMethodField()

    class Meta:
        model = DiscountTable
        fields = "__all__"

    def get_rule_count(self, obj):
        return sum(1 for r in obj.rules.all() if r.deleted_at is None)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        rules = sorted((r for r in instance.rules.all() if r.deleted_at is None), key=lambda r: (r.position, r.created_at))
        data["rules"] = [{
            "id": str(r.pk), "name": r.name, "target": r.target, "kind": r.kind, "value": str(r.value),
            "categories": [str(c.pk) for c in r.categories.all()], "brands": [str(b.pk) for b in r.brands.all()],
            "products": [{"product": str(link.product_id), "product_name": link.product.name,
                          "promotional_price": None if link.promotional_price is None else str(link.promotional_price),
                          "compare_at_price": None if link.compare_at_price is None else str(link.compare_at_price)}
                         for link in r.product_links.all() if link.deleted_at is None],
            "is_enabled": r.is_enabled, "starts_at": r.starts_at, "ends_at": r.ends_at,
        } for r in rules]
        return data

    @transaction.atomic
    def create(self, validated_data):
        rows = validated_data.pop("rules", None)
        table = super().create(validated_data)
        self._sync(table, rows or [])
        return table

    @transaction.atomic
    def update(self, instance, validated_data):
        rows = validated_data.pop("rules", None)
        table = super().update(instance, validated_data)
        if rows is not None:
            self._sync(table, rows)
        return table

    def _sync(self, table, rows):
        user = self.context["request"].user
        current = {r.pk: r for r in table.rules.filter(deleted_at__isnull=True)}
        keep = {row.get("id") for row in rows if row.get("id") in current}
        for rule in [r for pk, r in current.items() if pk not in keep]:
            rule.delete()
        # Prioridade = ordem da lista. Antes, afasta as que ficam (a posição é única na tabela).
        for offset, pk in enumerate(keep):
            Promotion.all_objects.filter(pk=pk).update(position=10_000 + offset)
        for position, row in enumerate(rows, start=1):
            row = dict(row)
            categories, brands = row.pop("categories", []), row.pop("brands", [])
            products = row.pop("products", [])
            rule = current.get(row.pop("id", None)) or Promotion(account_id=table.account_id, table=table, created_by=user)
            for field, value in row.items():
                setattr(rule, field, value)
            rule.position, rule.updated_by = position, user
            rule.save()
            rule.categories.set(categories if rule.target == Promotion.Target.CATEGORIES else [])
            rule.brands.set(brands if rule.target == Promotion.Target.BRANDS else [])
            self._sync_products(rule, products if rule.target == Promotion.Target.PRODUCTS else [], user)

    def _sync_products(self, rule, rows, user):
        links = {link.product_id: link for link in rule.product_links.filter(deleted_at__isnull=True)}
        for row in rows:
            link = links.pop(row["product"].pk, None) or PromotionProduct(
                account_id=rule.account_id, promotion=rule, product=row["product"], created_by=user)
            link.promotional_price = row.get("promotional_price")
            link.compare_at_price = row.get("compare_at_price")
            link.save()
        for leftover in links.values():
            leftover.delete()
PromotionProductSerializer = tenant_serializer(PromotionProduct)
CouponSerializer = tenant_serializer(Coupon)

# Fiscal
FiscalProfileSerializer = tenant_serializer(FiscalProfile)
FiscalSeriesSerializer = tenant_serializer(FiscalSeries)
InvoiceItemSerializer = tenant_serializer(InvoiceItem)


FISCAL_SECRETS = ("csc_token", "certificate_password", "provider_token_production", "provider_token_homologation")


class FiscalConfigSerializer(TenantSerializer):
    """Dados fiscais. Segredos só entram (na saída vira `has_<campo>`); o
    certificado chega pela ação própria. `stores` = lojas vinculadas (ids)."""

    stores = serializers.ListField(child=serializers.UUIDField(), required=False, write_only=True)
    has_certificate = serializers.SerializerMethodField()
    dfe = serializers.SerializerMethodField()

    class Meta:
        model = FiscalConfig
        exclude = ["certificate_file"]
        read_only_fields = ["provider_sync_status", "provider_sync_error", "provider_synced_at", "provider_data",
                            "certificate_valid_until", "certificate_cnpj", "certificate_name"]
        extra_kwargs = {name: {"write_only": True} for name in FISCAL_SECRETS}

    def validate_cnpj(self, value):
        digits = only_digits(value)
        if len(digits) != 14:
            raise serializers.ValidationError("CNPJ precisa ter 14 dígitos.")
        return digits

    def get_has_certificate(self, obj):
        return bool(obj.certificate_file)

    def get_dfe(self, obj):
        state = next((s for s in obj.dfe_states.all() if s.environment == obj.environment and not s.deleted_at), None)
        if state is None:
            return None
        return {"last_sync_at": state.last_sync_at, "next_allowed_at": state.next_allowed_at,
                "last_nsu": state.last_nsu, "cstat": state.last_cstat, "reason": state.last_reason}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for name in FISCAL_SECRETS:
            data[f"has_{name}"] = bool(getattr(instance, name))
        stores = [s for s in instance.stores.all() if s.deleted_at is None]
        data["stores"] = [str(s.pk) for s in stores]
        data["store_names"] = ", ".join(s.name for s in stores)
        return data

    def _link(self, config, ids):
        if ids is None:
            return
        found = Store.objects.filter(pk__in=ids)
        if found.count() != len(set(ids)):
            raise serializers.ValidationError({"stores": "Filial não encontrada."})
        Store.all_objects.filter(fiscal_config=config).exclude(pk__in=ids).update(fiscal_config=None)
        found.update(fiscal_config=config)

    def create(self, validated_data):
        ids = validated_data.pop("stores", None)
        config = super().create(validated_data)
        self._link(config, ids)
        return config

    def update(self, instance, validated_data):
        ids = validated_data.pop("stores", None)
        config = super().update(instance, validated_data)
        self._link(config, ids)
        return config


class InvoiceSerializer(TenantSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    fiscal_config_name = serializers.CharField(source="fiscal_config.name", read_only=True, default=None)
    sale_number = serializers.CharField(source="sale.number", read_only=True, default=None)

    class Meta:
        model = Invoice
        exclude = ["xml"]
        read_only_fields = [f.name for f in Invoice._meta.fields]


# NF-e de entrada
class InboundNFeItemSerializer(TenantSerializer):
    variant_name = serializers.CharField(source="variant.display_name", read_only=True, default=None)
    variant_sku = serializers.CharField(source="variant.sku", read_only=True, default=None)
    stock_quantity = serializers.SerializerMethodField()
    volumes = serializers.SerializerMethodField()

    class Meta:
        model = InboundNFeItem
        fields = "__all__"
        read_only_fields = [f.name for f in InboundNFeItem._meta.fields if f.name not in (
            "variant", "conversion_factor", "ignored", "ignored_reason")]

    def get_stock_quantity(self, obj):
        """Quanto entra no estoque: quantidade da nota vezes o fator (1 CX x 12 = 12 UN)."""
        return str((obj.quantity * obj.conversion_factor).quantize(Decimal("0.001")))

    def get_volumes(self, obj):
        from starrp.serializers.stock import volumes_of

        return volumes_of(obj.variant)
NFeEventSerializer = tenant_serializer(NFeEvent)
NFeIssueSerializer = tenant_serializer(NFeIssue)


class InboundNFeSerializer(TenantSerializer):
    items = InboundNFeItemSerializer(many=True, read_only=True)
    stage = serializers.CharField(read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    fiscal_config_name = serializers.CharField(source="fiscal_config.name", read_only=True, default=None)
    item_count = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()
    entry = serializers.SerializerMethodField()

    def get_item_count(self, obj):
        return len(obj.items.all())

    def get_pending_count(self, obj):
        return sum(1 for i in obj.items.all() if i.variant_id is None and not i.ignored)

    def get_entry(self, obj):
        """A entrada de estoque viva desta nota (atalho para abrir a conferência)."""
        doc = next((d for d in obj.stock_documents.all() if d.status != "cancelled" and d.deleted_at is None), None)
        return doc and {"id": str(doc.pk), "number": doc.number, "status": doc.status,
                        "checked": doc.checked_at is not None}

    class Meta:
        model = InboundNFe
        exclude = ["summary_xml", "full_xml"]
        read_only_fields = [f.name for f in InboundNFe._meta.fields if f.name != "supplier"]


# Patrimônio
AssetSerializer = tenant_serializer(Asset, read_only=("qr_token", "source_nfe_cancelled"))
AssetMovementSerializer = tenant_serializer(AssetMovement)
AssetDisposalSerializer = tenant_serializer(AssetDisposal)

# Dispositivos
PrinterSerializer = tenant_serializer(Printer)
ScaleSerializer = tenant_serializer(Scale, read_only=("agent_instance_id", "agent_lease_expires_at"))
ScaleReadingSerializer = tenant_serializer(ScaleReading)
PrintJobSerializer = tenant_serializer(PrintJob, read_only=("serial", "printed_at", "printed_by"))

# Sistema
AuditLogSerializer = tenant_serializer(AuditLog)
NotificationSerializer = tenant_serializer(Notification, read_only=("read_at",))
ImportJobSerializer = tenant_serializer(
    ImportJob, read_only=("status", "total", "created_count", "updated_count", "errors", "finished_at")
)


# Plataforma e sincronização (somente leitura na API da conta)
class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = "__all__"


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)

    class Meta:
        model = Subscription
        exclude = ["account"]


class IntegrationSerializer(serializers.ModelSerializer):
    """`credentials` entra; na saída só aparece quais chaves estão preenchidas."""

    credentials = serializers.DictField(write_only=True, required=False)
    configured_keys = serializers.SerializerMethodField()

    class Meta:
        model = Integration
        exclude = ["account"]

    def get_configured_keys(self, obj):
        return sorted(k for k, v in (obj.credentials or {}).items() if v)


def _readonly(model_cls):
    return type(f"{model_cls.__name__}Serializer", (serializers.ModelSerializer,), {
        "Meta": type("Meta", (), {"model": model_cls, "exclude": ["credential_hash"] if model_cls is SyncNode else [],
                                  "read_only_fields": [f.name for f in model_cls._meta.fields]}),
    })


SyncNodeSerializer = _readonly(SyncNode)
SyncEventSerializer = _readonly(SyncEvent)
SyncRunSerializer = _readonly(SyncRun)
SyncConflictSerializer = _readonly(SyncConflict)
