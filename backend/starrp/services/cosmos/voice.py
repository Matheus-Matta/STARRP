"""Entrada de voz da Cosmos: valida o áudio curto e o transcreve sem guardar o arquivo."""
import logging
from pathlib import Path

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

from starrp.services.cosmos import agent, usage

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
}
class VoiceUnavailable(APIException):
    status_code = 503
    default_detail = "Não consegui transcrever o áudio agora. Tente novamente em instantes."
    default_code = "voice_unavailable"


def _tokens(result):
    raw = getattr(result, "usage", None)
    if raw is None:
        return 0, 0, 0
    get = raw.get if isinstance(raw, dict) else lambda key, default=0: getattr(raw, key, default)
    prompt = int(get("input_tokens", 0) or get("prompt_tokens", 0) or 0)
    completion = int(get("output_tokens", 0) or get("completion_tokens", 0) or 0)
    return prompt, completion, int(get("total_tokens", 0) or prompt + completion)


def transcribe(upload, account):
    """Devolve texto em pt-BR; o áudio fica somente em memória durante a chamada."""
    content_type = str(upload.content_type or "").split(";", 1)[0].lower()
    if content_type not in ALLOWED_TYPES:
        raise ValidationError({"audio": "Formato de áudio não aceito."})
    if not upload.size:
        raise ValidationError({"audio": "A gravação veio vazia. Tente falar novamente."})
    if upload.size > MAX_AUDIO_BYTES:
        raise ValidationError({"audio": "A gravação ficou grande demais. Fale por até 1 minuto."})
    limit = usage.blocked(account)
    if limit:
        raise ValidationError({"audio": limit})

    suffix = Path(upload.name or "").suffix.lower()
    if suffix not in ALLOWED_TYPES.values():
        suffix = ALLOWED_TYPES[content_type]
    from openai import APIError

    try:
        result = agent._client().audio.transcriptions.create(  # noqa: SLF001 — cliente compartilhado da Cosmos
            model=settings.OPENAI_TRANSCRIBE_MODEL,
            file=(f"fala{suffix}", upload.read(), content_type),
            language="pt",
            response_format="json",
        )
    except APIError as error:
        logger.warning("Cosmos voz: erro da OpenAI: %s", error)
        raise VoiceUnavailable() from error

    text = str(result if isinstance(result, str) else getattr(result, "text", "")).strip()
    prompt, completion, total = _tokens(result)
    usage.record(account, prompt, completion, total)
    if not text:
        raise ValidationError({"audio": "Não identifiquei nenhuma fala. Tente novamente mais perto do microfone."})
    return text
