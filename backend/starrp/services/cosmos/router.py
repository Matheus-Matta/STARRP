"""Roteamento por custo: cada chamada vai ao modelo mais barato que dá conta dela.

| Nível   | Quando                                                                 | Modelo               |
|---------|------------------------------------------------------------------------|----------------------|
| light   | saudação/agradecimento; comentar o resultado de uma confirmação;       | OPENAI_MODEL_LIGHT   |
|         | resumir o histórico antigo                                             |                      |
| default | o resto (consultas, relatórios, cadastros)                             | OPENAI_MODEL         |
| heavy   | planilha anexada, cadastro em lote                                     | OPENAI_MODEL_HEAVY   |

"sim", "pode", "não" NÃO vão ao leve: costumam continuar uma tarefa (a proposta que o modelo
ofereceu), e o leve erraria o corpo da gravação. Na dúvida, fica no padrão.
"""
import re

from django.conf import settings

LIGHT, DEFAULT, HEAVY = "light", "default", "heavy"

CHITCHAT = re.compile(
    r"^\s*(oi+|ol[aá]|e a[ií]|bom dia|boa tarde|boa noite|obrigad[oa]|valeu|vlw|brigad[oa]|show|top|"
    r"perfeito|[oó]timo|legal|beleza|blz|tchau|at[eé] mais)\b[\s!.,🙂😀👍]*"
    r"(cosmos)?[\s!.,🙂😀👍]*$", re.IGNORECASE)
BATCH = re.compile(r"\b(planilha|lote|importa[rç]|em massa|v[aá]rios produtos|todos os produtos)\b", re.IGNORECASE)


def tier(text="", attachments=False):
    if attachments or BATCH.search(text or ""):
        return HEAVY
    if CHITCHAT.match(text or ""):
        return LIGHT
    return DEFAULT


def local_reply(text=""):
    """Conversa puramente social não precisa pagar uma chamada ao modelo."""
    if not CHITCHAT.match(text or ""):
        return ""
    lowered = (text or "").lower()
    if any(word in lowered for word in ("obrigad", "valeu", "vlw", "brigad")):
        return "Por nada!"
    if any(word in lowered for word in ("tchau", "até mais")):
        return "Até mais!"
    return "Oi! Como posso ajudar?"


def model_for(level):
    if level == LIGHT and settings.OPENAI_MODEL_LIGHT:
        return settings.OPENAI_MODEL_LIGHT
    if level == HEAVY and settings.OPENAI_MODEL_HEAVY:
        return settings.OPENAI_MODEL_HEAVY
    return settings.OPENAI_MODEL


def max_output(level):
    return settings.COSMOS_MAX_OUTPUT_TOKENS // 3 if level == LIGHT else settings.COSMOS_MAX_OUTPUT_TOKENS


def options(model, level):
    """Parâmetros por modelo: raciocínio enxuto nos de raciocínio; teto de saída sempre."""
    out = {"max_completion_tokens": max_output(level)}
    # Não precisamos guardar respostas do ERP no provedor. Proxies OpenAI-compatíveis podem não
    # conhecer este parâmetro, então ele só vai para a API oficial.
    if not settings.OPENAI_BASE_URL:
        out["store"] = False
    if settings.OPENAI_REASONING_EFFORT and model.startswith(("gpt-5", "o1", "o3", "o4")):
        # No leve, o mínimo: comentar um resultado não precisa pensar.
        out["reasoning_effort"] = "minimal" if level == LIGHT and model.startswith("gpt-5") \
            else settings.OPENAI_REASONING_EFFORT
    return out
