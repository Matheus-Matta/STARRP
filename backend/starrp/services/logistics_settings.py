"""Configuração de logística por filial: sempre existe uma (criada na primeira leitura)."""
from starrp.models import LogisticsSettings, Store


def for_store(store_id):
    """A configuração da filial; sem filial (consulta da conta), a padrão (tudo desligado)."""
    if store_id is None:
        return LogisticsSettings()
    found = LogisticsSettings.all_objects.filter(store_id=store_id, deleted_at__isnull=True).first()
    if found is not None:
        return found
    store = Store.all_objects.get(pk=store_id)
    return LogisticsSettings.all_objects.create(account_id=store.account_id, store=store)


def ensure_all(account_id):
    """Uma configuração para cada filial da conta (a lista mostra todas)."""
    have = set(LogisticsSettings.all_objects.filter(account_id=account_id, deleted_at__isnull=True)
               .values_list("store_id", flat=True))
    for store_id in Store.all_objects.filter(account_id=account_id, deleted_at__isnull=True).values_list("pk", flat=True):
        if store_id not in have:
            for_store(store_id)
