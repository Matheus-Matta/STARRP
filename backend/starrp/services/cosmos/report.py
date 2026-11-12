"""Relatórios da Cosmos: no MESMO formato do livro de relatórios (`report_book`), então o widget
desenha com os mesmos gráficos da tela de relatórios e o Excel sai pelo mesmo exportador.

Dois caminhos:

- `from_book(actor, "vendas", params)`: um relatório pronto do livro (números iguais aos da tela);
- `build(actor, spec)`: um relatório montado na conversa. O modelo descreve os indicadores e os
  blocos (conjunto, medida, agrupamento, tipo de gráfico) e o servidor calcula tudo:

    {"title": "Vendas de outubro", "date_from": "2026-10-01", "date_to": "2026-10-31",
     "kpis": [{"label": "Faturamento", "dataset": "vendas", "metric": "faturamento"}],
     "blocks": [{"type": "bars", "title": "Por vendedor", "dataset": "vendas",
                 "metrics": ["faturamento"], "group_by": ["vendedor"]}]}

Terceiro caminho, quando nada acima cobre o pedido (atividade da equipe, uma lista consultada na API):
`free(actor, spec)` monta o relatório com os números que a Cosmos JÁ levantou nesta conversa — ela copia
os valores dos resultados das ferramentas; o servidor só confere o formato (número é número, séries do
tamanho do eixo) e desenha igual aos outros.

Os três viram um `CosmosReport` (o retrato fica salvo: baixar amanhã dá o mesmo arquivo).
"""
import json
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from django.utils.text import slugify

from starrp.core.permissions import has_permission_code
from starrp.core.text import decimals_as_text
from starrp.models import CosmosReport
from starrp.services import report_book, report_export
from starrp.services.cosmos import datasets

CHARTS = {"line", "bars", "share", "ranking", "table"}
OTHERS = "Outros"
SERIES_MAX = 6


class ReportError(ValueError):
    pass


def book_catalog(actor):
    """Relatórios prontos do livro que o usuário pode abrir: {slug: título}."""
    out = {}
    for slug, (_handler, permission, module) in report_book.BOOK.items():
        if module != "base" and not actor.account.has_module(module):
            continue
        if has_permission_code(actor.user, permission):
            out[slug] = slug.replace("-", " ")
    return out


def from_book(actor, slug, params, conversation=None):
    if slug not in report_book.BOOK:
        raise ReportError(f"Relatório desconhecido. Opções: {', '.join(report_book.BOOK)}.")
    handler, permission, module = report_book.BOOK[slug]
    if not has_permission_code(actor.user, permission) or (module != "base" and not actor.account.has_module(module)):
        raise datasets.Denied("Você não tem permissão para ver este relatório.")
    data = decimals_as_text(handler(actor.account, actor.store, params))
    return _save(actor, data, conversation, slug=slug)


def _kpi(actor, spec, date_from, date_to):
    dataset, metric = spec.get("dataset"), spec.get("metric")
    filters = spec.get("filters") or {}
    now = datasets.query(actor, dataset, [metric], [], filters, date_from, date_to)
    ds = datasets.DATASETS[dataset]
    value, fmt = now["rows"][0][metric], ds.metrics[metric].format
    previous = None
    if ds.date_field:
        prev_from, prev_to = datasets.previous_window(date_from, date_to)
        previous = datasets.query(actor, dataset, [metric], [], filters, prev_from, prev_to)["rows"][0][metric]
    kpi = report_book.kpi(spec.get("label") or ds.metrics[metric].label, value, fmt, previous=previous,
                          good=spec.get("good", "up"), hint=spec.get("hint", ""))
    return kpi


def _series_block(block, result, metrics, group_by, ds):
    """Linha/barras: o 1º agrupamento é o eixo; o 2º (se houver) vira uma série por valor."""
    rows = result["rows"]
    x_key = group_by[0]
    xs = list(dict.fromkeys(str(r[x_key]) for r in rows))
    if len(group_by) == 1:
        series = [{"name": ds.metrics[m].label, "values": [r[m] for r in rows]} for m in metrics]
    else:
        metric, split = metrics[0], group_by[1]
        totals = {}
        for r in rows:
            totals[str(r[split])] = totals.get(str(r[split]), 0) + Decimal(str(r[metric]))
        top = [name for name, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:SERIES_MAX]]
        grid = {name: dict.fromkeys(xs, Decimal("0")) for name in [*top, OTHERS]}
        for r in rows:
            name = str(r[split]) if str(r[split]) in top else OTHERS
            grid[name][str(r[x_key])] += Decimal(str(r[metric]))
        series = [{"name": name, "values": list(values.values())} for name, values in grid.items()
                  if name != OTHERS or any(values.values())]
        block["stacked"] = block.get("stacked", block["type"] == "bars")
    block.update({"x": xs, "series": series, "format": ds.metrics[metrics[0]].format})
    return block


