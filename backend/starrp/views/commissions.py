from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from starrp.core.permissions import has_permission_code
from starrp.core.text import decimals_as_text
from starrp.core.viewsets import TenantViewSet
from starrp.models import Commission, FinancialAccount
from starrp.serializers import sales as s
from starrp.services import commissions


class CommissionViewSet(TenantViewSet):
    model = Commission
    serializer_class = s.CommissionSerializer
    permission_code = "commissions"
    # POST só para `payout`: comissão nasce da venda, nunca à mão.
    http_method_names = ["get", "post", "patch", "head", "options"]
    select_related = ("seller", "sale")
    filterset_fields = {"seller": ["exact"], "status": ["exact"], "created_at": ["gte", "lte"]}

    def get_queryset(self):
        qs = super().get_queryset()
        profile = getattr(self.request, "profile", None)
        # Vendedor sem gestão de comissões vê só as dele.
        if profile and profile.is_seller and not has_permission_code(self.request.user, "commissions.manage"):
            qs = qs.filter(seller=self.request.user)
        return qs

    action_permissions = {"payout": "commissions.manage"}

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="Comissão nasce da venda; use /commissions/payout/ para pagar.")

    @action(detail=False, methods=["post"])
    def payout(self, request):
        """Paga as comissões pendentes de um vendedor até `until` (padrão: hoje)."""
        seller = get_object_or_404(get_user_model(), pk=request.data.get("seller"), profile__account=request.account)
        account = get_object_or_404(FinancialAccount.objects, pk=request.data.get("financial_account"))
        until = parse_date(str(request.data.get("until") or "")) or None
        result = commissions.pay(request.account, seller, account, request.user, until=until, store=request.store)
        return Response(decimals_as_text(result), status=201)
