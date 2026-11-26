"""Custo e margem: só quem tem `catalog.view_costs`.

O operador de caixa e o vendedor veem produto, preço e venda, mas não quanto a loja pagou nem quanto
ganha. Três lugares aplicam a regra, todos daqui:

- `HideCostFieldsMixin` nos serializers (variante, item de venda, precificação, produto do fornecedor):
  sem a permissão, os campos de custo somem da resposta e são ignorados na gravação;
- `redact_report` nos relatórios (tela e Excel): somem colunas, métricas, KPIs, séries e as opções
  de "classificar por margem";
- a Cosmos (`services/cosmos/datasets.py`): medida de custo/margem exige a permissão.
"""
import re

from starrp.core.permissions import has_permission_code

PERMISSION = "catalog.view_costs"

# Chave de dado de custo/margem/lucro (nomes em inglês, separados por "_"): "cost", "unit_cost",
# "margin_pct", "n_profit_day", "gross_margin"... e NÃO "customer", "customers".
COST_KEY = re.compile(r"(^|_)(cost|costs|margin|profit|markup|cmv|loss|losses|result)(_|$)")
# Texto visível (rótulo de KPI, coluna, série, opção, título de bloco).
COST_LABEL = re.compile(r"\b(custos?|margem|margens|lucros?|cmv|markup|prejuízos?|resultado|perda de)\b", re.IGNORECASE)


def sees_costs(user):
    return bool(user and user.is_authenticated) and has_permission_code(user, PERMISSION)


def _user_of(serializer):
    request = serializer.context.get("request") if isinstance(serializer.context, dict) else None
    return getattr(request, "user", None)


class HideCostFieldsMixin:
    """Serializer com `cost_fields = (...)`: sem `catalog.view_costs`, eles não saem nem entram.

    Sem requisição no contexto (tarefa, comando, serviço interno) mostra tudo: a regra é de tela."""

    cost_fields = ()

    def _hides_costs(self):
        request = self.context.get("request") if isinstance(self.context, dict) else None
        if request is None:
            return False
        memo = self.context.setdefault("_hides_costs", {})
        user = _user_of(self)
        key = getattr(user, "pk", None)
        if key not in memo:
            memo[key] = not sees_costs(user)
        return memo[key]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.cost_fields and self._hides_costs():
            for name in self.cost_fields:
                data.pop(name, None)
        return data

    def to_internal_value(self, data):
        if self.cost_fields and self._hides_costs() and hasattr(data, "items"):
            data = {key: value for key, value in data.items() if key not in self.cost_fields}
        return super().to_internal_value(data)


def _is_cost_entry(entry):
    """Coluna/métrica/série/KPI/opção de custo: pela chave ou pelo rótulo."""
    if not isinstance(entry, dict):
        return False
    if entry.get("cost") is True:  # o próprio relatório diz: "Valor em estoque" é custo, sem a palavra no rótulo
        return True
    for field in ("key", "value_key"):
        value = entry.get(field)
        if isinstance(value, str) and COST_KEY.search(value):
            return True
    for field in ("label", "name", "title"):
        value = entry.get(field)
        if isinstance(value, str) and COST_LABEL.search(value):
            return True
    return False


#: Textos livres do relatório (o número do custo/margem aparecia neles, R5-06).
TEXT_KEYS = ("hint", "sub", "description", "subtitle", "text", "note", "empty")


def _clean_row(row, hidden=()):
    if not isinstance(row, dict):
        return row
    out = {k: v for k, v in row.items() if not COST_KEY.search(str(k)) and k not in hidden}
    for key in TEXT_KEYS:
        if isinstance(out.get(key), str) and COST_LABEL.search(out[key]):
            out[key] = ""
    return out


def _clean_rows(rows, hidden=()):
    """Linhas sem as que SÃO de custo (na DRE o custo é uma linha: "CMV", "Lucro bruto", "Resultado")."""
    return [_clean_row(row, hidden) for row in rows if not _is_cost_entry(row)
            and not (isinstance(row, dict) and COST_LABEL.search(str(row.get("text") or "")))]


def _redact_block(block):
    """Bloco de relatório sem as partes de custo; `None` quando ele era SÓ sobre custo/margem."""
    if not isinstance(block, dict):
        return block
    if block.get("cost") is True:
        return None
    block = dict(block)
    hidden = {entry.get("key") for name in ("columns", "metrics") for entry in block.get(name) or []
              if _is_cost_entry(entry)}
    title_is_cost = isinstance(block.get("title"), str) and COST_LABEL.search(block["title"])
    for list_key in ("columns", "metrics", "series"):
        if isinstance(block.get(list_key), list):
            kept = [entry for entry in block[list_key] if not _is_cost_entry(entry)]
            if block[list_key] and not kept:
                return None  # tabela/gráfico que só mostrava custo/margem
            block[list_key] = kept
    if title_is_cost and not any(block.get(k) for k in ("columns", "metrics")):
        return None  # gráfico de margem (ex.: "Margem bruta por categoria")
    if title_is_cost:
        return None
    for list_key in ("rows", "steps", "items", "facts", "insights"):
        if isinstance(block.get(list_key), list):
            block[list_key] = _clean_rows(block[list_key], hidden)
    # Só o que a tela mostra: chave extra na linha (a parte do lucro de cada sócio) não viaja escondida.
    shown = [e for name in ("columns", "metrics") for e in block.get(name) or [] if isinstance(e, dict)]
    if shown and isinstance(block.get("rows"), list):
        tab = (block.get("tabs") or {}).get("key") if isinstance(block.get("tabs"), dict) else None
        keep = {e.get("key") for e in shown} | {"label", "group", "strong", "link", "id", tab}
        block["rows"] = [{k: v for k, v in row.items() if k in keep} if isinstance(row, dict) else row
                         for row in block["rows"]]
    block = _clean_row(block)
    if isinstance(block.get("value_key"), str) and COST_KEY.search(block["value_key"]):
        return None
    return block


def redact_report(data):
    """Relatório (dicionário de `services/reports` ou `report_book`) sem custo nem margem."""
    if isinstance(data, list):
        return [_clean_row(row) for row in data]
    if not isinstance(data, dict):
        return data
    out = {}
    for key, value in data.items():
        if COST_KEY.search(str(key)):
            continue
        if key == "kpis" and isinstance(value, list):
            out[key] = _clean_rows(value)
        elif key == "blocks" and isinstance(value, list):
            out[key] = [block for block in map(_redact_block, value) if block is not None]
        elif key == "filters" and isinstance(value, list):
            out[key] = [_redact_filter(f) for f in value]
        elif isinstance(value, list):
            out[key] = [redact_report(row) if isinstance(row, dict) else row for row in value
                        if not (isinstance(row, dict) and COST_LABEL.search(str(row.get("text") or "")))]
        elif isinstance(value, dict):
            out[key] = redact_report(value)
        elif key in TEXT_KEYS and isinstance(value, str) and COST_LABEL.search(value):
            out[key] = ""
        else:
            out[key] = value
    return out


def _redact_filter(item):
    if isinstance(item, dict) and isinstance(item.get("options"), list):
        item = {**item, "options": [o for o in item["options"] if not _is_cost_entry(o)
                                    and not (isinstance(o, dict) and COST_KEY.search(str(o.get("value", ""))))]}
    return item


def cost_measure_requested(params):
    """`?measure=margin` (curva ABC por margem) sem a permissão é recusado na view."""
    return bool(COST_KEY.search(str(params.get("measure", "") or "")))
