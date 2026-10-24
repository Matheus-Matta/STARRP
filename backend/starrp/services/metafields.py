"""Metacampos: valida `metafields` contra as definições e monta a ficha técnica.

    clean(account_id, "product", {"tempo_montagem": "2", "obs": "x"}, category=cat)
        -> {"tempo_montagem": 2, "obs": "x"}   (definida: convertida; livre: texto como veio)
    specs(product) -> [{"key", "label", "value", "text"}]  (só as `show_in_specs` preenchidas)

Chave definida recebe o tipo da definição (número, sim/não, data, opção da lista); erro
volta no formato do DRF ({"metafields": {"chave": "mensagem"}}). Chave sem definição
é guardada como texto — é o metacampo livre do StarHub (integração, anotação).
"""
import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from starrp.models import Category, MetafieldDefinition

KEY = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,59}$")


def definitions(account_id, owner, category=None):
    qs = (MetafieldDefinition.all_objects
          .filter(account_id=account_id, owner=owner, is_active=True, deleted_at__isnull=True)
          .prefetch_related("categories").order_by("position", "name"))
    if owner != MetafieldDefinition.Owner.PRODUCT:
        return list(qs)
    lineage = _lineage(category)
    return [d for d in qs if not d.categories.all() or {c.pk for c in d.categories.all()} & lineage]


def _lineage(category):
    """A categoria e as de cima (a definição de "Móveis" vale para "Quarto")."""
    ids, current, depth = set(), category, 0
    while current is not None and depth < 6:
        ids.add(current.pk)
        current = Category.all_objects.filter(pk=current.parent_id).first() if current.parent_id else None
        depth += 1
    return ids


def _convert(definition, value):
    kind = MetafieldDefinition.Type
    if definition.type == kind.NUMBER:
        try:
            number = Decimal(str(value).replace(",", "."))
        except InvalidOperation:
            raise ValueError("Informe um número.") from None
        return int(number) if number == number.to_integral_value() else float(number)
    if definition.type == kind.BOOLEAN:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "sim", "s", "yes"}:
            return True
        if text in {"0", "false", "não", "nao", "n", "no"}:
            return False
        raise ValueError("Use sim ou não.")
    if definition.type == kind.DATE:
        try:
            return dt.date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            raise ValueError("Data inválida (AAAA-MM-DD).") from None
    text = str(value).strip()
    if definition.type == kind.SELECT and definition.options and text not in definition.options:
        raise ValueError(f"Escolha uma das opções: {', '.join(map(str, definition.options))}.")
    return text


def clean(account_id, owner, data, category=None):
    if data in (None, ""):
        data = {}
    if not isinstance(data, dict):
        raise ValidationError({"metafields": "Envie um objeto {chave: valor}."})
    defined = {d.key: d for d in definitions(account_id, owner, category)}
    out, errors = {}, {}
    for key, value in data.items():
        key = str(key).strip()
        if not KEY.match(key):
            errors[key or "?"] = "Chave com letras minúsculas, números, _ ou - (até 60)."
            continue
        if value is None or value == "":
            continue  # vazio = sem o metacampo
        definition = defined.get(key)
        if definition is None:
            out[key] = value if isinstance(value, (bool, int, float)) else str(value)
            continue
        try:
            out[key] = _convert(definition, value)
        except ValueError as error:
            errors[key] = f"{definition.name}: {error}"
    for key, definition in defined.items():
        if definition.required and key not in out and key not in errors:
            errors[key] = f"{definition.name} é obrigatório."
    if errors:
        raise ValidationError({"metafields": errors})
    return out


def display(definition, value):
    if definition.type == MetafieldDefinition.Type.BOOLEAN:
        text = "Sim" if value else "Não"
    elif definition.type == MetafieldDefinition.Type.DATE:
        text = dt.date.fromisoformat(value).strftime("%d/%m/%Y")
    elif definition.type == MetafieldDefinition.Type.NUMBER:
        text = f"{value}".replace(".", ",")
    else:
        text = str(value)
    return f"{text} {definition.unit}".strip() if definition.unit and definition.type != "boolean" else text


def specs(product):
    """Ficha técnica: os metacampos definidos com `show_in_specs`, na ordem da definição."""
    values = product.metafields or {}
    out = []
    for definition in definitions(product.account_id, MetafieldDefinition.Owner.PRODUCT, product.category):
        value = values.get(definition.key)
        if definition.show_in_specs and value not in (None, ""):
            out.append({"key": definition.key, "label": definition.name, "value": value,
                        "text": display(definition, value)})
    return out