def _block(actor, spec, date_from, date_to):
    kind = spec.get("type")
    if kind not in CHARTS:
        raise ReportError(f"Tipo de bloco '{kind}' não existe. Opções: {', '.join(sorted(CHARTS))}.")
    dataset = spec.get("dataset")
    ds = datasets.DATASETS.get(dataset)
    if ds is None:
        raise ReportError(f"Conjunto '{dataset}' não existe.")
    metrics = [m for m in spec.get("metrics") or [] if m] or [next(iter(ds.metrics))]
    group_by = [g for g in spec.get("group_by") or [] if g][:2]
    if kind != "table" and not group_by:
        raise ReportError(f"O bloco '{spec.get('title')}' ({kind}) precisa de um agrupamento.")
    result = datasets.query(actor, dataset, metrics, group_by, spec.get("filters") or {}, date_from, date_to,
                            order_by=spec.get("order_by"), limit=spec.get("limit") or (500 if kind == "table" else 50),
                            include_empty=spec.get("include_empty") is not False)
    block = {"type": kind, "title": spec.get("title") or result["title"], "description": spec.get("description", ""),
             "span": spec.get("span") or ("full" if kind in ("line", "table") else "half")}
    if kind in ("line", "bars"):
        return _series_block(block, result, metrics, group_by, ds)
    if kind in ("share", "ranking"):
        metric = metrics[0]
        block["format"] = ds.metrics[metric].format
        block["rows"] = [{"label": str(r[group_by[0]]), "value": r[metric]} for r in result["rows"]]
        return block
    block["columns"] = result["columns"]
    block["rows"] = result["rows"]
    return block


def build(actor, spec, conversation=None):
    date_from, date_to = spec.get("date_from"), spec.get("date_to")
    start, end = datasets._period_bounds(date_from, date_to)
    date_from, date_to = str(start.date()), str(end.date())
    kpis = [_kpi(actor, k, date_from, date_to) for k in (spec.get("kpis") or [])[:8]]
    blocks = [_block(actor, b, date_from, date_to) for b in (spec.get("blocks") or [])[:10]]
    if not kpis and not blocks:
        raise ReportError("O relatório precisa de ao menos um indicador ou bloco.")
    data = decimals_as_text({"title": spec.get("title") or "Relatório da Cosmos", "subtitle": spec.get("subtitle", ""),
                             "period": {"from": date_from, "to": date_to}, "grain": "day", "filters": [],
                             "kpis": kpis, "blocks": blocks})
    return _save(actor, data, conversation)


FORMATS = {"money", "number", "decimal", "quantity", "percent", "text"}
FREE_ROWS = 500


def _num(value, where):
    try:
        return Decimal(str(value).replace(" ", ""))
    except ArithmeticError as error:
        raise ReportError(f"{where}: '{value}' não é número (use ponto decimal, ex.: 1234.50).") from error


def _value(value, fmt, where):
    """Número do relatório livre: contagem inteira sai inteira ("10", não "10.00")."""
    number = _num(value, where)
    return int(number) if fmt == "number" and number == number.to_integral_value() else number


def _fmt(value):
    return value if value in FORMATS else "number"


