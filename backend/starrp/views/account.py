"""Configurações da conta numa página só (admin da conta).

GET/PATCH /api/v1/account/settings/
    {"account": {...}, "pdv": {...}, "stock": {...}, "plan": {...}}

- account: dados da empresa titular (nome, documento, contato, fuso);
- pdv: regras do PDV e do caixa, aplicadas a TODAS as lojas no salvar (cada loja ainda
  ajusta a sua em Lojas); a leitura mostra a da loja principal (a mais antiga);
- stock: configurações de estoque da conta (FEFO/FIFO, vencimento, saldo negativo);
- plan: plano e módulos (só leitura).
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.permissions import IsAccountAdmin
from starrp.models import StockSettings, Store

PDV_FIELDS = ("require_open_cash_session", "cash_closing_tolerance", "require_seller", "auto_print_receipt",
              "print_cancellation_receipt")


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
    pdv_lock_minutes = serializers.IntegerField(min_value=0, max_value=120, required=False)


class StockSection(serializers.Serializer):
    picking_strategy = serializers.ChoiceField(choices=StockSettings.Picking.choices, required=False)
    expiry_warning_days = serializers.IntegerField(min_value=0, max_value=365, required=False)
    block_expired = serializers.BooleanField(required=False)
    allow_negative_stock = serializers.BooleanField(required=False)


class AccountSettingsView(APIView):
    permission_classes = [IsAccountAdmin]

    def _stores(self, account):
        return Store.all_objects.filter(account=account, deleted_at__isnull=True).order_by("created_at")

    def _stock(self, account):
        found = StockSettings.all_objects.filter(account=account, deleted_at__isnull=True).first()
        return found or StockSettings.all_objects.create(account=account)

    def _payload(self, request):
        account = request.account
        main = self._stores(account).first()
        stock = self._stock(account)
        subscription = getattr(account, "subscription", None)
        return {
            "account": {f: getattr(account, f) for f in ("name", "document", "email", "phone", "timezone")},
            "pdv": {**{f: getattr(main, f) if main else None for f in PDV_FIELDS},
                    "cash_closing_tolerance": str(main.cash_closing_tolerance) if main else "0.50",
                    "pdv_lock_minutes": int((main.settings or {}).get("pdv_lock_minutes", 5)) if main else 5},
            "stock": {f: getattr(stock, f) for f in ("picking_strategy", "expiry_warning_days", "block_expired",
                                                     "allow_negative_stock")},
            "plan": {"name": subscription.plan.name if subscription and subscription.plan_id else "—",
                     "status": subscription.get_status_display() if subscription else "—",
                     "modules": sorted(account.active_modules()), "stores": self._stores(account).count()},
        }

    def get(self, request):
        return Response(self._payload(request))

    @transaction.atomic
    def patch(self, request):
        account = request.account
        sections = {"account": AccountSection, "pdv": PdvSection, "stock": StockSection}
        clean = {}
        for key, serializer_class in sections.items():
            if key in request.data:
                body = serializer_class(data=request.data[key], partial=True)
                body.is_valid(raise_exception=True)
                clean[key] = body.validated_data
        if clean.get("account"):
            for field, value in clean["account"].items():
                setattr(account, field, value)
            account.save()
        if clean.get("pdv"):
            lock = clean["pdv"].pop("pdv_lock_minutes", None)
            for store in self._stores(account):  # vale para todas as lojas
                for field, value in clean["pdv"].items():
                    setattr(store, field, value)
                if lock is not None:
                    store.settings = {**(store.settings or {}), "pdv_lock_minutes": lock}
                store.updated_by = request.user
                store.save()
        if clean.get("stock"):
            stock = self._stock(account)
            for field, value in clean["stock"].items():
                setattr(stock, field, value)
            stock.updated_by = request.user
            stock.save()
        return Response(self._payload(request))
