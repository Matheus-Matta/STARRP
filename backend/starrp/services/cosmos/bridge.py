"""Chamada à API do Starrp em nome do usuário, sem sair do processo.

A Cosmos não tem atalho para o banco: ela monta a mesma requisição que a tela faria e
entrega para a view de verdade. Assim valem, sem repetir nada, as permissões do cargo,
o recorte por conta e filial, a validação dos serializers, a auditoria e o histórico.

    actor = actor_for(user, store_id)
    bridge.call(actor, "GET", "/catalog/products/", params={"search": "camiseta"})
    bridge.call(actor, "PATCH", "/catalog/products/<id>/", body={"name": "Camiseta Azul"})

`dry_run=True` executa e desfaz (transação revertida): serve para validar uma proposta
antes de pedir a confirmação — o usuário só vê o cartão se a gravação vai passar.
"""
import json
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

from django.db import transaction
from django.test import RequestFactory
from django.urls import Resolver404, resolve
from rest_framework.test import force_authenticate
from simple_history.models import HistoricalRecords

from starrp.core.middleware import ALL_STORES, bind_user
from starrp.core.tenant import set_current_account

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1/"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Fora do alcance da Cosmos: login/senha, sincronização técnica, desbloqueio do PDV.
BLOCKED_PREFIXES = ("auth/", "sync/", "pdv/", "public/", "imports/", "cosmos/")


class CosmosDenied(Exception):
    """O usuário não pode usar a Cosmos agora (sem conta, sem filial, sem permissão)."""


@dataclass
class Actor:
    """Quem a Cosmos representa: o usuário, a conta e a filial ativa da tela."""

    user: object
    account: object
    profile: object
    store: object
    allowed_store_ids: object

    @property
    def store_header(self):
        return str(self.store.pk) if self.store is not None else ALL_STORES

    def bind(self):
        """Fixa o contexto da conta na thread (consultas com `Model.objects`)."""
        set_current_account(self.account, self.allowed_store_ids)


def actor_for(user, store_id=None):
    request = RequestFactory().get(API_PREFIX + "me/", HTTP_X_STORE_ID=store_id or "")
    request.user = user
    denied = bind_user(request)
    if denied is not None:
        raise CosmosDenied(json.loads(denied.content).get("error", {}).get("message", "Sem acesso."))
    return Actor(user=user, account=request.account, profile=request.profile, store=request.store,
                 allowed_store_ids=request.allowed_store_ids)


@dataclass
class ApiResult:
    status: int
    data: object
    filename: str = ""

    @property
    def ok(self):
        return 200 <= self.status < 300


def normalize(path):
    """`/api/v1/catalog/products` ou `catalog/products/?x=1` → `catalog/products/` (sem a query)."""
    path = (path or "").split("?", 1)[0].strip()
    if path.startswith(API_PREFIX):
        path = path[len(API_PREFIX):]
    path = path.lstrip("/")
    return path if path.endswith("/") else f"{path}/"


def blocked(path):
    return normalize(path).startswith(BLOCKED_PREFIXES)


def _clean_body(body):
    """A autorização de gerente (`approval` com usuário e senha) nunca vem da Cosmos."""
    if isinstance(body, dict):
        return {key: value for key, value in body.items() if key != "approval"}
    return body


def call(actor, method, path, params=None, body=None, dry_run=False):
    method = (method or "GET").upper()
    path = normalize(path)
    if method not in {"GET", *WRITE_METHODS}:
        return ApiResult(405, {"detail": f"Método {method} não é aceito."})
    if blocked(path):
        return ApiResult(403, {"detail": "A Cosmos não usa este endereço."})
    url = API_PREFIX + path
    try:
        match = resolve(url)
    except Resolver404:
        return ApiResult(404, {"detail": f"Endereço inexistente: /{path}"})
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    factory = RequestFactory()
    # Host fixo e permitido: a paginação monta o link da próxima página a partir dele.
    headers = {"HTTP_X_STORE_ID": actor.store_header, "HTTP_HOST": "localhost"}
    if method == "GET":
        request = factory.get(url, data=query, **headers)
    else:
        target = f"{url}?{urlencode(query, doseq=True)}" if query else url
        request = factory.generic(method, target, data=json.dumps(_clean_body(body) or {}, default=str),
                                  content_type="application/json", **headers)
    request.user = actor.user
    request.via_cosmos = True
    denied = bind_user(request)
    if denied is not None:
        actor.bind()
        return ApiResult(denied.status_code, json.loads(denied.content))
    force_authenticate(request, user=actor.user)
    previous = getattr(HistoricalRecords.context, "request", None)
    HistoricalRecords.context.request = request  # o histórico registra o usuário, não "sistema"
    try:
        if dry_run:
            with transaction.atomic():
                result = _dispatch(match, request)
                transaction.set_rollback(True)
        else:
            result = _dispatch(match, request)
    except Exception as error:  # noqa: BLE001 — a conversa segue; o erro vira resposta
        logger.exception("Cosmos: falha em %s %s", method, path)
        result = ApiResult(500, {"detail": f"Erro interno ao executar: {error.__class__.__name__}."})
    finally:
        HistoricalRecords.context.request = previous
        actor.bind()
    return result


def _dispatch(match, request):
    response = match.func(request, *match.args, **match.kwargs)
    if hasattr(response, "render"):
        response.render()
    kind = response.get("Content-Type", "")
    disposition = response.get("Content-Disposition", "")
    if "attachment" in disposition:
        return ApiResult(response.status_code, {"detail": "Arquivo gerado."}, filename=disposition)
    if not response.content:
        return ApiResult(response.status_code, {})
    if "json" in kind:
        return ApiResult(response.status_code, json.loads(response.content))
    return ApiResult(response.status_code, {"detail": response.content.decode(errors="replace")[:500]})
