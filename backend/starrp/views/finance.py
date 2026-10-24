"""Financeiro pela API.

    /finance/accounts/{id}/statement/?date_from=&date_to=   extrato com saldo corrido
    POST /finance/accounts/transfer/      {source, target, amount, description}
    /finance/titles/, /finance/installments/{id}/settle/    contas a pagar/receber e baixa
    /finance/transactions/                lançamento avulso (despesa/receita sem título)
    POST /finance/transactions/{id}/reverse/                estorno (lançamento não se edita)
    Relatórios: /reports/dre/, /reports/cash-flow/, /reports/balances/, /reports/aging/
"""
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.bulk import bulk_action
from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import decimals_as_text
from starrp.core.viewsets import TenantViewSet
from starrp.models import FinancialAccount, FinancialCategory, FinancialTitle, FinancialTransaction, Installment
from starrp.models.platform import Module
from starrp.serializers import finance as s
from starrp.services import cash_flow, finance, ledger


class FinanceView:
    required_module = Module.FINANCE
    permission_code = "finance"


class FinancialAccountViewSet(FinanceView, TenantViewSet):
    model = FinancialAccount
    serializer_class = s.FinancialAccountSerializer
    filterset_fields = ["kind", "is_active", "store"]
    search_fields = ["name", "bank_code", "agency"]

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        return Response(decimals_as_text(cash_flow.statement(self.get_object(), request.query_params)))

    @action(detail=False, methods=["post"])
    def transfer(self, request):
        source = get_object_or_404(FinancialAccount.objects, pk=request.data.get("source"))
        target = get_object_or_404(FinancialAccount.objects, pk=request.data.get("target"))
        amount = Decimal(str(request.data.get("amount") or "0"))
        if amount <= 0:
            raise BusinessError("Informe um valor maior que zero.")
        ledger.transfer(source, target, amount, description=str(request.data.get("description", "")),
                        user=request.user)
        return Response(decimals_as_text(cash_flow.balances(request.account, request.store)), status=201)


class FinancialCategoryViewSet(FinanceView, TenantViewSet):
    model = FinancialCategory
    serializer_class = s.FinancialCategorySerializer
    tree_parent = "parent"
    filterset_fields = ["kind", "parent", "is_active"]

    def perform_destroy(self, instance):
        if instance.system_key:
            raise StateConflict("Categoria usada nos lançamentos automáticos: renomeie, mas não exclua.")
        super().perform_destroy(instance)


class FinancialTitleViewSet(FinanceView, TenantViewSet):
    model = FinancialTitle
    serializer_class = s.FinancialTitleSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    select_related = ("customer", "supplier", "category")
    prefetch_related = ("installments",)
    filterset_fields = {"kind": ["exact"], "status": ["exact"], "customer": ["exact"], "supplier": ["exact"],
                        "issue_date": ["gte", "lte"]}
    search_fields = ["description", "document_number", "customer__name", "supplier__name"]


class InstallmentViewSet(FinanceView, TenantViewSet):
    model = Installment
    serializer_class = s.InstallmentSerializer
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("title__customer", "title__supplier")
    filterset_fields = {"title": ["exact"], "status": ["exact"], "due_date": ["gte", "lte"],
                        "title__kind": ["exact"], "title__customer": ["exact"], "title__supplier": ["exact"]}

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        body = s.SettleSerializer(data=request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        part = finance.settle(self.get_object(), data.pop("financial_account"), data.pop("amount"), request.user,
                              **data)
        return Response(self.get_serializer(part).data)


class FinancialTransactionViewSet(FinanceView, TenantViewSet):
    """Lançamento é imutável: errado se corrige com estorno, para o extrato contar a história."""

    model = FinancialTransaction
    serializer_class = s.FinancialTransactionSerializer
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("financial_account", "category")
    filterset_fields = {"financial_account": ["exact"], "kind": ["exact"], "date": ["gte", "lte"],
                        "category": ["exact"], "reconciled": ["exact"], "sale": ["exact"], "cash_session": ["exact"]}
    search_fields = ["description"]

    def save_kwargs(self, serializer, creating):
        return {**super().save_kwargs(serializer, creating), "operator": self.request.user}

    @bulk_action("Estornar", icon="pi pi-undo", danger=True,
                 confirm="Estornar os lançamentos selecionados? Cada um ganha um lançamento inverso.")
    def bulk_reverse(self, request, queryset, params):
        done, skipped = 0, []
        for tx in queryset:
            reason = ("já é um estorno" if tx.reversal_of_id else "baixa de parcela: estorne pelo título"
                      if tx.installment_id else "já estornado" if tx.reversals.exists() else "")
            if reason:
                skipped.append({"id": str(tx.pk), "label": tx.description, "reason": reason})
                continue
            ledger.reverse(tx, description=str(params.get("reason") or ""), user=request.user)
            done += 1
        return {"affected": done, "skipped": skipped}

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, pk=None):
        tx = self.get_object()
        if tx.reversal_of_id:
            raise StateConflict("Este lançamento já é um estorno.")
        if tx.installment_id:
            raise StateConflict("Baixa de parcela se estorna pelo título.")
        reversal = ledger.reverse(tx, description=str(request.data.get("reason") or ""), user=request.user)
        return Response(self.get_serializer(reversal).data, status=201)
