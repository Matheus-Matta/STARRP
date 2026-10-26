"""Dados fiscais e notas de entrada pela SEFAZ (DF-e), com a SEFAZ simulada.

O caminho testado é o do dia a dia: o fornecedor emite → a busca traz o
resumo → ciência automática → XML completo → itens casados pelo EAN → entrada
em rascunho → conferência pelo coletor → aprovação → estoque e contas a pagar.
"""
import base64
import gzip
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
from django.core.files.uploadedfile import SimpleUploadedFile

from starrp.models import (
    FinancialTitle, FiscalConfig, InboundNFe, LogisticsSettings, NFeIssue, ProductBarcode, StockDocument, Store,
)
from starrp.services import dfe, fiscal_data, sefaz, stock

from .nfe_fixture import UNIT_EAN, nfe_xml

CNPJ = "11222333000181"
KEY = "35261012345678000199550010000012341000012345"


def pfx(cnpj=CNPJ, password=b"1234"):
    """Certificado A1 de teste (autoassinado), com o CNPJ no CN como os reais."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, f"LOJA TESTE LTDA:{cnpj}")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(days=365))
            .sign(key, hashes.SHA256()))
    return serialize_key_and_certificates(b"teste", key, cert, None,
                                          serialization.BestAvailableEncryption(password))


def zipped(xml_text):
    data = xml_text if isinstance(xml_text, bytes) else xml_text.encode()
    return base64.b64encode(gzip.compress(data)).decode()


def answer(cstat, docs=(), last="0", maximum="0"):
    """Resposta SOAP da distribuição com os documentos [(nsu, schema, xml)]."""
    lote = "".join(f'<docZip NSU="{n}" schema="{schema}">{zipped(x)}</docZip>' for n, schema, x in docs)
    return (f'<soap:Envelope xmlns:soap="{sefaz.SOAP_NS}"><soap:Body><retDistDFeInt xmlns="{sefaz.NFE_NS}">'
            f"<cStat>{cstat}</cStat><xMotivo>ok</xMotivo><ultNSU>{last}</ultNSU><maxNSU>{maximum}</maxNSU>"
            f"<loteDistDFeInt>{lote}</loteDistDFeInt></retDistDFeInt></soap:Body></soap:Envelope>")


SUMMARY = (f'<resNFe xmlns="{sefaz.NFE_NS}" versao="1.01"><chNFe>{KEY}</chNFe><CNPJ>12345678000199</CNPJ>'
           f"<xNome>Distribuidora Exemplo LTDA</xNome><dhEmi>2026-10-20T10:00:00-03:00</dhEmi><vNF>87.80</vNF>"
           f"<cSitNFe>1</cSitNFe></resNFe>")
CANCEL = (f'<resEvento xmlns="{sefaz.NFE_NS}" versao="1.01"><chNFe>{KEY}</chNFe><tpEvento>110111</tpEvento>'
          f"<nSeqEvento>1</nSeqEvento><xEvento>Cancelamento</xEvento><nProt>135260000000001</nProt></resEvento>")


class FakeSefaz:
    """Troca o `_post` (HTTP com certificado) por respostas prontas, por serviço."""

    def __init__(self, monkeypatch):
        self.pages, self.by_key, self.events = [], {}, []
        monkeypatch.setattr(sefaz, "_post", self.post)

    def post(self, config, url, body, action):
        if "RecepcaoEvento" in action:
            self.events.append(body)
            return (f'<soap:Envelope xmlns:soap="{sefaz.SOAP_NS}"><soap:Body><retEnvEvento xmlns="{sefaz.NFE_NS}">'
                    f"<cStat>128</cStat><retEvento><infEvento><cStat>135</cStat><xMotivo>Evento registrado</xMotivo>"
                    f"<nProt>135260000000009</nProt></infEvento></retEvento></retEnvEvento></soap:Body></soap:Envelope>")
        if "<consChNFe>" in body:
            key = body.split("<chNFe>")[1][:44]
            return self.by_key.get(key) or answer("137")
        return self.pages.pop(0) if self.pages else answer("137")


@pytest.fixture
def fiscal(ctx):
    ctx.account.extra_modules = ["stock", "inbound_nfe", "finance", "fiscal"]
    ctx.account.save()
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj=CNPJ, state="SP", legal_name="Loja Teste LTDA")
    ctx.store.refresh_from_db()
    config = fiscal_data.from_store(ctx.store)
    fiscal_data.save_certificate(config, SimpleUploadedFile("a1.pfx", pfx()), "1234")
    soda = ctx.product(name="Refrigerante Lata", sku="REFRI", price="5.00")
    ProductBarcode.all_objects.create(account=ctx.account, variant=soda, code=UNIT_EAN)
    yogurt = ctx.product(name="Iogurte Natural", sku="IOG", price="6.00", track_lots=True)
    ProductBarcode.all_objects.create(account=ctx.account, variant=yogurt, code="7891000999998")
    return ctx, FiscalConfig.all_objects.get(pk=config.pk), soda, yogurt


def test_dados_fiscais_nascem_da_loja_e_guardam_o_certificado(fiscal):
    """Copia razão social/UF da loja, vincula, cria as séries e lê titular e validade do A1."""
    ctx, config, _, _ = fiscal
    body = ctx.client().get(f"/api/v1/fiscal/configs/{config.pk}/").json()

    assert (config.cnpj, config.legal_name, config.state) == (CNPJ, "Loja Teste LTDA", "SP")
    assert body["stores"] == [str(ctx.store.pk)] and body["has_certificate"] is True
    assert body["certificate_cnpj"] == CNPJ and "certificate_password" not in body
    assert config.series.count() == 2


def test_certificado_com_senha_errada_ou_de_outra_empresa_e_recusado(fiscal):
    ctx, config, _, _ = fiscal
    api = ctx.client()
    url = f"/api/v1/fiscal/configs/{config.pk}/certificate/"

    wrong = api.post(url, {"file": SimpleUploadedFile("a.pfx", pfx()), "password": "errada"}, format="multipart")
    other = api.post(url, {"file": SimpleUploadedFile("a.pfx", pfx("99888777000166")), "password": "1234"},
                     format="multipart")

    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "certificate_invalid"
    assert other.status_code == 422 and other.json()["error"]["code"] == "certificate_other_cnpj"


def test_assinatura_da_manifestacao_confere_com_o_certificado():
    """XMLDSig sem prefixo: o digest bate com o infEvento e a assinatura com a chave pública."""
    key, cert, _ = fiscal_data.read_certificate(pfx(), "1234")
    config = FiscalConfig(cnpj=CNPJ, environment="2")
    xml_text, reference = sefaz.event_xml(config, KEY, "210210")

    signed = sefaz.sign(xml_text, reference, key, cert)

    root = ET.fromstring(signed)
    ns = {"d": sefaz.DSIG_NS}
    node = signed[signed.index("<infEvento "):signed.index("</infEvento>") + 12].replace(
        "<infEvento ", f'<infEvento xmlns="{sefaz.NFE_NS}" ', 1)
    digest = base64.b64encode(hashlib.sha1(ET.canonicalize(node).encode()).digest()).decode()
    info = signed[signed.index("<SignedInfo"):signed.index("</SignedInfo>") + 13]
    assert root.find(".//d:DigestValue", ns).text == digest and "ds:" not in signed
    cert.public_key().verify(base64.b64decode(root.find(".//d:SignatureValue", ns).text),
                             ET.canonicalize(info).encode(), padding.PKCS1v15(), hashes.SHA1())


def test_busca_traz_resumo_da_ciencia_baixa_xml_e_gera_entrada(fiscal, monkeypatch):
    """Resumo → ciência automática (evento assinado) → XML completo → itens pelo EAN → entrada em rascunho."""
    ctx, config, soda, _ = fiscal
    fake = FakeSefaz(monkeypatch)
    fake.pages = [answer("138", [("000000000000101", "resNFe_v1.01.xsd", SUMMARY)], last="101", maximum="101")]
    fake.by_key[KEY] = answer("138", [("000000000000102", "procNFe_v4.00.xsd", nfe_xml())])

    result = ctx.client().post(f"/api/v1/fiscal/configs/{config.pk}/sync-dfe/", {}, format="json")

    assert result.status_code == 200, result.json()
    nfe = InboundNFe.all_objects.get(access_key=KEY)
    assert result.json()["notes"] == 1 and len(fake.events) == 1 and "<tpEvento>210210</tpEvento>" in fake.events[0]
    assert (nfe.manifestation, nfe.xml_status, nfe.fiscal_config_id) == ("science", "available", config.pk)
    assert nfe.items.count() == 2 and nfe.items.get(item_number=1).variant_id == soda.pk
    assert nfe.stage == "pending_mapping"  # o iogurte da nota vem sem EAN: alguém vincula


def test_vinculado_o_ultimo_item_a_entrada_nasce_e_so_aprova_depois_da_conferencia(fiscal, monkeypatch):
    """Nota → entrada em rascunho → conferência pelo coletor (faltou 1 lata) → aprovação."""
    ctx, config, soda, yogurt = fiscal
    api = ctx.client()
    fake = FakeSefaz(monkeypatch)
    fake.pages = [answer("138", [("000000000000102", "procNFe_v4.00.xsd", nfe_xml())], last="102", maximum="102")]
    dfe.sync(config)
    nfe = InboundNFe.all_objects.get(access_key=KEY)
    item = nfe.items.get(item_number=2)

    api.post(f"/api/v1/inbound-nfe/{nfe.pk}/map-item/", {"item": str(item.pk), "variant": str(yogurt.pk)},
             format="json")
    doc = StockDocument.all_objects.get(inbound_nfe=nfe)
    blocked = api.post(f"/api/v1/stock/documents/{doc.pk}/post/", {}, format="json")
    codes = [UNIT_EAN] * 23 + ["7891000999998"] * 10
    checked = api.post(f"/api/v1/stock/documents/{doc.pk}/check/", {"codes": codes}, format="json")
    approved = api.post(f"/api/v1/stock/documents/{doc.pk}/post/", {}, format="json")

    assert (doc.status, doc.warehouse_id) == ("draft", stock.default_warehouse(ctx.store).pk)
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "conference_required"
    assert checked.status_code == 200, checked.json()
    assert approved.status_code == 200, approved.json()
    assert stock.available(soda) == Decimal("23") and stock.available(yogurt) == Decimal("10")
    nfe.refresh_from_db()
    assert nfe.receiving == InboundNFe.Receiving.DIVERGENT
    assert FinancialTitle.all_objects.filter(inbound_nfe=nfe).count() == 1  # duplicatas só na aprovação


def test_leitura_de_produto_fora_da_nota_barra_a_conferencia(fiscal, monkeypatch):
    ctx, config, _, yogurt = fiscal
    other = ctx.product(name="Biscoito", sku="BIS", price="3.00")
    ProductBarcode.all_objects.create(account=ctx.account, variant=other, code="7891000888887")
    nfe = InboundNFe.all_objects.get(pk=ctx.client().post(
        "/api/v1/inbound-nfe/import/", {"file": SimpleUploadedFile("n.xml", nfe_xml())}, format="multipart"
    ).json()["id"])
    item = nfe.items.get(item_number=2)
    ctx.client().post(f"/api/v1/inbound-nfe/{nfe.pk}/map-item/", {"item": str(item.pk), "variant": str(yogurt.pk)},
                      format="json")
    doc = StockDocument.all_objects.get(inbound_nfe=nfe)

    response = ctx.client().post(f"/api/v1/stock/documents/{doc.pk}/check/", {"codes": ["7891000888887"]},
                                 format="json")

    assert response.status_code == 422 and response.json()["error"]["code"] == "conference_unexpected"


def test_cancelamento_do_fornecedor_derruba_o_rascunho_ou_abre_pendencia(fiscal, monkeypatch):
    """Rascunho de entrada cai; se já tinha entrado no estoque, vira pendência para decidir."""
    ctx, config, _, yogurt = fiscal
    fake = FakeSefaz(monkeypatch)
    fake.pages = [answer("138", [("000000000000102", "procNFe_v4.00.xsd", nfe_xml())], last="102", maximum="102")]
    dfe.sync(config)
    nfe = InboundNFe.all_objects.get(access_key=KEY)
    ctx.client().post(f"/api/v1/inbound-nfe/{nfe.pk}/map-item/",
                      {"item": str(nfe.items.get(item_number=2).pk), "variant": str(yogurt.pk)}, format="json")
    # "Receber e aprovar de uma vez" é conferência manual: precisa estar liberada na Logística.
    LogisticsSettings.all_objects.update_or_create(store=ctx.store, defaults={"account": ctx.account,
                                                                              "allow_manual_conference": True})
    ctx.client().post(f"/api/v1/inbound-nfe/{nfe.pk}/receive/", {"post": True}, format="json")
    fake.pages = [answer("138", [("000000000000103", "resEvento_v1.01.xsd", CANCEL)], last="103", maximum="103")]
    from starrp.models import DFeSyncState
    DFeSyncState.all_objects.filter(config=config).update(next_allowed_at=None)

    dfe.sync(config)

    nfe.refresh_from_db()
    assert nfe.fiscal_status == "cancelled"
    assert NFeIssue.all_objects.filter(nfe=nfe, kind="cancelled_after_receipt", status="open").exists()


def test_nada_novo_faz_esperar_uma_hora(fiscal, monkeypatch):
    """cStat 137: a SEFAZ bloqueia quem pergunta de novo antes de 1 hora."""
    ctx, config, _, _ = fiscal
    FakeSefaz(monkeypatch)

    first = ctx.client().post(f"/api/v1/fiscal/configs/{config.pk}/sync-dfe/", {}, format="json")
    again = ctx.client().post(f"/api/v1/fiscal/configs/{config.pk}/sync-dfe/", {}, format="json")

    assert first.status_code == 200 and first.json()["cstat"] == "137"
    assert again.status_code == 409 and again.json()["error"]["code"] == "dfe_wait"