def _free_block(spec):
    kind = spec.get("tipo")
    if kind not in CHARTS:
        raise ReportError(f"Tipo de bloco '{kind}' não existe. Opções: {', '.join(sorted(CHARTS))}.")
    title = str(spec.get("titulo") or "Bloco")[:120]
    fmt = _fmt(spec.get("formato"))
    block = {"type": kind, "title": title, "description": str(spec.get("descricao") or "")[:300],
             "span": spec.get("largura") or ("full" if kind in ("line", "table") else "half"), "format": fmt}
    if kind in ("line", "bars"):
        xs = [str(x)[:40] for x in (spec.get("eixo") or [])][:FREE_ROWS]
        series = []
        for serie in (spec.get("series") or [])[:SERIES_MAX + 1]:
            values = serie.get("valores") or []
            if len(values) != len(xs):
                raise ReportError(f"'{title}': a série '{serie.get('nome')}' tem {len(values)} valores e o eixo "
                                  f"{len(xs)} pontos.")
            series.append({"name": str(serie.get("nome") or "Série")[:60],
                           "values": [_value(v, fmt, title) for v in values]})
        if not xs or not series:
            raise ReportError(f"'{title}': informe o eixo e ao menos uma série.")
        block.update({"x": xs, "series": series, "stacked": bool(spec.get("empilhado"))})
    elif kind in ("share", "ranking"):
        rows = [{"label": str(r.get("rotulo"))[:80], "value": _value(r.get("valor"), fmt, title),
                 **({"sub": str(r["detalhe"])[:120]} if r.get("detalhe") else {})}
                for r in (spec.get("linhas") or [])[:FREE_ROWS]]
        if not rows:
            raise ReportError(f"'{title}': informe as linhas (rotulo e valor).")
        block["rows"] = rows
    else:
        columns = [{"key": str(c.get("chave")), "label": str(c.get("rotulo") or c.get("chave"))[:60],
                    "format": _fmt(c.get("formato")) if c.get("formato") != "text" else "text"}
                   for c in (spec.get("colunas") or []) if c.get("chave")]
        if not columns:
            raise ReportError(f"'{title}': informe as colunas da tabela.")
        rows = []
        for row in (spec.get("linhas") or [])[:FREE_ROWS]:
            rows.append({c["key"]: (_value(row.get(c["key"]), c["format"], title) if c["format"] != "text"
                                    and row.get(c["key"]) not in (None, "") else row.get(c["key"]))
                         for c in columns})
        block.update({"columns": columns, "rows": rows})
    return block


def free(actor, spec, conversation=None):
    """Relatório com os dados que a Cosmos já levantou (ver o topo do arquivo)."""
    kpis = []
    for k in (spec.get("indicadores") or [])[:8]:
        fmt = _fmt(k.get("formato"))
        value = k.get("valor") if fmt == "text" else _value(k.get("valor"), fmt, str(k.get("rotulo")))
        kpis.append(report_book.kpi(str(k.get("rotulo") or "Indicador")[:60], value, fmt,
                                    good=k.get("bom", "up"), hint=str(k.get("dica") or "")[:120]))
    blocks = [_free_block(b) for b in (spec.get("blocos") or [])[:10]]
    if not kpis and not blocks:
        raise ReportError("O relatório precisa de ao menos um indicador ou bloco.")
    start, end = datasets._period_bounds(spec.get("data_inicial"), spec.get("data_final"))
    subtitle = spec.get("subtitulo") or "Montado pela Cosmos com os dados consultados nesta conversa."
    data = decimals_as_text({"title": str(spec.get("titulo") or "Relatório da Cosmos")[:200], "subtitle": subtitle,
                             "period": {"from": str(start.date()), "to": str(end.date())}, "grain": "day",
                             "filters": [], "kpis": kpis, "blocks": blocks})
    return _save(actor, data, conversation)


def _save(actor, data, conversation, slug=""):
    data = json.loads(json.dumps(data, cls=DjangoJSONEncoder))  # datas e decimais viram texto (JSON)
    return CosmosReport.all_objects.create(account=actor.account, conversation=conversation, slug=slug,
                                           title=data["title"][:200], data=data, store=actor.store,
                                           created_by=actor.user, updated_by=actor.user)


def summary_for_model(report):
    """O que volta ao modelo: os indicadores e as primeiras linhas de cada bloco (ele comenta)."""
    data = report.data
    lines = [f"Relatório '{data['title']}' ({data['period']['from']} a {data['period']['to']}) pronto e já mostrado "
             f"ao usuário com gráficos e botão de baixar (id {report.pk})."]
    for k in data.get("kpis", []):
        delta = f" ({k['delta']}% vs. anterior)" if k.get("delta") not in (None, "") else ""
        lines.append(f"- {k['label']}: {k['value']}{delta}")
    for b in data.get("blocks", [])[:8]:
        if b["type"] in ("share", "ranking", "table"):
            head = b.get("rows", [])[:5]
            lines.append(f"- {b['title']}: {head}")
        elif b["type"] in ("line", "bars"):
            lines.append(f"- {b['title']}: {len(b.get('x', []))} pontos, séries {[s['name'] for s in b.get('series', [])]}")
    return "\n".join(lines)[:4000]


def export(report, user, formato="xlsx"):
    """(conteúdo, content-type, nome do arquivo) do relatório salvo."""
    data = report.data
    if formato == "csv":
        content, kind, ext = report_export.to_csv(data), "text/csv; charset=utf-8", "csv"
    else:
        context = {"store": getattr(report.store, "name", None), "filters": "",
                   "user": user.get_full_name() or user.username,
                   "issued": timezone.localtime().strftime("%d/%m/%Y %H:%M")}
        content = report_export.to_xlsx(data, context, charts=True)
        kind, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    name = report_export.filename(slugify(report.title)[:60] or "relatorio", data, ext)
    return content, kind, name
