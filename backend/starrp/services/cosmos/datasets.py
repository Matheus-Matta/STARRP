"""Consultas agregadas para a Cosmos: "faturamento por vendedor no mês", "estoque por categoria".

O modelo não escreve SQL nem conta números: ele escolhe um CONJUNTO (vendas, itens vendidos,
clientes...), as MEDIDAS (faturamento, quantidade...), até dois AGRUPAMENTOS (vendedor, mês...)
e filtros — e o servidor calcula. Cada conjunto parte do manager com escopo (`Model.objects`):
conta e filiais permitidas valem sozinhas; a filial ativa da tela recorta por cima.

    query(actor, "vendas", metrics=["faturamento", "quantidade"], group_by=["vendedor"],
          date_from="2026-10-01", date_to="2026-10-31")
    → {"columns": [...], "rows": [{"vendedor": "Ana", "faturamento": "1520.00", "quantidade": 12}, ...]}
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import (
    Coalesce, ExtractHour, ExtractWeekDay, NullIf, TruncDate, TruncMonth, TruncWeek,
)
from django.utils import timezone

from starrp.core.permissions import has_permission_code
from starrp.models import (
    CosmosFinding, Customer, FinancialTitle, Installment, PriceCheck, Product, ProductVariant, Sale, SaleItem, SaleReturn, StockBalance,
)
from starrp.models.base import store_scope_q
from starrp.services.reports import period

MONEY = DecimalField(max_digits=18, decimal_places=2)
WEEKDAYS = {1: "Dom", 2: "Seg", 3: "Ter", 4: "Qua", 5: "Qui", 6: "Sex", 7: "Sáb"}
MAX_ROWS = 500
TIME_DIMS = {"dia", "semana", "mes"}


def _person(prefix):
    """Nome de quem fez (primeiro nome, senão o login)."""
    return Coalesce(NullIf(F(f"{prefix}__first_name"), Value("")), F(f"{prefix}__username"))


@dataclass
class Dim:
    label: str
    expr: object  # caminho do ORM (str) ou expressão
    choices: dict = field(default_factory=dict)  # valor → rótulo


@dataclass
class Metric:
    label: str
    expr: object
    format: str = "money"


@dataclass
class Dataset:
    label: str
    description: str
    model: object
    permission: str
    module: str
    date_field: str | None
    base: object  # Q do recorte
    dims: dict
    metrics: dict
    filters: dict = field(default_factory=dict)  # nome → caminho do ORM (igualdade; lista = "em")


def _time_dims(path, date_only=False):
    # Campo só de data (vencimento) já é o dia: TruncDate converte fuso de data-hora e quebra nele.
    return {"dia": Dim("Dia", path if date_only else TruncDate(path)), "semana": Dim("Semana", TruncWeek(path)),
            "mes": Dim("Mês", TruncMonth(path))}


def _choices(model, name):
    return {k: str(v) for k, v in model._meta.get_field(name).choices}


ITEM_COST = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=MONEY)
BALANCE_COST = ExpressionWrapper(F("quantity") * F("variant__average_cost"), output_field=MONEY)
BALANCE_PRICE = ExpressionWrapper(F("quantity") * F("variant__price"), output_field=MONEY)
OPEN_AMOUNT = ExpressionWrapper(F("amount") - F("paid_amount"), output_field=MONEY)

DATASETS = {
    "vendas": Dataset(
        "Vendas concluídas", "Cada venda fechada e paga (data = conclusão).", Sale, "reports.view", "base",
        "completed_at", Q(status=Sale.Status.COMPLETED),
        {**_time_dims("completed_at"), "hora": Dim("Hora", ExtractHour("completed_at")),
         "dia_da_semana": Dim("Dia da semana", ExtractWeekDay("completed_at"), WEEKDAYS),
         "filial": Dim("Filial", "store__name"), "vendedor": Dim("Vendedor", _person("seller")),
         "operador": Dim("Operador", _person("operator")), "cliente": Dim("Cliente", "customer__name"),
         "canal": Dim("Canal", "channel", _choices(Sale, "channel")),
         "situacao_pagamento": Dim("Pagamento", "payment_status", _choices(Sale, "payment_status")),
         "situacao_entrega": Dim("Entrega", "fulfillment_status", _choices(Sale, "fulfillment_status")),
         "cupom": Dim("Cupom", "coupon_code")},
        {"faturamento": Metric("Faturamento", Sum("total")), "quantidade": Metric("Vendas", Count("id"), "number"),
         "ticket_medio": Metric("Ticket médio", Avg("total")), "descontos": Metric(
             "Descontos", Sum(F("discount") + F("coupon_discount"), output_field=MONEY)),
         "frete": Metric("Frete", Sum("freight")), "devolvido": Metric("Devolvido", Sum("refunded_amount"))},
        {"filial": "store", "vendedor": "seller", "operador": "operator", "cliente": "customer", "canal": "channel"},
    ),
    "itens_vendidos": Dataset(
        "Itens vendidos", "Cada produto nas vendas concluídas (com custo e margem).", SaleItem, "reports.view",
        "base", "sale__completed_at", Q(sale__status=Sale.Status.COMPLETED, status=SaleItem.Status.ACTIVE),
        {**_time_dims("sale__completed_at"), "produto": Dim("Produto", "variant__product__name"),
         "variante": Dim("Variante", "description"), "sku": Dim("SKU", "sku"),
         "categoria": Dim("Categoria", "variant__product__category__name"),
         "marca": Dim("Marca", "variant__product__brand__name"), "vendedor": Dim("Vendedor", _person("sale__seller")),
         "filial": Dim("Filial", "sale__store__name")},
        {"quantidade": Metric("Quantidade", Sum("quantity"), "quantity"), "faturamento": Metric("Faturamento", Sum("total")),
         "custo": Metric("Custo", Sum(ITEM_COST)), "margem": Metric("Margem", Sum(F("total") - ITEM_COST, output_field=MONEY)),
         "descontos": Metric("Descontos", Sum("discount")),
         "vendas": Metric("Vendas", Count("sale", distinct=True), "number")},
        {"filial": "sale__store", "vendedor": "sale__seller", "produto": "variant__product",
         "categoria": "variant__product__category", "marca": "variant__product__brand"},
    ),
    "cancelamentos": Dataset(
        "Vendas canceladas", "Vendas canceladas (data = cancelamento), com quem cancelou.", Sale, "reports.view",
        "base", "cancelled_at", Q(status=Sale.Status.CANCELLED),
        {**_time_dims("cancelled_at"), "filial": Dim("Filial", "store__name"),
         "cancelado_por": Dim("Cancelado por", _person("cancelled_by")), "vendedor": Dim("Vendedor", _person("seller")),
         "motivo": Dim("Motivo", "cancel_reason")},
        {"quantidade": Metric("Cancelamentos", Count("id"), "number"), "valor": Metric("Valor", Sum("total"))},
        {"filial": "store", "cancelado_por": "cancelled_by", "vendedor": "seller"},
    ),
    "devolucoes": Dataset(
        "Trocas e devoluções", "Devoluções concluídas.", SaleReturn, "reports.view", "base", "completed_at",
        Q(status=SaleReturn.Status.COMPLETED),
        {**_time_dims("completed_at"), "filial": Dim("Filial", "store__name"),
         "feito_por": Dim("Feita por", _person("processed_by")),
         "reembolso": Dim("Reembolso", "refund_method", _choices(SaleReturn, "refund_method")),
         "motivo": Dim("Motivo", "reason")},
        {"quantidade": Metric("Devoluções", Count("id"), "number"), "valor": Metric("Valor", Sum("total"))},
        {"filial": "store", "feito_por": "processed_by"},
    ),
    "clientes": Dataset(
        "Clientes", "Cadastro de clientes (data = cadastro).", Customer, "partners.view", "base", "created_at", Q(),
        {**_time_dims("created_at"), "tipo_pessoa": Dim("Tipo", "person_type", _choices(Customer, "person_type")),
         "grupo": Dim("Grupo", "groups__name"), "ativo": Dim("Ativo", "is_active", {True: "Sim", False: "Não"}),
         "cadastrado_por": Dim("Cadastrado por", _person("created_by"))},
        {"quantidade": Metric("Clientes", Count("id", distinct=True), "number"),
         "limite_credito": Metric("Limite de crédito", Sum("credit_limit"))},
        {"grupo": "groups", "ativo": "is_active", "cadastrado_por": "created_by"},
    ),
    "produtos": Dataset(
        "Produtos (variantes)", "Cada variante vendável do catálogo (data = cadastro).", ProductVariant,
        "catalog.view", "base", "created_at", Q(product__deleted_at__isnull=True),
        {**_time_dims("created_at"), "produto": Dim("Produto", "product__name"),
         "categoria": Dim("Categoria", "product__category__name"), "marca": Dim("Marca", "product__brand__name"),
         "tipo": Dim("Tipo", "product__type", _choices(Product, "type")),
         "ativo": Dim("Ativo", "is_active", {True: "Sim", False: "Não"}),
         "cadastrado_por": Dim("Cadastrado por", _person("product__created_by"))},
        {"quantidade": Metric("Variantes", Count("id"), "number"), "preco_medio": Metric("Preço médio", Avg("price")),
         "custo_medio": Metric("Custo médio", Avg("average_cost"))},
        {"categoria": "product__category", "marca": "product__brand", "ativo": "is_active"},
    ),
    "estoque": Dataset(
        "Posição de estoque", "Saldo atual por variante e depósito (sem data).", StockBalance, "stock.view", "stock",
        None, Q(variant__deleted_at__isnull=True),
        {"produto": Dim("Produto", "variant__product__name"), "variante": Dim("Variante", "variant__sku"),
         "categoria": Dim("Categoria", "variant__product__category__name"),
         "marca": Dim("Marca", "variant__product__brand__name"), "deposito": Dim("Depósito", "warehouse__name"),
         "filial": Dim("Filial", "warehouse__store__name")},
        {"quantidade": Metric("Quantidade", Sum("quantity"), "quantity"),
         "valor_custo": Metric("Valor a custo", Sum(BALANCE_COST)),
         "valor_venda": Metric("Valor a preço de venda", Sum(BALANCE_PRICE)),
         "itens": Metric("Itens", Count("id"), "number")},
        {"filial": "warehouse__store", "deposito": "warehouse", "categoria": "variant__product__category",
         "marca": "variant__product__brand", "produto": "variant__product"},
    ),
    "alertas": Dataset(
        "Alertas da supervisão", "Erros e desvios apontados pela Cosmos, com quem fez (data = quando apontou). Use "
        "para a QUALIDADE do trabalho de cada pessoa.", CosmosFinding, "cosmos.supervise", "base", "created_at", Q(),
        {**_time_dims("created_at"), "pessoa": Dim("Pessoa", _person("actor")), "regra": Dim("Regra", "rule"),
         "gravidade": Dim("Gravidade", "severity", _choices(CosmosFinding, "severity")),
         "situacao": Dim("Situação", "status", _choices(CosmosFinding, "status")), "filial": Dim("Filial", "store__name")},
        {"quantidade": Metric("Alertas", Count("id"), "number")},
        {"pessoa": "actor", "situacao": "status", "gravidade": "severity", "regra": "rule", "filial": "store"},
    ),
    "precificacao": Dataset(
        "Precificação (preço × mercado)", "Cada produto comparado com o mercado na última leitura (data = "
        "leitura): posição, sugestão de preço pendente e se o custo deixa valer a pena.", PriceCheck, "catalog.view",
        "pricing", "checked_at", Q(),
        {**_time_dims("checked_at"), "produto": Dim("Produto", "variant__product__name"),
         "posicao": Dim("Posição", "position", _choices(PriceCheck, "position")),
         "situacao": Dim("Situação", "status", _choices(PriceCheck, "status")),
         "vale_a_pena": Dim("Vale a pena", "worth_it", {True: "Sim", False: "Não"}),
         "categoria": Dim("Categoria", "variant__product__category__name"),
         "marca": Dim("Marca", "variant__product__brand__name")},
        {"quantidade": Metric("Produtos", Count("id"), "number"),
         "preco_atual": Metric("Preço atual (soma)", Sum("current_price")),
         "mediana_mercado": Metric("Mediana do mercado (soma)", Sum("market_median")),
         "preco_sugerido": Metric("Preço sugerido (soma)", Sum("suggested_price")),
         "indice_medio": Metric("Índice de preço médio", Avg("price_index"), "quantity")},
        {"posicao": "position", "situacao": "status", "vale_a_pena": "worth_it", "produto": "variant__product",
         "categoria": "variant__product__category", "marca": "variant__product__brand"},
    ),
    "contas": Dataset(
        "Contas a pagar e receber", "Parcelas dos títulos (data = vencimento).", Installment, "finance.view",
        "finance", "due_date", Q(title__deleted_at__isnull=True),
        {**_time_dims("due_date", date_only=True), "tipo": Dim("Tipo", "title__kind", _choices(FinancialTitle, "kind")),
         "situacao": Dim("Situação", "status", _choices(Installment, "status")),
         "categoria": Dim("Categoria", "title__category__name"), "cliente": Dim("Cliente", "title__customer__name"),
         "fornecedor": Dim("Fornecedor", "title__supplier__name"), "filial": Dim("Filial", "title__store__name")},
        {"valor": Metric("Valor", Sum("amount")), "pago": Metric("Pago", Sum("paid_amount")),
         "em_aberto": Metric("Em aberto", Sum(OPEN_AMOUNT)), "quantidade": Metric("Parcelas", Count("id"), "number")},
        {"tipo": "title__kind", "situacao": "status", "filial": "title__store", "cliente": "title__customer",
         "fornecedor": "title__supplier", "categoria": "title__category"},
    ),
}


class DatasetError(ValueError):
    pass


class Denied(DatasetError):
    """O usuário não tem a permissão (ou o módulo) para estes dados."""


def available(actor):
    """Os conjuntos que o usuário pode consultar, com medidas, agrupamentos e filtros."""
    out = {}
    for key, ds in DATASETS.items():
        if not _can(actor, ds):
            continue
        out[key] = {"descricao": f"{ds.label}: {ds.description}",
                    "medidas": {k: m.label for k, m in ds.metrics.items()},
                    "agrupamentos": {k: d.label for k, d in ds.dims.items()},
                    "filtros": sorted(ds.filters), "tem_periodo": ds.date_field is not None}
    return out


def _can(actor, ds):
    if ds.module != "base" and not (actor.user.is_superuser or actor.account.has_module(ds.module)):
        return False
    return has_permission_code(actor.user, ds.permission)


DATE_FORMATS = {"mes": "%m/%Y", "semana": "sem. %d/%m/%Y"}


def _label(name, dim, value):
    if value is None or value == "":
        return "(sem)"
    if dim.choices:
        return dim.choices.get(value, str(value))
    if hasattr(value, "strftime"):
        if hasattr(value, "tzinfo") and value.tzinfo is not None:
            value = timezone.localtime(value)
        return value.strftime(DATE_FORMATS.get(name, "%d/%m/%Y"))
    return value


def _number(value, fmt):
    if value is None:
        return 0 if fmt == "number" else Decimal("0")
    if fmt == "number":
        return int(value)
    return Decimal(value).quantize(Decimal("0.01") if fmt == "money" else Decimal("0.001"))


def _period_bounds(date_from, date_to):
    return period({"date_from": date_from or "", "date_to": date_to or ""})


def query(actor, dataset, metrics=None, group_by=None, filters=None, date_from=None, date_to=None,
          order_by=None, limit=50, include_empty=True):
    ds = DATASETS.get(dataset)
    if ds is None:
        raise DatasetError(f"Conjunto desconhecido: {dataset}. Opções: {', '.join(DATASETS)}.")
    if not _can(actor, ds):
        raise Denied(f"Você não tem permissão para ver {ds.label.lower()}.")
    metrics = [m for m in (metrics or []) if m] or [next(iter(ds.metrics))]
    group_by = [g for g in (group_by or []) if g][:2]
    for name in metrics:
        if name not in ds.metrics:
            raise DatasetError(f"Medida '{name}' não existe em {dataset}. Opções: {', '.join(ds.metrics)}.")
    for name in group_by:
        if name not in ds.dims:
            raise DatasetError(f"Agrupamento '{name}' não existe em {dataset}. Opções: {', '.join(ds.dims)}.")

    qs = ds.model.objects.filter(ds.base)
    if actor.store is not None:
        q = store_scope_q(ds.model, [actor.store.pk])
        qs = qs.filter(q) if q is not None else qs
    start = end = None
    if ds.date_field:
        start, end = _period_bounds(date_from, date_to)
        bounds = (start.date(), end.date()) if ds.date_field == "due_date" else (start, end)
        qs = qs.filter(**{f"{ds.date_field}__range": bounds})
    for name, value in (filters or {}).items():
        if name not in ds.filters:
            raise DatasetError(f"Filtro '{name}' não existe em {dataset}. Opções: {', '.join(ds.filters)}.")
        path = ds.filters[name]
        qs = qs.filter(**{f"{path}__in": value} if isinstance(value, list) else {path: value})

    annotations = {f"g{i}": (F(ds.dims[g].expr) if isinstance(ds.dims[g].expr, str) else ds.dims[g].expr)
                   for i, g in enumerate(group_by)}
    aggregates = {m: ds.metrics[m].expr for m in metrics}
    if group_by:
        rows = qs.annotate(**annotations).values(*annotations).annotate(**aggregates)
        time_first = group_by[0] in TIME_DIMS or group_by[0] in {"hora", "dia_da_semana"}
        if order_by in metrics:
            rows = rows.order_by(f"-{order_by}")
        elif time_first:
            rows = rows.order_by("g0")
        else:
            rows = rows.order_by(f"-{metrics[0]}")
        rows = list(rows[: min(int(limit or 50), MAX_ROWS)])
    else:
        rows = [qs.aggregate(**aggregates)]

    out = []
    for row in rows:
        item = {g: _label(g, ds.dims[g], row.get(f"g{i}")) for i, g in enumerate(group_by)}
        item.update({m: _number(row.get(m), ds.metrics[m].format) for m in metrics})
        out.append(item)
    if include_empty and group_by == ["filial"]:
        out += _empty_stores(actor, ds, metrics, filters, {row["filial"] for row in out})
    columns = ([{"key": g, "label": ds.dims[g].label} for g in group_by]
               + [{"key": m, "label": ds.metrics[m].label, "format": ds.metrics[m].format} for m in metrics])
    return {"dataset": dataset, "title": ds.label, "columns": columns, "rows": out,
            "period": {"from": str(start.date()), "to": str(end.date())} if start else None}


def _empty_stores(actor, ds, metrics, filters, seen):
    """Por filial: a filial sem movimento entra zerada (senão some do relatório e ninguém percebe)."""
    from starrp.services.store_access import visible_stores

    stores = visible_stores(actor.account, actor.store)
    wanted = (filters or {}).get("filial")
    if wanted:
        wanted = {str(w) for w in (wanted if isinstance(wanted, list) else [wanted])}
        stores = [s for s in stores if str(s.pk) in wanted]
    zero = {m: _number(0, ds.metrics[m].format) for m in metrics}
    return [{"filial": s.name, **zero} for s in stores if s.name not in seen]


def previous_window(date_from, date_to):
    """O período imediatamente anterior, do mesmo tamanho (para a variação dos indicadores)."""
    start, end = _period_bounds(date_from, date_to)
    days = (end.date() - start.date()).days + 1
    prev_end = start.date() - timedelta(days=1)
    return str(prev_end - timedelta(days=days - 1)), str(prev_end)


def today():
    return timezone.localdate()
