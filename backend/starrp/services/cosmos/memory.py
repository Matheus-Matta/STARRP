"""Memória da conversa: janela deslizante + resumo do que saiu dela.

Reenviar a conversa inteira a cada mensagem faz o custo crescer com o quadrado do tamanho.
Então: as últimas `COSMOS_HISTORY_TURNS` falas do usuário (com tudo o que veio depois de cada
uma) vão inteiras; o que é mais antigo vira um parágrafo curto (`CosmosConversation.summary`),
escrito pelo modelo LEVE. O resumo é refeito em blocos (a cada `REFRESH_TURNS` falas que saem
da janela), não a cada mensagem.

Assunto novo depois de muito tempo parado (`GAP`): o que veio antes sai da janela na hora — vai
só no resumo, sem carregar o contexto velho inteiro.
"""
import logging
from datetime import timedelta

from django.conf import settings

from starrp.models import CosmosMessage
from starrp.services.cosmos import router, usage

logger = logging.getLogger(__name__)

Role = CosmosMessage.Role
GAP = timedelta(hours=12)
REFRESH_TURNS = 4
INPUT_CHARS = 12_000
LINE_CHARS = 600
SUMMARY_TOKENS = 600
PROMPT = ("Resuma a conversa entre um usuário de ERP de varejo e a assistente Cosmos, em pt-BR, até 120 palavras, "
          "em tópicos curtos. Guarde: o que o usuário quer, decisões, ids/nomes/valores citados, propostas "
          "confirmadas ou canceladas e o que ficou pendente. Sem cumprimentos. Junte com o resumo anterior.")


def _starts(conversation):
    """Falas que abrem uma rodada (usuário ou aviso de confirmação), da mais nova para a mais velha."""
    return list(conversation.messages.filter(role__in=[Role.USER, Role.EVENT])
                .order_by("-position").values_list("position", "created_at")[:settings.COSMOS_HISTORY_TURNS + 1])


def cut(conversation):
    """(posição da primeira fala que vai inteira, se o corte veio de uma pausa longa)."""
    starts = _starts(conversation)
    for (position, at), (_, before) in zip(starts, starts[1:], strict=False):
        if at - before >= GAP:
            return position, True
    if len(starts) <= settings.COSMOS_HISTORY_TURNS:
        return 0, False
    return starts[settings.COSMOS_HISTORY_TURNS - 1][0], False


def _transcript(conversation, start, end):
    names = {Role.USER: "Usuário", Role.ASSISTANT: "Cosmos", Role.EVENT: "Sistema"}
    lines = []
    for m in conversation.messages.filter(position__gt=start, position__lt=end).exclude(role=Role.TOOL) \
            .order_by("position"):
        if m.content:
            lines.append(f"{names[m.role]}: {m.content[:LINE_CHARS]}")
    return "\n".join(lines)[-INPUT_CHARS:]


def refresh(conversation, actor, client):
    """Resume o que saiu da janela, se já juntou o bastante. Falhou → segue sem (a janela de 40 segura)."""
    position, by_gap = cut(conversation)
    if position <= conversation.summary_until + 1:
        return False
    pending = conversation.messages.filter(position__gt=conversation.summary_until, position__lt=position,
                                           role=Role.USER).count()
    if not by_gap and pending < REFRESH_TURNS:
        return False
    text = _transcript(conversation, conversation.summary_until, position)
    if not text:
        return False
    model = router.model_for(router.LIGHT)
    previous = f"Resumo anterior:\n{conversation.summary}\n\n" if conversation.summary else ""
    try:
        options = router.options(model, router.LIGHT)
        options["max_completion_tokens"] = SUMMARY_TOKENS
        reply = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": PROMPT},
                                   {"role": "user", "content": f"{previous}Conversa:\n{text}"}], **options)
        summary = (reply.choices[0].message.content or "").strip()
        if reply.usage is not None:
            details = getattr(reply.usage, "prompt_tokens_details", None)
            usage.record(actor.account, reply.usage.prompt_tokens or 0, reply.usage.completion_tokens or 0,
                         reply.usage.total_tokens or 0, getattr(details, "cached_tokens", 0) or 0)
    except Exception:  # noqa: BLE001 — sem resumo a conversa continua (só fica mais cara)
        logger.warning("Cosmos: não consegui resumir a conversa %s", conversation.pk, exc_info=True)
        return False
    if not summary:
        return False
    conversation.summary, conversation.summary_until = summary[:4000], position - 1
    conversation.save(update_fields=["summary", "summary_until", "updated_at"])
    return True
