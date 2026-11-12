"""A Cosmos trabalhando em segundo plano, sem conversa: uma pergunta ao modelo MAIS BARATO, com resposta em JSON.

Usada pelo Analítico de SEO e pela Precificação. Sempre um extra: sem módulo, sem interruptor, sem chave, sem saldo de tokens
ou com erro no modelo, devolve `None` e quem chamou segue com as regras. Conta no limite de tokens da conta, como a conversa.
"""
import json
import logging

from django.conf import settings

from starrp.services.cosmos import router, usage

logger = logging.getLogger(__name__)


def available(account, switch):
    """A conta tem a Cosmos, ligou esta função (`cosmos_seo_ai`, `cosmos_pricing_ai`), há chave e sobra saldo?"""
    from starrp.services.cosmos import agent

    return bool(account.cosmos_active and getattr(account, switch) and agent.enabled() and usage.blocked(account) is None)


def ask_json(account, system, user, max_tokens=800, namespace="background"):
    """O objeto JSON que o modelo devolveu, ou `None`. Quem chama confere `available` e valida o conteúdo."""
    from starrp.services.cosmos import agent

    model = router.model_for(router.LIGHT)
    try:
        options = {**router.options(model, router.LIGHT), "max_completion_tokens": max_tokens}
        if not settings.OPENAI_BASE_URL:
            options["prompt_cache_key"] = f"cosmos-{namespace}-{account.pk}"
        reply = agent._client().chat.completions.create(
            model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, **options)
        if reply.usage is not None:
            details = getattr(reply.usage, "prompt_tokens_details", None)
            usage.record(account, reply.usage.prompt_tokens or 0, reply.usage.completion_tokens or 0,
                         reply.usage.total_tokens or 0, getattr(details, "cached_tokens", 0) or 0)
        body = json.loads(reply.choices[0].message.content or "")
    except Exception:  # noqa: BLE001 — a IA é um extra: nunca derruba a análise
        logger.warning("Cosmos: falha na chamada em segundo plano da conta %s", account.pk, exc_info=True)
        return None
    return body if isinstance(body, dict) else None
