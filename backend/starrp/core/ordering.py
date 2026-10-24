"""Ordenação de lista que entende o nome da COLUNA da tela.

`?ordering=category_name` vira `category__name` (o campo do serializer diz de
onde vem o dado); `?ordering=-price` funciona até em valor calculado, desde que
a view declare como calcular (`ordering_annotations`). Exemplos:

    ?ordering=name            A → Z
    ?ordering=-name           Z → A
    ?ordering=-price,name     mais caro primeiro, empate por nome

Coluna que não dá para ordenar devolve 400 com a explicação (em vez de ser
ignorada em silêncio e a tela mostrar uma ordem que não é a pedida).
Relação "para muitos" (variantes, tags) só ordena via anotação: ordenar direto
por ela repetiria a linha uma vez por item.
"""
from django.core.exceptions import FieldDoesNotExist
from django.db.models import F
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter

BLOCKED = {"password", "cash_action_password", "secret", "token"}


def resolve_path(model, path):
    """O caminho `a__b__c` existe no model e não passa por relação "para muitos"?"""
    parts = path.split("__")
    for index, part in enumerate(parts):
        if part in BLOCKED:
            return False
        try:
            field = model._meta.get_field(part)
        except FieldDoesNotExist:
            return False
        if field.many_to_many or field.one_to_many:
            return False
        if field.is_relation:
            model = field.related_model
        elif index != len(parts) - 1:
            return False
    return True


class ColumnOrderingFilter(OrderingFilter):
    def _source(self, view, request, name):
        """Caminho no banco para a coluna `name` (ou None se não for ordenável)."""
        mapped = getattr(view, "ordering_map", {}).get(name)
        if mapped:
            return mapped
        serializer_class = getattr(view, "get_serializer_class", lambda: None)()
        if serializer_class is not None:
            field = serializer_class(context={"request": request, "view": view}).fields.get(name)
            if field is not None and not isinstance(field, serializers.SerializerMethodField) and field.source != "*":
                return field.source.replace(".", "__")
        return name

    def filter_queryset(self, request, queryset, view):
        raw = request.query_params.get(self.ordering_param, "").strip()
        if not raw:
            return queryset
        annotations = getattr(view, "ordering_annotations", {})
        ordering, needed = [], {}
        for term in (t.strip() for t in raw.split(",")):
            if not term:
                continue
            desc, name = term.startswith("-"), term.lstrip("-")
            if name in annotations:
                needed[f"_order_{name}"] = annotations[name]
                path = f"_order_{name}"
            elif name in queryset.query.annotations:
                path = name
            else:
                path = self._source(view, request, name)
                if not resolve_path(queryset.model, path):
                    raise ValidationError({"ordering": f"Não dá para ordenar por “{name}”."})
            # Vazio vai para o fim nos dois sentidos (no Postgres o DESC o poria no topo).
            ordering.append(F(path).desc(nulls_last=True) if desc else F(path).asc(nulls_last=True))
        if needed:
            queryset = queryset.annotate(**needed)
        # `pk` desempata: sem ele a paginação pode repetir ou pular linhas.
        return queryset.order_by(*ordering, "pk")
