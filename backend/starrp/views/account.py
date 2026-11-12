"""Configurações da conta numa página só (admin da conta).

GET/PATCH /api/v1/account/settings/
    {"account": {...}, "pdv": {...}, "stock": {...}, "plan": {...}}

- account: dados da empresa titular (nome, documento, contato, fuso);
- pdv: regras do PDV e do caixa, aplicadas a TODAS as lojas no salvar (cada loja ainda
  ajusta a sua em Lojas); a leitura mostra a da loja principal (a mais antiga);
- stock: configurações de estoque da conta (FEFO/FIFO, vencimento, saldo negativo);
- cosmos: resumo diário e, com o módulo `pricing`, a precificação (preço comparado com o mercado, ver
  models/market.py; sem o módulo, os campos dela não aparecem e não são gravados). Fontes, fila, limite mensal e
  chaves ficam só no admin do Django: a conta não vê quais APIs são usadas;
- plan: plano e módulos (só leitura).
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.permissions import IsAccountAdmin
from starrp.models import Module, StockRule, Store, StoreRule
from starrp.services import rules

PRICE_FIELDS = ("price_tracking_enabled", "price_tracking_hours", "price_min_margin", "price_band", "price_min_competitors",
                "price_match_min")
TRACKING_HOURS = (6, 12, 24, 72, 168)
PDV_FIELDS = ("require_open_cash_session", "cash_closing_tolerance", "require_seller", "auto_print_receipt",
              "print_cancellation_receipt", "require_payment_reference", "pdv_auto_lock", "pdv_lock_minutes")


class AccountSection(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    document = serializers.CharField(max_length=18, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=50, required=False)


class PdvSection(serializers.Serializer):
    require_open_cash_session = serializers.BooleanField(required=False)
    cash_closing_tolerance = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0"),
                                                      required=False)
    require_seller = serializers.BooleanField(required=False)
    auto_print_receipt = serializers.BooleanField(required=False)
    print_cancellation_receipt = serializers.BooleanField(required=False)
    require_payment_reference = serializers.BooleanField(required=False)
    pdv_auto_lock = serializers.BooleanField(required=False)
    pdv_lock_minutes = serializers.IntegerField(min_value=1, max_value=120, required=False)


class StockSection(serializers.Serializer):
    picking_strategy = serializers.ChoiceField(choices=StockRule.Picking.choices, required=False)
    expiry_warning_days = serializers.IntegerField(min_value=0, max_value=365, required=False)
    block_expired = serializers.BooleanField(required=False)
    allow_negative_stock = serializers.BooleanField(required=False)
    fifo_by_entry = serializers.BooleanField(required=False)


class CosmosSection(serializers.Serializer):
    cosmos_daily_digest = serializers.BooleanField(required=False)
    cosmos_seo_ai = serializers.BooleanField(required=False)
    cosmos_pricing_ai = serializers.BooleanField(required=False)
    cosmos_stock_advice = serializers.BooleanField(required=False)
    price_tracking_enabled = serializers.BooleanField(required=False)
    price_tracking_hours = serializers.ChoiceField(choices=TRACKING_HOURS, required=False)
    price_min_margin = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"),
                                                max_value=Decimal("95"), required=False)
    price_band = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("1"),
                                          max_value=Decimal("50"), required=False)
    price_min_competitors = serializers.IntegerField(min_value=1, max_value=20, required=False)
    price_match_min = serializers.IntegerField(min_value=60, max_value=100, required=False)


class AccountSettingsView(APIView):
    permission_classes = [IsAccountAdmin]

    def _stores(self, account):
        return Store.all_objects.filter(account=account, deleted_at__isnull=True).order_by("created_at")

    # PDV e estoque editam as regras PADRÃO (as filiais que usam outra regra se ajustam nela).
    def _stock(self, account):
        return rules.default(StockRule, account.pk)

    def _pdv(self, account):
        return rules.default(StoreRule, account.pk)

    def _cosmos(self, account):
        """Só o que a conta tem: cada campo depende do módulo dele."""
        out = {}
        if account.cosmos_active:
            out["cosmos_daily_digest"] = account.cosmos_daily_digest
            if account.has_module(Module.SEO):
                out["cosmos_seo_ai"] = account.cosmos_seo_ai
            if account.has_module(Module.PRICING):
                out["cosmos_pricing_ai"] = account.cosmos_pricing_ai
            if account.has_module(Module.STOCK):
                out["cosmos_stock_advice"] = account.cosmos_stock_advice
        if account.has_module(Module.PRICING):
            out.update({f: getattr(account, f) for f in PRICE_FIELDS})
            out.update(price_min_margin=str(account.price_min_margin), price_band=str(account.price_band),
                       price_tracking_hours=str(account.price_tracking_hours))
        return out

    def _payload(self, request):
        account = request.account
        pdv = self._pdv(account)
        stock = self._stock(account)
        subscription = getattr(account, "subscription", None)
        return {
            "account": {**{f: getattr(account, f) for f in ("name", "document", "email", "phone", "timezone")},
                        "logo_url": account.logo.file.url if account.logo_id else None},
            "pdv": {**{f: getattr(pdv, f) for f in PDV_FIELDS}, "cash_closing_tolerance": str(pdv.cash_closing_tolerance),
                    "rule_name": pdv.name, "stores_using": pdv.stores_using().count()},
            "stock": {f: getattr(stock, f) for f in ("picking_strategy", "expiry_warning_days", "block_expired",
                                                     "allow_negative_stock", "fifo_by_entry")},
            "cosmos": self._cosmos(account),
            "plan": {"name": subscription.plan.name if subscription and subscription.plan_id else "—",
                     "status": subscription.get_status_display() if subscription else "—",
                     "modules": sorted(account.active_modules()), "stores": self._stores(account).count()},
        }

    def get(self, request):
        return Response(self._payload(request))

    @transaction.atomic
    def patch(self, request):
        account = request.account
        sections = {"account": AccountSection, "pdv": PdvSection, "stock": StockSection, "cosmos": CosmosSection}
        clean = {}
        for key, serializer_class in sections.items():
            if key in request.data:
                body = serializer_class(data=request.data[key], partial=True)
                body.is_valid(raise_exception=True)
                clean[key] = body.validated_data
        if clean.get("cosmos"):
            allowed = self._cosmos(account)
            clean["cosmos"] = {k: v for k, v in clean["cosmos"].items() if k in allowed}
        if clean.get("account") or clean.get("cosmos"):
            for field, value in {**clean.get("account", {}), **clean.get("cosmos", {})}.items():
                setattr(account, field, value)
            account.save()
        if clean.get("pdv"):
            pdv = self._pdv(account)
            for field, value in clean["pdv"].items():
                setattr(pdv, field, value)
            pdv.updated_by = request.user
            pdv.save()
        if clean.get("stock"):
            stock = self._stock(account)
            for field, value in clean["stock"].items():
                setattr(stock, field, value)
            stock.updated_by = request.user
            stock.save()
        return Response(self._payload(request))


class AccountLogoView(APIView):
    """POST multipart `file`: troca o logo (ajustado para 1080×1080). DELETE: tira (volta o do Starrp)."""

    permission_classes = [IsAccountAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        from starrp.core.errors import BusinessError
        from starrp.services import media

        upload = request.FILES.get("file")
        if upload is None:
            raise BusinessError("Envie a imagem do logo no campo `file`.", code="file_required")
        image = media.store_upload(request.account, request.user, media.square_logo(upload), alt="Logo da empresa")
        request.account.logo = image
        request.account.save(update_fields=["logo", "updated_at"])
        return Response({"logo_url": image.file.url, "width": image.width, "height": image.height})

    def delete(self, request):
        request.account.logo = None
        request.account.save(update_fields=["logo", "updated_at"])
        return Response({"logo_url": None})
