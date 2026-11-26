"""Financeiro pela API.

    /finance/accounts/{id}/statement/?date_from=&date_to=   extrato com saldo corrido
    POST /finance/accounts/transfer/      {source, target, amount, description}
    /finance/titles/, /finance/installments/{id}/settle/    contas a pagar/receber e baixa
    /finance/transactions/                lançamento avulso (despesa/receita sem título)
    POST /finance/transactions/{id}/reverse/                estorno (lançamento não se edita)
    /finance/recurring/ (+ POST {id}/generate/, POST generate-all/)  contas recorrentes
    GET /finance/installments/{id}/credit/  crédito disponível do cliente/fornecedor da parcela
    Relatórios: /reports/dre/, /reports/cash-flow/, /reports/balances/, /reports/aging/
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from starrp.core.bulk import bulk_action
from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import decimals_as_text
from starrp.core.viewsets import TenantViewSet
from starrp.models import (
    FinancialAccount, FinancialCategory, FinancialTitle, FinancialTransaction, Installment, RecurringTitle,
)
from starrp.models.platform import Module
from starrp.serializers import finance as s
from starrp.services import cash_flow, finance, ledger, recurring


class FinanceView:
    required_module = Module.FINANCE
    permission_code = "finance"

    def check_account(self, account):
        """Quem é de algumas filiais não TIRA dinheiro da conta da rede (R4-10): o lançamento direto já era
        recusado, mas transferência, baixa e estorno passavam."""
        check_network_account(self.request, account)


def check_network_account(request, account):
    if account is not None and account.store_id is None and getattr(request, "allowed_store_ids", None) is not None:
        raise PermissionDenied("Esta conta é da rede; só quem acessa todas as filiais movimenta o dinheiro dela.")


class FinancialAccountViewSet(FinanceView, TenantViewSet):
    model = FinancialAccount
    serializer_class = s.FinancialAccountSerializer
    filterset_fields = ["kind", "is_active", "store"]
    search_fields = ["name", "bank_code", "agency"]

    def perform_destroy(self, instance):
        if instance.payment_methods.filter(deleted_at__isnull=True).exists():
            raise StateConflict("Esta conta recebe uma forma de pagamento: troque a conta dela antes de excluir.")
        if instance.opening_balance + cash_flow._net(instance.transactions.filter(deleted_at__isnull=True)):
            raise StateConflict("Esta conta tem saldo: transfira o dinheiro antes de excluir.")
        super().perform_destroy(instance)

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        return Response(decimals_as_text(cash_flow.statement(self.get_object(), request.query_params)))

    @action(detail=False, methods=["post"])
    def transfer(self, request):
        source = get_object_or_404(FinancialAccount.objects, pk=request.data.get("source"))
        self.check_account(source)
        target = get_object_or_404(FinancialAccount.objects, pk=request.data.get("target"))
        try:
            amount = Decimal(str(request.data.get("amount") or "0"))
        except InvalidOperation:
            raise BusinessError("Informe um valor válido.") from None
        if not amount.is_finite() or amount > Decimal("1e12"):
            raise BusinessError("Informe um valor válido.")
        amount = amount.quantize(Decimal("0.01"))
        if amount <= 0:
            raise BusinessError("Informe um valor maior que zero.")
        day = parse_date(str(request.data.get("date") or "")) or None
        ledger.transfer(source, target, amount, description=str(request.data.get("description", "")),
                        user=request.user, date=day)
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

    def list(self, request, *args, **kwargs):
        from starrp.services.report_closing import ensure_recurring

        ensure_recurring(request.account)  # sem Celery, as recorrências do dia nascem aqui
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancela um título lançado à mão que não tem baixa."""
        return Response(self.get_serializer(finance.cancel_title(self.get_object(), request.user)).data)


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
        installment = self.get_object()
        if installment.title.kind == FinancialTitle.Kind.PAYABLE:
            self.check_account(data.get("financial_account"))
        part = finance.settle(installment, data.pop("financial_account", None), data.pop("amount"), request.user,
                              **data)
        return Response(self.get_serializer(part).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def unsettle(self, request, pk=None):
        """Desfaz a baixa lançada por engano: {"reason"}."""
        installment = self.get_object()
        for tx in installment.transactions.filter(reversal_of__isnull=True).select_related("financial_account"):
            self.check_account(tx.financial_account)
        part = finance.unsettle(installment, request.user, request.data.get("reason"))
        return Response(self.get_serializer(part).data)

    @action(detail=True, methods=["get"])
    def credit(self, request, pk=None):
        title = self.get_object().title
        party = finance._party(title)
        value = finance.party_credit(**party) if party else Decimal("0")
        return Response({"credit": str(max(value, Decimal("0")).quantize(Decimal("0.01"))),
                         "party": (title.customer or title.supplier).name if party else None})


class FinancialTransactionViewSet(FinanceView, TenantViewSet):
    """Lançamento é imutável: errado se corrige com estorno, para o extrato contar a história."""

    model = FinancialTransaction
    serializer_class = s.FinancialTransactionSerializer
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("financial_account", "category", "customer", "supplier")
    filterset_fields = {"financial_account": ["exact"], "kind": ["exact"], "date": ["gte", "lte"],
                        "category": ["exact"], "reconciled": ["exact"], "sale": ["exact"], "cash_session": ["exact"],
                        "customer": ["exact"], "supplier": ["exact"]}
    search_fields = ["description"]

    def save_kwargs(self, serializer, creating):
        return {**super().save_kwargs(serializer, creating), "operator": self.request.user}

    @bulk_action("Estornar", icon="pi pi-undo", danger=True, permission="manage",
                 confirm="Estornar os lançamentos selecionados? Cada um ganha um lançamento inverso.")
    def bulk_reverse(self, request, queryset, params):
        done, skipped = 0, []
        for tx in queryset:
            reason = ("já é um estorno" if tx.reversal_of_id else "baixa de parcela: estorne pelo título"
                      if tx.installment_id else "já estornado" if tx.reversals.exists()
                      else "conta da rede" if self._restricted() and any(
                          leg.financial_account.store_id is None for leg in ledger.legs(tx)) else "")
            if reason:
                skipped.append({"id": str(tx.pk), "label": tx.description, "reason": reason})
                continue
            try:
                with transaction.atomic():
                    ledger.reverse(tx, description=str(params.get("reason") or ""), user=request.user)
            except BusinessError as error:
                skipped.append({"id": str(tx.pk), "label": tx.description, "reason": str(error.detail)})
                continue
            done += 1
        return {"affected": done, "skipped": skipped}

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, pk=None):
        tx = self.get_object()
        if tx.reversal_of_id:
            raise StateConflict("Este lançamento já é um estorno.")
        if tx.installment_id:
            raise StateConflict("Baixa de parcela se desfaz na parcela (Desfazer baixa).")
        for leg in ledger.legs(tx):  # transferência: estornar uma perna desfaz as duas
            self.check_account(leg.financial_account)
        reversal = ledger.reverse(tx, description=str(request.data.get("reason") or ""), user=request.user)
        return Response(self.get_serializer(reversal).data, status=201)


class RecurringTitleViewSet(FinanceView, TenantViewSet):
    """Conta recorrente: gera um título por mês (tarefa diária ou "Gerar agora")."""

    model = RecurringTitle
    serializer_class = s.RecurringTitleSerializer
    select_related = ("customer", "supplier", "category")
    filterset_fields = ["kind", "is_active", "customer", "supplier", "category"]
    search_fields = ["description", "customer__name", "supplier__name"]

    def get_queryset(self):
        # `generated` do serializer na mesma query (antes: uma contagem por recorrência).
        return super().get_queryset().annotate(
            generated_count=Count("titles", filter=Q(titles__deleted_at__isnull=True), distinct=True))

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        created = recurring.generate_one(self.get_object(), user=request.user)
        return Response({"created": len(created), "titles": [str(t.pk) for t in created]})

    @action(detail=False, methods=["post"], url_path="generate-all")
    def generate_all(self, request):
        return Response({"created": recurring.generate_all(request.account)})
