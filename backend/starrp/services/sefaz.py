"""Conversa com a SEFAZ nacional (Ambiente Nacional) para notas de ENTRADA.

Dois serviços, os dois com TLS mútuo usando o certificado A1 dos dados fiscais:

- Distribuição DF-e (`NFeDistribuicaoDFe`): tudo que foi emitido contra o CNPJ,
  em lotes de até 50 por NSU. Vem resumo (`resNFe`) até o destinatário dar
  ciência; depois vem a nota completa (`procNFe`) com os itens.
- Recepção de evento (`NFeRecepcaoEvento4`): a manifestação do destinatário
  (ciência, confirmação, desconhecimento, não realizada), assinada (XMLDSig).

Exemplo de uso (o que `services.dfe` faz):
    page = distribution(config, last_nsu="0")      # lote seguinte
    event = send_event(config, chave, "210210")    # ciência → libera o XML
    page = distribution(config, access_key=chave)  # a nota completa
"""
import base64
import gzip
import hashlib
import logging
import os
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.core.text import only_digits
from starrp.models.fiscal import Environment
from starrp.services.fiscal_data import load_certificate

logger = logging.getLogger(__name__)

NFE_NS = "http://www.portalfiscal.inf.br/nfe"
DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
NS = {"nfe": NFE_NS, "soap": SOAP_NS}
TIMEOUT = 30

DIST_URL = {
    Environment.PRODUCTION: "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    Environment.HOMOLOGATION: "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
EVENT_URL = {
    Environment.PRODUCTION: "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    Environment.HOMOLOGATION: "https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
}
UF_CODES = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17", "MA": "21", "PI": "22",
    "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32",
    "RJ": "33", "SP": "35", "PR": "41", "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}
# Manifestação do destinatário: código → descrição exigida pelo leiaute.
EVENTS = {
    "210210": "Ciencia da Operacao",
    "210200": "Confirmacao da Operacao",
    "210220": "Desconhecimento da Operacao",
    "210240": "Operacao nao Realizada",
}


@dataclass
class RawDocument:
    nsu: str
    schema: str
    xml: str


@dataclass
class DistributionPage:
    cstat: str
    reason: str
    last_nsu: str | None
    max_nsu: str | None
    documents: list[RawDocument] = field(default_factory=list)


@dataclass
class EventResult:
    cstat: str
    reason: str
    protocol: str = ""
    request_xml: str = ""
    response_xml: str = ""

    @property
    def accepted(self):
        # 135 registrado e vinculado; 136 registrado sem vínculo; 573 duplicado (já estava feito).
        return self.cstat in ("135", "136", "573")


@contextmanager
def _tls_files(config):
    """O `requests` quer certificado e chave em arquivos PEM: temporários, apagados no fim."""
    key, cert = load_certificate(config)
    paths = []
    try:
        for data in (cert.public_bytes(serialization.Encoding.PEM),
                     key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption())):
            fd, path = tempfile.mkstemp(suffix=".pem")
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            paths.append(path)
        yield tuple(paths)
    finally:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass


