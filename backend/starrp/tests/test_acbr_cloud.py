"""Comunicador Fiscal em NUVEM: a ponte do PDV web (`/pdv/acbr/`), a cifra e o cancelamento."""
import base64
import json
import json as jsonlib
import os

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.utils import timezone

from starrp.core.errors import StateConflict
from starrp.models import Invoice
from starrp.services import acbr_cloud, invoice_cancel
from starrp.tests.test_pdv_offline_fiscal import _fiscal

KEY = base64.b64encode(b"k" * 32).decode()


def _side(side):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"acbr-e2e-v1 {side}".encode()).derive(b"k" * 32)


class FakeCommunicator:
    """O lado do servidor do comunicador (docs/API.md §3), escrito à parte do cliente."""

    def __init__(self, answer, status=200):
        self.answer, self.status, self.calls = answer, status, []

    def post(self, url, json=None, timeout=None, headers=None):
        envelope = json
        path = "/" + url.split("/", 3)[3]
        aad = f"acbr-e2e-v1\nPOST\n{path}\n{envelope['ts']}\n{envelope['nonce']}".encode()
        plain = AESGCM(_side("pedido")).decrypt(base64.b64decode(envelope["nonce"]),
                                                base64.b64decode(envelope["dados"]), aad)
        self.calls.append({"path": path, "body": jsonlib.loads(plain), "headers": headers})
        nonce = os.urandom(12)
        sealed = AESGCM(_side("resposta")).encrypt(
            nonce, jsonlib.dumps(self.answer).encode(),
            f"acbr-e2e-v1\n{self.status}\n{envelope['nonce']}".encode())
        return _Response(self.status, {"v": 1, "nonce": base64.b64encode(nonce).decode(),
                                       "dados": base64.b64encode(sealed).decode()})


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body, self.ok = status, body, status < 400

    def json(self):
        return self._body


@pytest.fixture
def cloud(settings, monkeypatch):
    settings.ACBRLIB_URL, settings.ACBRLIB_TOKEN, settings.ACBR_E2E_KEY = "http://acbr:8030", "t" * 40, KEY

    def install(answer, status=200):
        fake = FakeCommunicator(answer, status)
        monkeypatch.setattr(acbr_cloud.requests, "post", fake.post)
        return fake
    return install


def _sale(ctx, price="30.00"):
    """A ponte só assina a nota de uma venda da filial, com o total dela (S-07)."""
    variant = ctx.product(name="Caneca", price=price, track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    return sale["id"]


INI = "[Identificacao]\n[Total]\nvNF=30.00\n"


def test_pdv_web_emite_pela_nuvem_com_o_certificado_do_servidor(ctx, cloud):
    _fiscal(ctx)
    sale = _sale(ctx)
    fake = cloud({"situacao": "autorizada", "cstat": "100", "chave": "3" * 44})
    api = ctx.client()

    answer = api.post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/emitir", "body": {
        "ini": INI, "tp_emis": "1", "modelo": "65", "fuso": "-03:00", "referencia": f"{sale}:65:1",
        # o que o navegador mandar de emitente é ignorado: vale o dos dados fiscais
        "cnpj": "99999999000199", "certificado": {"pfx_base64": "x", "senha": "y"}}}, format="json")

    assert answer.status_code == 200, answer.json()
    assert answer.json() == {"status": 200, "trusted": True,
                             "data": {"situacao": "autorizada", "cstat": "100", "chave": "3" * 44}}
    sent = fake.calls[0]
    assert sent["path"] == "/v1/nfe/emitir" and sent["headers"]["Authorization"] == "Bearer " + "t" * 40
    body = sent["body"]
    assert body["cnpj"] == "11222333000181" and body["uf"] == "SP" and body["modelo"] == "65"
    assert body["certificado"] == {"pfx_base64": base64.b64encode(b"pfx").decode(), "senha": "senha"}
    assert body["csc"] == {"id": "1", "token": "ABC"} and body["ini"] == INI
    assert body["fuso"] == "-03:00"


def test_ponte_nao_deixa_configurar_o_comunicador(ctx, cloud):
    _fiscal(ctx)
    cloud({})
    refused = ctx.client().post("/api/v1/pdv/acbr/", {"path": "/v1/config/ler", "body": {}}, format="json")
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "acbr_route"


def test_resposta_sem_envelope_nao_e_decisao_fiscal(ctx, cloud, monkeypatch):
    _fiscal(ctx)
    cloud({})
    monkeypatch.setattr(acbr_cloud.requests, "post",
                        lambda *a, **k: _Response(503, {"erro": "sem_comunicacao", "mensagem": "forjado"}))
    sale = _sale(ctx)
    answer = ctx.client().post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/emitir", "body": {
        "ini": INI, "referencia": f"{sale}:65:1"}}, format="json")
    # Um 503 sem cifra pode ter sido forjado no caminho: não vira contingência.
    assert answer.json()["trusted"] is False and answer.json()["data"]["erro"] == "sem_resposta"


