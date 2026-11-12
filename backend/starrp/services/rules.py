"""Regras compartilhadas entre filiais (models/rules.py): a padrão de cada tipo e a da filial."""
from starrp.models import LogisticsRule, StockRule, StoreRule

DEFAULT_NAME = "Padrão"


def store_rule_fields():
    """FK de `Store` → modelo da regra."""
    return {"rule": StoreRule, "logistics_rule": LogisticsRule, "stock_rule": StockRule}


def default(model, account_id):
    """A regra padrão da conta; não existe (conta antiga, banco novo), nasce agora."""
    found = model.all_objects.filter(account_id=account_id, is_default=True, deleted_at__isnull=True).first()
    if found is not None:
        return found
    name, n = DEFAULT_NAME, 1
    while model.all_objects.filter(account_id=account_id, name=name, deleted_at__isnull=True).exists():
        n += 1
        name = f"{DEFAULT_NAME} {n}"
    return model.all_objects.create(account_id=account_id, name=name, is_default=True)


def ensure_defaults(account_id):
    """Uma regra padrão de cada tipo (chamado ao criar a conta)."""
    return {field: default(model, account_id) for field, model in store_rule_fields().items()}


def of_store(field, store_id, account_id):
    """A regra da filial (`field` = "rule", "logistics_rule" ou "stock_rule"); sem filial, a padrão."""
    from starrp.models import Store

    model = store_rule_fields()[field]
    if store_id is not None:
        rule_id = Store.all_objects.filter(pk=store_id).values_list(f"{field}_id", flat=True).first()
        if rule_id is not None:
            return model.all_objects.get(pk=rule_id)
    return default(model, account_id)
