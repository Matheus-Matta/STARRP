"""Tarefas da Cosmos: a varredura periódica da supervisão (cancelamentos, estoque negativo, caixa)
e o resumo diário da equipe para quem supervisiona (com a limpeza dos anexos que nunca foram enviados)."""
from celery import shared_task

from starrp.models import Account
from starrp.services.cosmos import attachments, digest, supervision


@shared_task(name="starrp.cosmos_supervision")
def cosmos_supervision(account_id=None):
    account = Account.objects.filter(pk=account_id).first() if account_id else None
    if account_id and account is None:
        return {"opened": 0}
    return {"opened": supervision.sweep(account)}


@shared_task(name="starrp.cosmos_daily_digest")
def cosmos_daily_digest():
    return {"sent": digest.run(), "attachments_purged": attachments.purge()}
