"""Comprovante da autorização do gerente para o que o PDV desktop faz no PC (S-06, docs/SEGURANCA.md).

Venda e caixa feitos no PC chegam PRONTOS e são fatos (o cliente pagou, a sangria saiu): o servidor não pode
recusá-los por falta de autorização. Mas também não pode aceitar o "aprovado por" que o PDV escrever. Então:

1. `/pdv/authorize/` (servidor no ar) devolve, junto com quem autorizou, um COMPROVANTE assinado pelo servidor:
   conta, filial, operador que pediu, autorizador (vazio = senha de ações do caixa), ação, o percentual
   autorizado (desconto) e um id único. Vale 3 dias e UMA vez.
2. O PDV guarda os comprovantes e manda com a venda/evento de caixa (`approval_proofs`).
3. Cada "aprovado por" precisa de um comprovante que bata (mesmo autorizador, conta, filial e operador, ação
   certa, desconto dentro do autorizado) e que ainda não tenha sido usado. Bateu: vale, e o comprovante é gasto.
4. Não bateu (autorização feita OFFLINE pelas senhas que o PC aprendeu, ou adulterada): o fato entra marcado para
   a gerência conferir (venda `_approval_unverified`, sangria pendente, turno com motivo "confira").
"""
import secrets
from decimal import Decimal

from django.core import signing
from django.core.cache import cache

SALT = "starrp.pdv.approval"
MAX_AGE = 3 * 24 * 3600
CASH_PASSWORD = "cash_password"  # autorizador = a senha de ações do caixa da loja


def issue(*, account, store, operator, approver, code, max_percent):
    return signing.dumps({
        "a": str(account.pk), "s": str(getattr(store, "pk", "") or ""), "o": getattr(operator, "pk", None),
        "p": getattr(approver, "pk", None) if approver is not None else CASH_PASSWORD, "c": code,
        "m": str(max_percent), "j": secrets.token_urlsafe(12),
    }, salt=SALT, compress=True)


def decode(proofs):
    """Comprovantes válidos (assinatura certa e dentro do prazo); os outros são ignorados."""
    out = []
    for raw in proofs or []:
        try:
            out.append(signing.loads(str(raw), salt=SALT, max_age=MAX_AGE))
        except signing.BadSignature:
            continue
    return out


def _spent(proof):
    return cache.get(f"starrp:proof:{proof.get('j')}") is not None


def spend(proof):
    """Gasta o comprovante (uso único). `False` se outro já o gastou (corrida/reuso)."""
    return bool(cache.add(f"starrp:proof:{proof.get('j')}", 1, MAX_AGE))


def find(proofs, *, account, store, operator, approver_id, codes, percent=None):
    """O comprovante (ainda não usado) que prova que `approver_id` autorizou `operator` nesta conta/filial."""
    for proof in proofs:
        if proof.get("a") != str(account.pk) or proof.get("p") != approver_id or not proof.get("j"):
            continue
        if store is not None and proof.get("s") not in ("", str(store.pk)):
            continue
        if proof.get("o") != getattr(operator, "pk", None) or proof.get("c") not in codes:
            continue
        if percent is not None and Decimal(str(percent)) > Decimal(proof.get("m") or "0") + Decimal("0.01"):
            continue
        if _spent(proof):
            continue
        return proof
    return None


def covers(proofs, **kwargs):
    return find(proofs, **kwargs) is not None
