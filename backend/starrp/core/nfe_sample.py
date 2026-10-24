"""XML de NF-e 4.00 de exemplo (estrutura real, valores fictícios): testes e a demonstração."""
from starrp.services.barcodes import ean_check_digit_ok


def ean(body):
    """Completa o dígito verificador de um GTIN."""
    return next(body + d for d in "0123456789" if ean_check_digit_ok(body + d))


UNIT_EAN = ean("789100031550")  # a lata (unidade)
BOX_EAN = ean("1789100031550")  # a caixa com 12 (GTIN-14)


def nfe_xml(*, key="35261012345678000199550010000012341000012345", recipient="11222333000181",
            supplier="12345678000199", number="1234", lot_code="LT-778"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
 <NFe><infNFe Id="NFe{key}" versao="4.00">
  <ide><mod>55</mod><serie>1</serie><nNF>{number}</nNF><dhEmi>2026-10-20T10:00:00-03:00</dhEmi></ide>
  <emit><CNPJ>{supplier}</CNPJ><xNome>Distribuidora Exemplo LTDA</xNome><xFant>Distribuidora Exemplo</xFant>
   <enderEmit><xLgr>Rua A</xLgr><nro>10</nro><xBairro>Centro</xBairro><cMun>3550308</cMun><xMun>Sao Paulo</xMun>
   <UF>SP</UF><CEP>01001000</CEP></enderEmit><IE>123456789</IE></emit>
  <dest><CNPJ>{recipient}</CNPJ><xNome>Loja</xNome></dest>
  <det nItem="1"><prod><cProd>REF-LATA</cProd><cEAN>{BOX_EAN}</cEAN><xProd>REFRIGERANTE LATA CX 12</xProd>
    <NCM>22021000</NCM><CFOP>5102</CFOP><uCom>CX</uCom><qCom>2.0000</qCom><vUnCom>24.0000000000</vUnCom>
    <vProd>48.00</vProd><cEANTrib>{UNIT_EAN}</cEANTrib><uTrib>UN</uTrib><qTrib>24.0000</qTrib>
    <vUnTrib>2.0000000000</vUnTrib><vFrete>2.40</vFrete><indTot>1</indTot></prod>
   <imposto><IPI><IPITrib><vIPI>2.40</vIPI></IPITrib></IPI></imposto></det>
  <det nItem="2"><prod><cProd>REF-IOG</cProd><cEAN>SEM GTIN</cEAN><xProd>IOGURTE NATURAL 170G</xProd>
    <NCM>04031000</NCM><CFOP>5102</CFOP><uCom>UN</uCom><qCom>10.0000</qCom><vUnCom>3.0000000000</vUnCom>
    <vProd>30.00</vProd><cEANTrib>SEM GTIN</cEANTrib><uTrib>UN</uTrib><qTrib>10.0000</qTrib>
    <vUnTrib>3.0000000000</vUnTrib><indTot>1</indTot>
    <rastro><nLote>{lot_code}</nLote><qLote>10.000</qLote><dFab>2026-10-01</dFab><dVal>2026-11-30</dVal></rastro>
   </prod><imposto/></det>
  <total><ICMSTot><vProd>78.00</vProd><vNF>82.80</vNF></ICMSTot></total>
  <cobr><dup><nDup>001</nDup><dVenc>2026-11-20</dVenc><vDup>41.40</vDup></dup>
   <dup><nDup>002</nDup><dVenc>2026-12-20</dVenc><vDup>41.40</vDup></dup></cobr>
 </infNFe></NFe>
 <protNFe versao="4.00"><infProt><chNFe>{key}</chNFe><nProt>135260000000001</nProt><cStat>100</cStat></infProt></protNFe>
</nfeProc>""".encode()
