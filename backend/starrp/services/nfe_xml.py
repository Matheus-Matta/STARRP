"""Leitura do XML da NF-e (layout 4.00), com ou sem o envelope `nfeProc`.

Só lê; quem grava é `services.inbound_nfe`. Usa o parser seguro da
biblioteca padrão com entidades bloqueadas (XML vem de fora: o fornecedor).
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from starrp.core.errors import BusinessError

NS = {"n": "http://www.portalfiscal.inf.br/nfe"}
NO_GTIN = {"", "SEM GTIN"}


@dataclass
class NFeItem:
    number: int
    supplier_code: str
    barcode: str
    taxable_barcode: str
    description: str
    ncm: str
    cest: str
    cfop: str
    unit: str
    quantity: Decimal
    unit_value: Decimal
    taxable_unit: str
    taxable_quantity: Decimal
    taxable_unit_value: Decimal
    total: Decimal
    discount: Decimal
    freight: Decimal
    insurance: Decimal
    other_expenses: Decimal
    taxes: dict
    lots: list = field(default_factory=list)


@dataclass
class NFeData:
    access_key: str
    number: str
    series: str
    issued_at: datetime | None
    emitter: dict
    recipient_document: str
    products_total: Decimal
    total: Decimal
    status_code: str
    protocol: str
    items: list[NFeItem]
    installments: list[dict]


def _text(node, path, default=""):
    found = node.find(path, NS) if node is not None else None
    return (found.text or "").strip() if found is not None and found.text else default


def _dec(node, path):
    try:
        return Decimal(_text(node, path, "0") or "0")
    except InvalidOperation:
        return Decimal("0")


def _barcode(value):
    return "" if value.upper() in NO_GTIN else value


def _date(value):
    try:
        return date.fromisoformat(value[:10]).isoformat() if value else None
    except ValueError:
        return None


def _taxes(imposto):
    """O que entra no custo de compra: IPI e ICMS-ST (o ICMS próprio é recuperável
    em regime normal e, no Simples, não se credita — fica fora por padrão)."""
    return {
        "ipi": str(_dec(imposto, ".//n:IPI/n:IPITrib/n:vIPI")),
        "icms_st": str(_dec(imposto, ".//n:ICMS/*/n:vICMSST")),
        "icms": str(_dec(imposto, ".//n:ICMS/*/n:vICMS")),
    }


def _item(det):
    prod = det.find("n:prod", NS)
    lots = [
        {"number": _text(r, "n:nLote"), "quantity": str(_dec(r, "n:qLote")),
         "manufactured_at": _date(_text(r, "n:dFab")), "expires_at": _date(_text(r, "n:dVal"))}
        for r in prod.findall("n:rastro", NS)
    ]
    return NFeItem(
        number=int(det.get("nItem", "0")),
        supplier_code=_text(prod, "n:cProd"),
        barcode=_barcode(_text(prod, "n:cEAN")),
        taxable_barcode=_barcode(_text(prod, "n:cEANTrib")),
        description=_text(prod, "n:xProd")[:255],
        ncm=_text(prod, "n:NCM"),
        cest=_text(prod, "n:CEST"),
        cfop=_text(prod, "n:CFOP"),
        unit=_text(prod, "n:uCom")[:6],
        quantity=_dec(prod, "n:qCom"),
        unit_value=_dec(prod, "n:vUnCom"),
        taxable_unit=_text(prod, "n:uTrib")[:6],
        taxable_quantity=_dec(prod, "n:qTrib"),
        taxable_unit_value=_dec(prod, "n:vUnTrib"),
        total=_dec(prod, "n:vProd"),
        discount=_dec(prod, "n:vDesc"),
        freight=_dec(prod, "n:vFrete"),
        insurance=_dec(prod, "n:vSeg"),
        other_expenses=_dec(prod, "n:vOutro"),
        taxes=_taxes(det.find("n:imposto", NS)),
        lots=lots,
    )


def parse(content: bytes) -> NFeData:
    if b"<!ENTITY" in content or b"<!DOCTYPE" in content:
        raise BusinessError("XML com declarações de entidade não é aceito.", code="nfe_invalid")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise BusinessError(f"Arquivo não é um XML válido: {exc}", code="nfe_invalid") from None
    inf = root.find(".//n:infNFe", NS)
    if inf is None:
        raise BusinessError("O arquivo não é uma NF-e (infNFe não encontrado).", code="nfe_invalid")
    if _text(inf, "n:ide/n:mod") not in ("55", ""):
        raise BusinessError("Só NF-e modelo 55 é aceita na entrada.", code="nfe_invalid")
    emit = inf.find("n:emit", NS)
    address = inf.find("n:emit/n:enderEmit", NS)
    issued = _text(inf, "n:ide/n:dhEmi") or _text(inf, "n:ide/n:dEmi")
    return NFeData(
        access_key=(inf.get("Id") or "").removeprefix("NFe"),
        number=_text(inf, "n:ide/n:nNF"),
        series=_text(inf, "n:ide/n:serie"),
        issued_at=datetime.fromisoformat(issued) if len(issued) > 10 else None,
        emitter={
            "document": _text(emit, "n:CNPJ") or _text(emit, "n:CPF"),
            "legal_name": _text(emit, "n:xNome"),
            "name": _text(emit, "n:xFant") or _text(emit, "n:xNome"),
            "state_registration": _text(emit, "n:IE"),
            "street": _text(address, "n:xLgr"), "number": _text(address, "n:nro"),
            "district": _text(address, "n:xBairro"), "city": _text(address, "n:xMun"),
            "city_ibge": _text(address, "n:cMun"), "state": _text(address, "n:UF"), "zip_code": _text(address, "n:CEP"),
            "phone": _text(address, "n:fone"),
        },
        recipient_document=_text(inf, "n:dest/n:CNPJ") or _text(inf, "n:dest/n:CPF"),
        products_total=_dec(inf, "n:total/n:ICMSTot/n:vProd"),
        total=_dec(inf, "n:total/n:ICMSTot/n:vNF"),
        status_code=_text(root, ".//n:protNFe/n:infProt/n:cStat"),
        protocol=_text(root, ".//n:protNFe/n:infProt/n:nProt"),
        items=[_item(det) for det in inf.findall("n:det", NS)],
        installments=[
            {"number": _text(d, "n:nDup"), "due_date": _date(_text(d, "n:dVenc")), "amount": str(_dec(d, "n:vDup"))}
            for d in inf.findall("n:cobr/n:dup", NS)
        ],
    )
