"""Limites e consumo da Cosmos por conta (tokens da OpenAI).

Os limites são da plataforma e ficam na conta, editados só no admin do Django:
o módulo `cosmos`, `cosmos_enabled` e três tetos independentes — por dia, por semana (segunda a domingo) e por mês
civil; 0 = sem limite naquele período. Vale o primeiro que estourar.

    diário 50.000 · semanal 0 · mensal 1.000.000
    → no máximo 50 mil por dia, e o mês para em 1 milhão mesmo que todo dia fique abaixo dos 50 mil.

Cada chamada ao modelo soma o que a OpenAI informou na linha do DIA (`CosmosUsage`); semana e
mês são a soma dos dias. Antes de cada chamada, `blocked` confere o saldo (uma resposta em
andamento pode passar um pouco do limite: a conferência é por chamada, não por token).
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from starrp.models import Account, CosmosUsage

DISABLED = "A Cosmos não está disponível para a sua empresa. Fale com o suporte do Starrp."
# período → (campo do limite, rótulo, quando volta)
PERIODS = {
    "day": ("cosmos_daily_tokens", "diário", "amanhã"),
    "week": ("cosmos_weekly_tokens", "semanal", "na segunda-feira"),
    "month": ("cosmos_monthly_tokens", "mensal", "no dia 1º do próximo mês"),
}


def exhausted(period):
    _field, label, back = PERIODS[period]
    return (f"A sua empresa já usou todo o limite {label} da Cosmos. O uso volta {back}; "
            "para ampliar, fale com o suporte do Starrp.")


def window_start(period, today=None):
    today = today or timezone.localdate()
    if period == "week":
        return today - timedelta(days=today.weekday())
    if period == "month":
        return today.replace(day=1)
    return today


def spent(account, period="month"):
    """Tokens gastos no período corrente (dia, semana ou mês)."""
    total = (CosmosUsage.objects.filter(account_id=account.pk, day__gte=window_start(period))
             .aggregate(t=Sum("total_tokens"))["t"])
    return total or 0


def limits(account):
    """[(período, limite, gasto)] só dos limites ligados (> 0)."""
    active = [(period, getattr(account, field))
              for period, (field, _label, _back) in PERIODS.items() if getattr(account, field)]
    if not active:
        return []
    totals = CosmosUsage.objects.filter(account_id=account.pk).aggregate(**{
        f"spent_{period}": Sum("total_tokens", filter=Q(day__gte=window_start(period)))
        for period, _limit in active
    })
    return [(period, limit, totals.get(f"spent_{period}") or 0) for period, limit in active]


def blocked(account):
    """Mensagem para o usuário se a conta não pode usar a Cosmos agora; senão `None`."""
    account = Account.objects.get(pk=account.pk)  # o admin pode ter mudado agora
    if not account.cosmos_active:
        return DISABLED
    for period, limit, used in limits(account):
        if used >= limit:
            return exhausted(period)
    return None


def record(account, prompt_tokens=0, completion_tokens=0, total_tokens=0, cached_tokens=0):
    """Soma uma chamada ao consumo do dia (atômico: duas conversas ao mesmo tempo não se perdem)."""
    total = total_tokens or (prompt_tokens + completion_tokens)
    with transaction.atomic():
        row, _ = CosmosUsage.objects.get_or_create(account_id=account.pk, day=timezone.localdate())
        CosmosUsage.objects.filter(pk=row.pk).update(
            requests=F("requests") + 1, prompt_tokens=F("prompt_tokens") + prompt_tokens,
            cached_tokens=F("cached_tokens") + cached_tokens,
            completion_tokens=F("completion_tokens") + completion_tokens, total_tokens=F("total_tokens") + total)
