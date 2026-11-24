"""Comunicador Fiscal ACBr em NUVEM (Docker, `ACBR_MODO=nuvem` — github.com/Matheus-Matta/app-fiscal-acbr).

Quem chama o comunicador em nuvem é SÓ este backend:

    PDV web ──INI──► POST /pdv/acbr/ ──► (token + envelope AES-256-GCM + certificado A1 + CSC)
                                      ──► comunicador Docker ──► ACBrLib ──► SEFAZ

- o token (`ACBRLIB_TOKEN`) e a chave de cifra (`ACBR_E2E_KEY`) ficam só no `.env` do backend;
- o certificado A1, a senha e o CSC saem dos dados fiscais da filial e vão em CADA chamada, dentro
  do envelope: o comunicador não grava nada (nem o XML, que volta na resposta e é guardado aqui);
- a resposta só vale se abriu com a chave (`trusted`). Sem envelope (401/403/404/413/429, rede,
  cifra) não é decisão fiscal: depois de um envio, consulta antes de reenviar.

O PDV desktop NÃO passa por aqui: ele fala com o Comunicador Fiscal desktop (modo local) do PC do
caixa. Mas o cancelamento de qualquer nota ACBrLib (desktop ou web) sai daqui (`cancel`).

Cifra (docs/API.md §3): HKDF-SHA256 da `ACBR_E2E_KEY`, sem sal, info "acbr-e2e-v1 pedido" / "acbr-e2e-v1
resposta"; AAD do pedido "acbr-e2e-v1\\nPOST\\n<rota>\\n<ts>\\n<nonce>", da resposta
"acbr-e2e-v1\\n<status>\\n<nonce do pedido>".
"""
import base64
import binascii
import json
import logging
import os
import time
from dataclasses import dataclass

import requests
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import only_digits

logger = logging.getLogger(__name__)

LABEL = "acbr-e2e-v1"
#: Rotas fiscais que o PDV web pode pedir pela ponte. Configuração (`/v1/config/*`) nunca.
PDV_ROUTES = {"/v1/status-servico", "/v1/nfe/emitir", "/v1/nfe/transmitir", "/v1/nfe/consultar"}
#: Campos do documento que vêm do PDV; o contexto (emitente, certificado, CSC) é sempre daqui.
PDV_FIELDS = {"ini", "tp_emis", "xml", "chave", "referencia"}


@dataclass
class Answer:
    status: int
    data: dict
    trusted: bool

    def as_dict(self):
        return {"status": self.status, "data": self.data, "trusted": self.trusted}


def configured():
    return bool(settings.ACBRLIB_URL and settings.ACBRLIB_TOKEN and settings.ACBR_E2E_KEY)


def _require():
    if not configured():
        raise BusinessError("O comunicador fiscal em nuvem não está configurado no servidor "
                            "(ACBRLIB_URL, ACBRLIB_TOKEN e ACBR_E2E_KEY).", code="acbr_cloud_missing")


def _key(side):
    try:
        raw = base64.b64decode(settings.ACBR_E2E_KEY, validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != 32:
        raise BusinessError("ACBR_E2E_KEY precisa ter 32 bytes em base64.", code="acbr_cloud_key")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"{LABEL} {side}".encode()).derive(raw)


def seal(path, body, *, ts=None, nonce=None):
    """(envelope, nonce em base64) de um pedido."""
    ts = int(time.time()) if ts is None else ts
    nonce_raw = os.urandom(12) if nonce is None else nonce
    nonce_b64 = base64.b64encode(nonce_raw).decode()
    aad = f"{LABEL}\nPOST\n{path}\n{ts}\n{nonce_b64}".encode()
    data = AESGCM(_key("pedido")).encrypt(nonce_raw, json.dumps(body).encode(), aad)
    return {"v": 1, "ts": ts, "nonce": nonce_b64, "dados": base64.b64encode(data).decode()}, nonce_b64


def unseal(status, envelope, request_nonce):
    """A resposta aberta, ou None se não abrir com a chave (não é decisão fiscal)."""
    try:
        aad = f"{LABEL}\n{status}\n{request_nonce}".encode()
        plain = AESGCM(_key("resposta")).decrypt(base64.b64decode(envelope["nonce"]),
                                                 base64.b64decode(envelope["dados"]), aad)
        data = json.loads(plain)
    except (KeyError, TypeError, ValueError, InvalidTag, binascii.Error):
        return None
    return data if isinstance(data, dict) else None


