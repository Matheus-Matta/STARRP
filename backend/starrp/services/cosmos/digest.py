"""Resumo diário da equipe: toda manhã, quem supervisiona recebe na Cosmos o dia anterior.

Uma conversa por pessoa e por dia (`CosmosConversation.digest_day`), com uma fala pronta da
Cosmos: vendas do dia, quem fez o quê, os alertas novos e os abertos. O texto é montado aqui,
com os números do servidor — não chama o modelo, não gasta tokens. Daí em diante é uma
conversa normal: os botões ("Ver alertas", "Detalhar Fulano") seguem com a Cosmos.

Entrega: pelo Celery beat (`starrp.cosmos_daily_digest`, de manhã) ou, sem Celery, quando
quem supervisiona abre o widget (`ensure`, a partir das 6h). Desliga por conta no admin
(`Account.cosmos_daily_digest`). Dia sem movimento não gera resumo.
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from starrp.core.middleware import ALL_STORES
from starrp.core.permissions import has_permission_code
from starrp.core.tenant import clear_current_account
from starrp.models import Account, CosmosConversation, CosmosFinding, CosmosMessage, PriceCheck
from starrp.services.cosmos import bridge, datasets, events, supervision

logger = logging.getLogger(__name__)

START_HOUR = 6
PEOPLE = 8
FINDINGS = 5
WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
SEVERITY = {"critical": "Grave", "warning": "Atenção", "info": "Informação"}


def _money(value):
    return "R$ " + f"{value or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _count(n, one, many):
    return f"{n} {one if n == 1 else many}"


def _sales(actor, day):
    """Vendas e cancelamentos do dia — só para quem pode ver relatórios."""
    try:
        sold = datasets.query(actor, "vendas", ["faturamento", "quantidade"], date_from=str(day), date_to=str(day))
        cancelled = datasets.query(actor, "cancelamentos", ["quantidade"], date_from=str(day), date_to=str(day))
    except datasets.DatasetError:
        return None
    row, cancel = sold["rows"][0], cancelled["rows"][0]
    return {"total": row.get("faturamento") or 0, "count": row.get("quantidade") or 0,
            "cancelled": cancel.get("quantidade") or 0}


def _person_line(person):
    parts = []
    for what, actions in sorted(person["counts"].items(), key=lambda kv: -sum(kv[1].values()))[:3]:
        parts.append(f"{what} ({', '.join(f'{verb} {n}' for verb, n in actions.items())})")
    alerts = person.get("alertas_no_periodo") or 0
    tail = f" · ⚠ {_count(alerts, 'alerta', 'alertas')}" if alerts else ""
    return f"- **{person['user']}** — {_count(person['total'], 'gravação', 'gravações')}: {'; '.join(parts)}{tail}"


def build(actor, day):
    """(texto, botões) do resumo do dia; `None` se o dia não teve movimento."""
    activity = supervision.team_activity(actor, str(day), str(day))
    people = [p for p in activity["people"] if p["user_id"] != actor.user.pk]
    actor.bind()
    findings = list(CosmosFinding.objects.filter(created_at__date=day).select_related("actor")
                    .order_by("created_at"))
    still_open = CosmosFinding.objects.filter(status=CosmosFinding.Status.OPEN).count()
    sales = _sales(actor, day)
    if not people and not findings and not (sales and (sales["count"] or sales["cancelled"])):
        return None

    yesterday = day == timezone.localdate() - timedelta(days=1)
    when = f"{'ontem, ' if yesterday else ''}{WEEKDAYS[day.weekday()]} {day:%d/%m/%Y}"
    lines = [f"**Resumo da equipe — {when}**"]
    if sales is not None:
        cancel = f" · {_count(sales['cancelled'], 'cancelamento', 'cancelamentos')}" if sales["cancelled"] else ""
        lines.append(f"**Vendas:** {_count(sales['count'], 'venda', 'vendas')} · {_money(sales['total'])}{cancel}")
    if people:
        lines.append("**Quem fez o quê**")
        lines += [_person_line(p) for p in people[:PEOPLE]]
        if len(people) > PEOPLE:
            lines.append(f"- e mais {_count(len(people) - PEOPLE, 'pessoa', 'pessoas')}")
    else:
        lines.append("Ninguém da equipe gravou nada no sistema neste dia.")
    if findings:
        order = {"critical": 0, "warning": 1, "info": 2}
        by_severity = {}
        for f in findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        split = ", ".join(f"{n} {SEVERITY[s].lower()}" for s, n in sorted(by_severity.items(), key=lambda kv: order[kv[0]]))
        lines.append(f"**Alertas novos ({len(findings)})** — {split}")
        for f in sorted(findings, key=lambda f: order.get(f.severity, 3))[:FINDINGS]:
            lines.append(f"- {SEVERITY[f.severity]}: {supervision.alert_text(f)}")
    else:
        lines.append("Nenhum alerta novo da supervisão neste dia. 👍")
    if still_open:
        lines.append(f"Há **{_count(still_open, 'alerta aberto', 'alertas abertos')}** no total, esperando correção.")
    prices = _pending_prices(actor)
    if prices:
        lines.append(f"**Precificação:** {_count(prices, 'sugestão de preço', 'sugestões de preço')} esperando "
                     "aprovação (Vendas › Precificação).")

    buttons = []
    if still_open:
        buttons.append({"label": "Ver alertas e como corrigir", "kind": "reply",
                        "value": "Quais alertas estão abertos e como corrigir cada um?"})
    for person in people[:2]:
        first = person["user"].split(" ")[0]
        buttons.append({"label": f"Detalhar {first}", "kind": "reply",
                        "value": f"O que {person['user']} fez em {day:%d/%m/%Y}? Liste as ações e o que está errado."})
    if prices:
        buttons.append({"label": "Ver sugestões de preço", "kind": "reply",
                        "value": "Quais sugestões de preço estão esperando aprovação? Vale a pena aderir?"})
    if people:
        buttons.append({"label": "Relatório da semana", "kind": "reply",
                        "value": "Monte um relatório da atividade da equipe nos últimos 7 dias, com gráfico por pessoa."})
    return "\n".join(_paragraphs(lines)), buttons[:4]


def _pending_prices(actor):
    """Sugestões de preço esperando alguém aprovar — só para quem pode ver o catálogo."""
    account = actor.account
    if not (account.price_tracking_enabled and account.has_module("pricing")
            and has_permission_code(actor.user, "catalog.view")):
        return 0
    return PriceCheck.objects.filter(status=PriceCheck.Status.PENDING).count()


def _paragraphs(lines):
    """Cada linha que não é item de lista abre um parágrafo; os itens ficam juntos, numa lista só."""
    out = []
    for line in lines:
        if out and not line.startswith("- "):
            out.append("")
        out.append(line)
    return out


def deliver(user, account, day):
    """Cria o resumo do dia para esta pessoa (uma vez). Devolve a conversa, ou `None`."""
    if CosmosConversation.all_objects.filter(user=user, digest_day=day).exists():
        return None
    actor = bridge.actor_for(user, ALL_STORES)
    if actor.account.pk != account.pk or not has_permission_code(user, "cosmos.supervise"):
        return None
    built = build(actor, day)
    if built is None:
        return None
    text, buttons = built
    now = timezone.now()
    try:
        with transaction.atomic():
            conversation = CosmosConversation.all_objects.create(
                account=account, user=user, title=f"Resumo da equipe — {day:%d/%m}", digest_day=day,
                last_message_at=now, created_by=user, updated_by=user)
            CosmosMessage.all_objects.create(
                account=account, conversation=conversation, role=CosmosMessage.Role.ASSISTANT, content=text,
                blocks=[{"type": "buttons", "buttons": buttons}] if buttons else [], created_by=user, updated_by=user)
    except IntegrityError:  # o Celery e o widget ao mesmo tempo: o outro já entregou
        return None
    from starrp.services.cosmos.agent import conversation_payload

    payload = conversation_payload(conversation)
    events.send(user.pk, {"type": "conversation", "conversation": payload})
    events.send(user.pk, {"type": "digest", "conversation": payload})
    return conversation


def ensure(user, account):
    """Sem Celery: quem supervisiona abriu o widget → o resumo de ontem, se ainda não recebeu."""
    if not account.cosmos_daily_digest or not account.cosmos_active:
        return None
    now = timezone.localtime()
    day = now.date() - timedelta(days=1)
    if now.hour < START_HOUR or not cache.add(f"cosmos:digest:{user.pk}:{day}", 1, 26 * 3600):
        return None
    try:
        return deliver(user, account, day)
    except Exception:  # noqa: BLE001 — o resumo nunca derruba a abertura do widget
        logger.exception("Cosmos: falha no resumo diário de %s", user.pk)
        return None


def run(day=None):
    """Celery: o resumo de ontem (ou do dia informado) para quem supervisiona, em cada conta."""
    day = day or timezone.localdate() - timedelta(days=1)
    users = get_user_model().objects
    sent = 0
    for account in Account.objects.filter(status=Account.Status.ACTIVE, cosmos_enabled=True, cosmos_daily_digest=True):
        if not account.cosmos_active:
            continue
        for user_id in supervision.supervisors(account.pk, None):
            try:
                sent += deliver(users.get(pk=user_id), account, day) is not None
            except Exception:  # noqa: BLE001 — uma pessoa com problema não segura as outras
                logger.exception("Cosmos: falha no resumo diário de %s", user_id)
            finally:
                clear_current_account()
    return sent
