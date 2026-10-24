"""Histórico de alterações em TODAS as models (django-simple-history), como no StarHub.

Cada `save()` — pela API, pelos serviços (venda, estoque, caixa), pelo admin, por uma
tarefa ou pelo shell — grava uma linha em `Historical<Model>` com o retrato do registro,
quem fez (`history_user`) e quando. A exclusão lógica (`deleted_at`) também entra.

Em vez de `HistoricalRecords(inherit=True)` no modelo base (que não deixa uma model
ficar de fora), `track_history` registra toda subclasse concreta de `TimeStampedModel`
menos as de SKIP — model nova ganha histórico sozinha. Ficam de fora o que já é log ou
razão (nunca muda depois de gravado) e o que muda a cada venda/movimento (saldo,
contador): histórico ali só multiplicaria o banco sem dizer nada novo.

Não passa pelo histórico: `QuerySet.update()` e `bulk_create` (não chamam `save()`).
"""
from simple_history import register

SKIP = {
    # Já são registro de acontecimento (imutáveis).
    "AuditLog", "StockMovement", "ScaleReading", "Notification", "PrintJob", "ImportJob",
    "IdempotencyRecord", "NFeEvent",
    # Mudam a cada venda/movimento/sincronização: o histórico está nos movimentos.
    "StockBalance", "BinBalance", "NumberSequence", "DFeSyncState",
    # Sincronização (fila e controle técnico) e cache público de CEP.
    "SyncEvent", "SyncRun", "SyncConflict", "SyncDiscard", "SyncDirty", "SyncFileTransfer", "SyncEnrollmentTicket",
    "SyncNode", "ZipCoordinate", "ZipDistance",
    # Segurança: o token de redefinição de senha não deve ficar copiado.
    "PasswordResetRequest", "FirstAccessState",
}


def history_user(instance=None, request=None, **kwargs):
    """Quem fez: o usuário da requisição; fora dela (tarefa, shell), o `updated_by` do registro."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return getattr(instance, "updated_by", None) or getattr(instance, "created_by", None)


def _concrete(base):
    for sub in base.__subclasses__():
        yield from _concrete(sub)
        meta = getattr(sub, "_meta", None)
        if meta is not None and not meta.abstract and not meta.proxy:
            yield sub


def track_history(base):
    tracked = []
    for model in dict.fromkeys(_concrete(base)):
        if model.__name__ in SKIP or model.__name__.startswith("Historical") or hasattr(model, "history"):
            continue
        register(model, app="starrp", get_user=history_user, cascade_delete_history=False)
        tracked.append(model.__name__)
    return tracked