def _post(config, url, body, action):
    envelope = (f'<?xml version="1.0" encoding="utf-8"?><soap12:Envelope xmlns:soap12="{SOAP_NS}"><soap12:Body>'
                f"{body}</soap12:Body></soap12:Envelope>")
    with _tls_files(config) as cert:
        try:
            response = requests.post(url, data=envelope.encode("utf-8"), cert=cert, timeout=TIMEOUT,
                                     headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"'})
            response.raise_for_status()
        except requests.RequestException as error:
            logger.warning("SEFAZ %s falhou: %s", action, error)
            raise BusinessError(f"Sem resposta da SEFAZ: {error}", code="sefaz_unavailable") from None
    return response.text


def _uf(config):
    code = UF_CODES.get((config.state or "").upper())
    if code is None:
        raise BusinessError(f"Informe a UF no endereço dos dados fiscais de {config.name}.", code="fiscal_no_state")
    return code


def distribution(config, *, last_nsu=None, nsu=None, access_key=None) -> DistributionPage:
    """Um lote da distribuição: depois de `last_nsu`, um NSU exato ou uma chave."""
    if access_key:
        query = f"<consChNFe><chNFe>{access_key}</chNFe></consChNFe>"
    elif nsu:
        query = f"<consNSU><NSU>{str(nsu).zfill(15)}</NSU></consNSU>"
    else:
        query = f"<distNSU><ultNSU>{str(last_nsu or '0').zfill(15)}</ultNSU></distNSU>"
    body = (f'<nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"><nfeDadosMsg>'
            f'<distDFeInt xmlns="{NFE_NS}" versao="1.01"><tpAmb>{config.environment}</tpAmb>'
            f"<cUFAutor>{_uf(config)}</cUFAutor><CNPJ>{only_digits(config.cnpj)}</CNPJ>{query}</distDFeInt>"
            f"</nfeDadosMsg></nfeDistDFeInteresse>")
    action = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"
    return parse_distribution(_post(config, DIST_URL[config.environment], body, action))


def parse_distribution(text) -> DistributionPage:
    root = ET.fromstring(text)
    ret = root.find(".//nfe:retDistDFeInt", NS)
    if ret is None:
        raise BusinessError("Resposta inesperada da SEFAZ na distribuição.", code="sefaz_bad_response")

    def get(tag):
        node = ret.find(f"nfe:{tag}", NS)
        return node.text if node is not None else None

    documents = []
    for zipped in ret.findall("nfe:loteDistDFeInt/nfe:docZip", NS):
        try:
            content = gzip.decompress(base64.b64decode(zipped.text or "")).decode("utf-8")
        except (OSError, ValueError):
            logger.error("docZip NSU %s ilegível", zipped.get("NSU"))
            continue
        documents.append(RawDocument(nsu=zipped.get("NSU", ""), schema=zipped.get("schema", ""), xml=content))
    # Sem ultNSU na resposta devolve None: nunca zerar o cursor salvo por engano.
    return DistributionPage(cstat=get("cStat") or "", reason=get("xMotivo") or "", last_nsu=get("ultNSU"),
                            max_nsu=get("maxNSU"), documents=documents)


def sign(xml_text, reference_id, key, cert):
    """XMLDSig da NF-e: C14N 1.0, RSA-SHA1, enveloped, sem prefixo `ds:`.
    Assina o `<infEvento Id=...>` e põe a `<Signature>` logo depois dele."""
    start = xml_text.index("<infEvento ")
    end = xml_text.index("</infEvento>", start) + len("</infEvento>")
    node = xml_text[start:end]
    if "xmlns=" not in node.split(">", 1)[0]:
        node = node.replace("<infEvento ", f'<infEvento xmlns="{NFE_NS}" ', 1)
    digest = base64.b64encode(hashlib.sha1(ET.canonicalize(node).encode()).digest()).decode()
    signed_info = (
        f'<SignedInfo xmlns="{DSIG_NS}"><CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        f'<SignatureMethod Algorithm="{DSIG_NS}rsa-sha1"/><Reference URI="#{reference_id}"><Transforms>'
        f'<Transform Algorithm="{DSIG_NS}enveloped-signature"/>'
        f'<Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/></Transforms>'
        f'<DigestMethod Algorithm="{DSIG_NS}sha1"/><DigestValue>{digest}</DigestValue></Reference></SignedInfo>'
    )
    value = base64.b64encode(key.sign(ET.canonicalize(signed_info).encode(), padding.PKCS1v15(), hashes.SHA1())).decode()
    certificate = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
    signature = (f'<Signature xmlns="{DSIG_NS}">{signed_info}<SignatureValue>{value}</SignatureValue>'
                 f"<KeyInfo><X509Data><X509Certificate>{certificate}</X509Certificate></X509Data></KeyInfo></Signature>")
    return xml_text[:end] + signature + xml_text[end:]


def event_xml(config, access_key, code, reason="", sequence=1):
    """`envEvento` da manifestação, ainda sem assinatura. Devolve (xml, Id)."""
    if code not in EVENTS:
        raise BusinessError("Manifestação desconhecida.")
    if code == "210240" and len(reason.strip()) < 15:
        raise BusinessError("Explique em pelo menos 15 caracteres por que a operação não foi realizada.")
    reference = f"ID{code}{access_key}{sequence:02d}"
    moment = timezone.localtime().isoformat(timespec="seconds")
    justification = f"<xJust>{reason.strip()[:255]}</xJust>" if code == "210240" else ""
    xml_text = (
        f'<envEvento xmlns="{NFE_NS}" versao="1.00"><idLote>{timezone.now().strftime("%y%m%d%H%M%S")}</idLote>'
        f'<evento versao="1.00"><infEvento Id="{reference}"><cOrgao>91</cOrgao><tpAmb>{config.environment}</tpAmb>'
        f"<CNPJ>{only_digits(config.cnpj)}</CNPJ><chNFe>{access_key}</chNFe><dhEvento>{moment}</dhEvento>"
        f"<tpEvento>{code}</tpEvento><nSeqEvento>{sequence}</nSeqEvento><verEvento>1.00</verEvento>"
        f'<detEvento versao="1.00"><descEvento>{EVENTS[code]}</descEvento>{justification}</detEvento>'
        f"</infEvento></evento></envEvento>"
    )
    return xml_text, reference


def send_event(config, access_key, code, reason="") -> EventResult:
    """Assina e envia a manifestação; devolve o que a SEFAZ disse do evento."""
    key, cert = load_certificate(config)
    xml_text, reference = event_xml(config, access_key, code, reason)
    signed = sign(xml_text, reference, key, cert)
    body = f'<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">{signed}</nfeDadosMsg>'
    action = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4/nfeRecepcaoEvento"
    text = _post(config, EVENT_URL[config.environment], body, action)
    return parse_event(text, signed)


def parse_event(text, request_xml="") -> EventResult:
    root = ET.fromstring(text)
    node = root.find(".//nfe:retEvento/nfe:infEvento", NS)
    if node is None:  # lote recusado inteiro: o motivo vem no retEnvEvento
        node = root.find(".//nfe:retEnvEvento", NS)
    if node is None:
        raise BusinessError("Resposta inesperada da SEFAZ no evento.", code="sefaz_bad_response")

    def get(tag):
        found = node.find(f"nfe:{tag}", NS)
        return found.text or "" if found is not None else ""

    return EventResult(cstat=get("cStat"), reason=get("xMotivo"), protocol=get("nProt"), request_xml=request_xml,
                       response_xml=text)