def test_sem_configuracao_no_servidor_avisa(ctx, settings):
    _fiscal(ctx)
    settings.ACBRLIB_URL = ""
    answer = ctx.client().post("/api/v1/pdv/acbr/", {"path": "/v1/status-servico", "body": {}}, format="json")
    assert answer.status_code == 422 and answer.json()["error"]["code"] == "acbr_cloud_missing"


def _authorized(ctx, config):
    return Invoice.all_objects.create(
        account=ctx.account, store=ctx.store, fiscal_config=config, document_model="65", series=2, number=7,
        environment="2", status=Invoice.Status.AUTHORIZED, provider="acbrlib", access_key="3" * 44,
        protocol="135000000000001", authorized_at=timezone.now(), total="10.00")


def test_cancelamento_de_nota_acbr_vai_a_sefaz_pela_nuvem(ctx, cloud):
    config = _fiscal(ctx)
    invoice = _authorized(ctx, config)
    fake = cloud({"situacao": "cancelada", "cstat": "135", "protocolo": "135000000000099"})

    invoice_cancel.cancel_invoice(invoice, ctx.admin, "cliente desistiu da compra")

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.CANCELLED and invoice.cancel_protocol == "135000000000099"
    body = fake.calls[0]["body"]
    assert fake.calls[0]["path"] == "/v1/nfe/cancelar"
    assert body["chave"] == "3" * 44 and body["protocolo"] == "135000000000001"
    assert body["justificativa"] == "cliente desistiu da compra" and body["certificado"]["senha"] == "senha"


def test_cancelamento_recusado_nao_muda_nada(ctx, cloud):
    config = _fiscal(ctx)
    invoice = _authorized(ctx, config)
    cloud({"situacao": "rejeitada", "cstat": "501", "motivo": "Prazo de cancelamento superior"})

    with pytest.raises(StateConflict):
        invoice_cancel.cancel_invoice(invoice, ctx.admin, "cliente desistiu da compra")

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.AUTHORIZED and not invoice.cancel_protocol


def test_envelope_confere_com_o_exemplo_do_comunicador(settings):
    """Mesma cifra do `docs/exemplos/cliente_nuvem.py`: o servidor abre o que mandamos."""
    settings.ACBR_E2E_KEY = KEY
    envelope, nonce = acbr_cloud.seal("/v1/status-servico", {"a": 1}, ts=1794000000, nonce=b"\x01" * 12)
    aad = f"acbr-e2e-v1\nPOST\n/v1/status-servico\n1794000000\n{nonce}".encode()
    plain = AESGCM(_side("pedido")).decrypt(b"\x01" * 12, base64.b64decode(envelope["dados"]), aad)
    assert json.loads(plain) == {"a": 1} and envelope["v"] == 1


def test_ponte_recusa_nota_sem_venda_com_outro_total_e_nfe_sem_fiscal_manage(ctx, cloud):
    """S-07: o caixa não assina documento qualquer com o A1 da filial."""
    _fiscal(ctx)
    cloud({"situacao": "autorizada"})
    sale = _sale(ctx)
    cashier = ctx.user("caixa", "cashier")
    api = ctx.client(cashier)

    no_sale = api.post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/emitir", "body": {"ini": INI}}, format="json")
    other_total = api.post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/emitir", "body": {
        "ini": INI.replace("30.00", "9999.00"), "referencia": f"{sale}:65:1"}}, format="json")
    nfe = api.post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/emitir", "body": {
        "ini": INI, "modelo": "55", "referencia": f"{sale}:55:1"}}, format="json")

    assert no_sale.status_code == 422 and no_sale.json()["error"]["code"] == "acbr_sale_unknown"
    assert other_total.status_code == 422 and other_total.json()["error"]["code"] == "acbr_total_mismatch"
    assert nfe.status_code == 403


def test_ponte_le_o_ini_por_secao_e_so_transmite_nota_da_filial(ctx, cloud):
    """Rodada 1 (P-8): vNF de outra seção, modelo trocado e XML qualquer em `transmitir`."""
    _fiscal(ctx)
    cloud({"situacao": "autorizada"})
    sale = _sale(ctx)
    api = ctx.client()

    def emit(ini, **extra):
        return api.post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/emitir", "body": {
            "ini": ini, "referencia": f"{sale}:65:1", **extra}}, format="json")

    decoy = emit("[Identificacao]\n[X]\nvNF=30.00\n[Total]\nvNF=9999.00\n")
    twice = emit("[Total]\nvNF=30.00\nvNF=9999.00\n")
    nfe = emit("[Identificacao]\nmod=55\n[Total]\nvNF=30.00\n")
    transmit = api.post("/api/v1/pdv/acbr/", {"path": "/v1/nfe/transmitir", "body": {
        "xml": '<NFe><infNFe Id="NFe' + "3" * 44 + '"/></NFe>'}}, format="json")

    assert decoy.status_code == 422 and decoy.json()["error"]["code"] == "acbr_total_mismatch"
    assert twice.status_code == 422 and twice.json()["error"]["code"] == "acbr_ini_invalid"
    assert nfe.status_code == 422 and nfe.json()["error"]["code"] == "acbr_ini_invalid"
    assert transmit.status_code == 422 and transmit.json()["error"]["code"] == "acbr_invoice_unknown"
