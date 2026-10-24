"""Conta (tenant) e lojas permitidas da requisição corrente.

Dois níveis de isolamento, os dois no mesmo lugar:

1. **Conta**: `_current_account`. Sem conta, o manager devolve vazio.
2. **Lojas permitidas**: `_allowed_stores`. `None` = todas as lojas da conta
   (admin, ou usuário marcado `all_stores`); um conjunto de ids = só elas.
   É SEGURANÇA: o manager nunca devolve linha de loja fora do conjunto.

A loja ATIVA (`X-Store-ID`, o seletor da tela) é outra coisa: é escolha de
visualização dentro das permitidas, e quem a aplica é a view.

Fora de requisição (tarefa, comando), use `tenant_context(conta)`: ele libera
todas as lojas da conta, porque processos de fundo atendem a rede inteira.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_current_account = ContextVar("current_account", default=None)
_allowed_stores = ContextVar("allowed_stores", default=None)


def get_current_account():
    return _current_account.get()


def set_current_account(account, allowed_store_ids=None):
    _allowed_stores.set(frozenset(allowed_store_ids) if allowed_store_ids is not None else None)
    return _current_account.set(account)


def get_allowed_store_ids():
    """`None` = todas as lojas da conta; senão, o conjunto de ids permitidos."""
    return _allowed_stores.get()


def store_allowed(store_id):
    allowed = _allowed_stores.get()
    return store_id is None or allowed is None or store_id in allowed


def clear_current_account():
    _current_account.set(None)
    _allowed_stores.set(None)


@contextmanager
def tenant_context(account, allowed_store_ids=None):
    """Executa o bloco como a conta `account` (por padrão, todas as lojas)."""
    account_token = _current_account.set(account)
    stores_token = _allowed_stores.set(frozenset(allowed_store_ids) if allowed_store_ids is not None else None)
    try:
        yield
    finally:
        _current_account.reset(account_token)
        _allowed_stores.reset(stores_token)
