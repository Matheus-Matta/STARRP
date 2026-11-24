"""Ensaio (dry-run) da Cosmos sem efeito fora do banco (S-05, docs/SEGURANCA.md).

A Cosmos ensaia toda gravação numa transação desfeita, para o usuário só ver proposta que passa. Desfazer o
banco não desfaz o que saiu para fora: cancelar a NFC-e na SEFAZ, cobrar no Asaas, disparar leitura de preço
(créditos pagos). Durante o ensaio, qualquer chamada HTTP de saída (requests, urllib) e qualquer tarefa do
Celery levanta `ExternalEffect`: a ponte para o ensaio ali e a proposta vai ao usuário SEM ensaio.

`ExternalEffect` herda de BaseException de propósito: nenhum `except Exception` no caminho (view, serviço,
cliente HTTP) a transforma em "erro" — ela sempre chega à ponte. Vale só no contexto do ensaio (ContextVar):
outras requisições, em outras threads, não são afetadas.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE = ContextVar("starrp_dry_run", default=False)
_installed = False


class ExternalEffect(BaseException):  # noqa: N818 — não é erro: é o sinal "isto sairia para fora"
    pass


def active():
    return _ACTIVE.get()


@contextmanager
def dry_run():
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def guard(what):
    if _ACTIVE.get():
        raise ExternalEffect(what)


def install():
    """Liga as travas (uma vez, no AppConfig.ready): requests, urllib e o envio de tarefas do Celery."""
    global _installed
    if _installed:
        return
    _installed = True

    import urllib.request

    import requests

    original_request = requests.Session.request

    def request(self, method, url, *args, **kwargs):
        guard(f"HTTP {method} {url}")
        return original_request(self, method, url, *args, **kwargs)

    requests.Session.request = request

    original_open = urllib.request.OpenerDirector.open

    def open_(self, fullurl, *args, **kwargs):
        guard(f"HTTP {getattr(fullurl, 'full_url', fullurl)}")
        return original_open(self, fullurl, *args, **kwargs)

    urllib.request.OpenerDirector.open = open_

    from celery.app.task import Task

    original_apply = Task.apply_async

    def apply_async(self, *args, **kwargs):
        guard(f"tarefa {self.name}")
        return original_apply(self, *args, **kwargs)

    Task.apply_async = apply_async
