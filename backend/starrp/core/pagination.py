from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

    def paginate_queryset(self, queryset, request, view=None):
        # OFFSET sem ordem determinística repete/pula linhas entre páginas.
        if hasattr(queryset, "ordered") and not queryset.ordered:
            queryset = queryset.order_by("-pk")
        return super().paginate_queryset(queryset, request, view=view)
