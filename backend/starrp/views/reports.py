from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.exceptions import PermissionDenied

from starrp.core.permissions import has_permission_code
from starrp.core.text import decimals_as_text
from starrp.services import cash_flow, dre, report_book, report_export, reports

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


class ReportBookView(APIView):
    """GET /reports/book/<slug>/?date_from=&date_to= — um relatório do livro (Movimento, Mercadorias,
    Contábil, Relacionamento) no formato padrão (indicadores + blocos), ver `services/report_book`."""

    def get(self, request, name):
        if name not in report_book.BOOK:
            return Response({"detail": f"Relatório desconhecido. Opções: {', '.join(report_book.BOOK)}."}, status=404)
        handler, permission, module = report_book.BOOK[name]
        if not has_permission_code(request.user, permission) or not request.account.has_module(module):
            raise PermissionDenied("Sem acesso a este relatório (permissão ou módulo).")
        return Response(decimals_as_text(handler(request.account, request.store, request.query_params)))


class ReportBookExportView(APIView):
    """GET /reports/book/<slug>/export/?formato=xlsx|csv[&bloco=<índice>][&aba=<valor>] + os filtros da tela.

    Excel: resumo + uma aba por bloco (e uma por classe na Curva ABC). CSV: um bloco só
    (o pedido ou a primeira tabela). Mesmas permissões do relatório."""

    def get(self, request, name):
        if name not in report_book.BOOK:
            return Response({"detail": "Relatório desconhecido."}, status=404)
        handler, permission, module = report_book.BOOK[name]
        if not has_permission_code(request.user, permission) or not request.account.has_module(module):
            raise PermissionDenied("Sem acesso a este relatório (permissão ou módulo).")
        params = request.query_params
        report = handler(request.account, request.store, params)
        block = int(params["bloco"]) if params.get("bloco", "").isdigit() else None
        if block is not None and block >= len(report["blocks"]):
            block = None
        tab = params.get("aba") or None
        tabs = report["blocks"][block].get("tabs") if block is not None else None
        tab_label = f"{tabs['label']} {tab}" if tabs and tab else None
        if params.get("formato") == "csv":
            content, kind, ext = report_export.to_csv(report, block, tab), "text/csv; charset=utf-8", "csv"
        else:
            context = {"store": getattr(request.store, "name", None), "filters": report_export.filters_label(report, params),
                       "user": request.user.get_full_name() or request.user.username,
                       "issued": timezone.localtime().strftime("%d/%m/%Y %H:%M")}
            content = report_export.to_xlsx(report, context, block, tab)
            kind, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        part = slugify(report["blocks"][block]["title"]) if block is not None else ""
        file = report_export.filename("-".join(filter(None, [name, part])), report, ext, slugify(tab_label) if tab_label else None)
        response = HttpResponse(content, content_type=kind)
        response["Content-Disposition"] = f'attachment; filename="{file}"'
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response
