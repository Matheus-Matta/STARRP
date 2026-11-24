"""Limite de tentativas de senha (S-04, docs/SEGURANCA.md): autorização do gerente, senha de ações do
caixa e desbloqueio da tela do PDV. Usuário logado não tem throttle geral; aqui é por ALVO e por quem tenta:

- o mesmo usuário contra o mesmo alvo (login do autorizador ou a senha do caixa de uma loja): 5 erros em 5 min;
- o mesmo usuário tentando: 20 erros em 5 minutos (vários alvos);
- o mesmo alvo, somando todo mundo: 50 erros em 5 minutos (força bruta espalhada em várias contas).

O bloqueio é de QUEM tenta (rodada 1, P-10): um caixa errando de propósito a senha do gerente não trava o
gerente para os outros. Estourou: 429 até a janela passar. Acertar zera o contador daquele par. Fica no
cache (Redis em produção: vale para todos os processos e para blue e green).
"""
import hashlib

from django.core.cache import cache
from rest_framework.exceptions import Throttled

WINDOW = 5 * 60
PER_PAIR = 5
PER_ACTOR = 20
PER_TARGET = 50


def _key(kind, *parts):
    digest = hashlib.sha256("|".join(str(p).lower() for p in parts).encode()).hexdigest()[:32]
    return f"starrp:attempts:{kind}:{digest}"


def check(actor, target):
    """Antes de conferir a senha: barra quem já errou demais."""
    if (cache.get(_key("pair", actor, *target), 0) >= PER_PAIR or cache.get(_key("actor", actor), 0) >= PER_ACTOR
            or cache.get(_key("target", *target), 0) >= PER_TARGET):
        raise Throttled(wait=WINDOW, detail="Muitas tentativas de senha. Aguarde alguns minutos e tente de novo.")


def failed(actor, target):
    for key in (_key("pair", actor, *target), _key("actor", actor), _key("target", *target)):
        if cache.add(key, 1, WINDOW):
            continue
        try:
            cache.incr(key)
        except ValueError:  # expirou entre o add e o incr
            cache.set(key, 1, WINDOW)


def succeeded(target, actor=None):
    cache.delete(_key("pair", actor, *target))