def call(path, body):
    """Uma chamada cifrada ao comunicador. Nunca levanta por rede: devolve `trusted=False`."""
    _require()
    envelope, nonce = seal(path, body)
    url = f"{settings.ACBRLIB_URL}{path}"
    try:
        response = requests.post(url, json=envelope, timeout=settings.ACBRLIB_TIMEOUT,
                                 headers={"Authorization": f"Bearer {settings.ACBRLIB_TOKEN}"})
    except requests.RequestException as error:
        logger.warning("Comunicador fiscal sem resposta em %s: %s", path, error)
        return Answer(0, {"erro": "sem_resposta", "mensagem": "O comunicador fiscal não respondeu."}, False)
    try:
        raw = response.json()
    except ValueError:
        raw = {}
    data = unseal(response.status_code, raw, nonce) if isinstance(raw, dict) and raw.get("dados") else None
    if data is None:
        detail = raw.get("mensagem") or raw.get("detail") if isinstance(raw, dict) else None
        message = {401: "Token do comunicador fiscal recusado (ACBRLIB_TOKEN).",
                   429: "O comunicador fiscal bloqueou este servidor por tentativas com token errado."}.get(
            response.status_code, detail or f"Resposta do comunicador fiscal sem cifra (HTTP {response.status_code}).")
        logger.warning("Comunicador fiscal %s respondeu %s sem envelope: %s", path, response.status_code, detail)
        return Answer(response.status_code, {"erro": "sem_resposta", "motivo": (raw or {}).get("motivo", "")
                                             if isinstance(raw, dict) else "", "mensagem": message}, False)
    return Answer(response.status_code, data, True)


def health():
    """`/health` do comunicador (aberto, sem segredo)."""
    if not configured():
        return {"ok": False, "message": "O comunicador fiscal em nuvem não está configurado no servidor."}
    try:
        response = requests.get(f"{settings.ACBRLIB_URL}/health", timeout=5)
        body = response.json()
    except (requests.RequestException, ValueError):
        return {"ok": False, "message": "O comunicador fiscal em nuvem não respondeu."}
    if not isinstance(body, dict):
        body = {}
    out = {k: body.get(k) for k in ("modo", "motor", "lib", "simulador")}
    out["ok"] = response.ok and body.get("ok") is not False
    if body.get("modo") and body["modo"] != "nuvem":
        out.update(ok=False, message="O comunicador configurado no servidor não está em ACBR_MODO=nuvem.")
    elif not out["ok"]:
        out["message"] = body.get("mensagem") or f"Comunicador fiscal respondeu {response.status_code}."
    return out


def context(config, issuer, model):
    """O contexto inteiro do emitente (API.md §4): no modo nuvem vai em toda chamada."""
    if not config.certificate_file:
        raise BusinessError(f"Envie o certificado A1 nos dados fiscais de {config.name}.", code="certificate_missing")
    pfx = base64.b64encode(config.certificate_bytes()).decode()
    body = {
        "cnpj": only_digits(issuer.get("cnpj", "")), "uf": issuer.get("state", ""),
        "ambiente": config.environment, "modelo": model if model in ("55", "65") else "65",
        "certificado": {"pfx_base64": pfx, "senha": config.certificate_password or ""},
    }
    if body["modelo"] == "65":
        if not (config.csc_id and config.csc_token):
            raise BusinessError(f"Informe o CSC (id e código) nos dados fiscais de {config.name}.", code="csc_missing")
        body["csc"] = {"id": str(config.csc_id), "token": config.csc_token}
    return body


def pdv_call(config, issuer, path, body, fuso=""):
    """A ponte do PDV web: só rotas fiscais, só os campos do documento; o contexto é sempre daqui."""
    if path not in PDV_ROUTES:
        raise BusinessError("Rota do comunicador fiscal não permitida.", code="acbr_route")
    body = body if isinstance(body, dict) else {}
    document = {k: v for k, v in body.items() if k in PDV_FIELDS}
    payload = {**context(config, issuer, str(body.get("modelo") or "65")), **document}
    if isinstance(fuso, str) and len(fuso) == 6:
        payload["fuso"] = fuso
    return call(path, payload)


def cancel(invoice, reason):
    """Evento de cancelamento (110111) pela nuvem. Devolve o protocolo; recusa com a mensagem."""
    from starrp.services.fiscal_emission import issuer_of

    config = invoice.fiscal_config or invoice.store.fiscal_config
    if config is None:
        raise StateConflict("A nota não tem dados fiscais vinculados.", code="fiscal_config_missing")
    if not (invoice.access_key and invoice.protocol):
        raise StateConflict("A nota não tem chave e protocolo de autorização para cancelar.", code="invoice_no_protocol")
    answer = call("/v1/nfe/cancelar", {
        **context(config, issuer_of(config, invoice.store), invoice.document_model),
        "chave": invoice.access_key, "protocolo": invoice.protocol, "justificativa": reason,
    })
    data = answer.data
    if answer.trusted and data.get("situacao") == "cancelada":
        return str(data.get("protocolo") or "")
    reason_text = " ".join(filter(None, [str(data.get("cstat") or ""),
                                         str(data.get("motivo") or data.get("mensagem") or "")])).strip()
    raise StateConflict(f"A SEFAZ não confirmou o cancelamento: {reason_text or 'sem resposta do comunicador'}. "
                        "Nada foi alterado.", code="invoice_cancel_failed")
