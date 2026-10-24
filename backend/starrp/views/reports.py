from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.exceptions import PermissionDenied

from starrp.core.permissions import has_permission_code
from starrp.core.text import decimals_as_text
from starrp.services import cash_flow, dre, reports

# nome → (função, permissão, módulo). Relatório financeiro exige o módulo Financeiro.
REPORTS = {
    "dashboard": (reports.dashboard, "reports.view", "base"),
    "summary": (reports.summary, "reports.view", "base"),
    "sales-by-day": (reports.by_day, "reports.view", "base"),
    "products": (reports.top_products, "reports.view", "base"),
    "payment-methods": (reports.by_payment_method, "reports.view", "base"),
    "sellers": (reports.by_seller, "reports.view", "base"),
    "dre": (dre.build, "finance.view", "finance"),
    "cash-flow": (cash_flow.build, "finance.view", "finance"),
    "balances": (cash_flow.balances, "finance.view", "finance"),
    "aging": (cash_flow.aging, "finance.view", "finance"),
}


class ReportView(APIView):
    """GET /reports/<nome>/?date_from=AAAA-MM-DD&date_to=...&seller=<id>

    A loja vem do header `X-Store-ID` (sem ele, a rede inteira).
    """

    def get(self, request, name):
        if name not in REPORTS:
            return Response({"detail": f"Relatório desconhecido. Opções: {', '.join(REPORTS)}."}, status=404)
        handler, permission, module = REPORTS[name]
        if not has_permission_code(request.user, permission) or not request.account.has_module(module):
            raise PermissionDenied("Sem acesso a este relatório (permissão ou módulo).")
        return Response(decimals_as_text(handler(request.account, request.store, request.query_params)))
