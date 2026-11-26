# ruff: noqa: F811
from decimal import Decimal as D

import pytest

from starrp.models import (
    Account, DFeDocument, DFeSyncState, FinancialTitle, InboundNFe, RecurringTitle, StockDocument, Store,
)
from starrp.services import dfe, inbound_nfe
from starrp.tests.nfe_fixture import BOX_EAN, UNIT_EAN, nfe_xml
from starrp.tests.test_dfe import CANCEL, KEY, SUMMARY, FakeSefaz, answer, fiscal  # noqa: F401

PROC = "procNFe_v4.00.xsd"


def test_ambiente_trocado_nao_perde_nota(fiscal, monkeypatch):
    ctx, config, *_ = fiscal
    fake = FakeSefaz(monkeypatch)
    config.dfe_auto_science = False
    config.environment = "2"
    config.save()
    other = SUMMARY.replace(KEY, KEY[:-1] + "9")
    fake.pages = [answer("138", [("000000000000001", "resNFe_v1.01.xsd", other)], "1", "1")]
    dfe.sync(config)
    config.environment = "1"
    config.save()
    fake.pages = [answer("138", [("000000000000001", "resNFe_v1.01.xsd", SUMMARY)], "1", "1")]
    dfe.sync(config)
    assert InboundNFe.all_objects.filter(access_key=KEY).exists()


def test_falha_ao_gravar_nao_avanca_nsu(fiscal, monkeypatch):
    ctx, config, *_ = fiscal
    fake = FakeSefaz(monkeypatch)
    fake.pages = [answer("138", [("000000000000007", "resNFe_v1.01.xsd", SUMMARY)], "7", "7")]
    real = dfe._save
    monkeypatch.setattr(dfe, "_save", lambda *a: (_ for _ in ()).throw(RuntimeError("banco caiu")))
    with pytest.raises(RuntimeError):
        dfe.sync(config)
    monkeypatch.setattr(dfe, "_save", real)
    assert DFeSyncState.all_objects.get(config=config).last_nsu in ("0", "")


def test_documento_estragado_nao_trava_os_seguintes(fiscal, monkeypatch):
    ctx, config, *_ = fiscal
    config.dfe_auto_science = False
    config.save()
    fake = FakeSefaz(monkeypatch)
    bad = nfe_xml(key=KEY[:-1] + "8").replace(b"2026-10-20T10:00:00-03:00", b"2026-10-20T10:00:00-03")
    bad = bad.replace(b"<qCom>2.0000</qCom>", b"<qCom>0.0001</qCom>").replace(b"<qTrib>24.0000</qTrib>", b"<qTrib>99999999999.0000</qTrib>")
    docs = [("000000000000001", PROC, bad), ("000000000000002", "resNFe_v1.01.xsd", SUMMARY.replace(KEY, KEY[:-1] + "7"))]
    fake.pages = [answer("138", docs, "2", "2")]
    try:
        dfe.sync(config)
    except Exception:
        raise
    assert InboundNFe.all_objects.filter(access_key=KEY[:-1] + "7").exists(), list(DFeDocument.all_objects.values_list("nsu", "processing", "processing_error"))


def test_cancelamento_antes_da_nota(fiscal, monkeypatch):
    """Evento chega; a nota só entra depois (upload ou NSU fora de ordem)."""
    ctx, config, *_ = fiscal
    fake = FakeSefaz(monkeypatch)
    fake.pages = [answer("138", [("000000000000001", "resEvento_v1.01.xsd", CANCEL)], "1", "1")]
    dfe.sync(config)
    nfe = inbound_nfe.import_xml(ctx.store, nfe_xml(), ctx.admin)
    nfe.refresh_from_db()
    assert nfe.fiscal_status == "cancelled", nfe.fiscal_status


def test_mesmo_ean_na_caixa_e_na_unidade(fiscal):
    """Erro comum do fornecedor: cEAN = cEANTrib (a lata), uCom=CX qCom=2, uTrib=UN qTrib=24."""
    ctx, config, soda, _ = fiscal
    nfe = inbound_nfe.import_xml(ctx.store, nfe_xml().replace(BOX_EAN.encode(), UNIT_EAN.encode()), ctx.admin)
    item = nfe.items.get(item_number=1)
    item.refresh_from_db()
    assert item.variant_id is None or item.conversion_factor == 12, (item.variant_id, item.conversion_factor)


@pytest.mark.parametrize("tag", [b"<tpNF>0</tpNF>", b"<finNFe>2</finNFe>", b"<finNFe>3</finNFe>"])
def test_nota_que_nao_e_compra_nao_gera_entrada(fiscal, tag):
    ctx, config, soda, yog = fiscal
    xml = nfe_xml().replace(b"<mod>55</mod>", b"<mod>55</mod>" + tag).replace(b"SEM GTIN", b"7891000999998")
    nfe = inbound_nfe.import_xml(ctx.store, xml, ctx.admin)
    assert not StockDocument.all_objects.filter(inbound_nfe=nfe).exists()


def test_denegada_completa(fiscal):
    ctx, *_ = fiscal
    xml = nfe_xml().replace(b"<cStat>100</cStat>", b"<cStat>302</cStat>").replace(b"SEM GTIN", b"7891000999998")
    nfe = inbound_nfe.import_xml(ctx.store, xml, ctx.admin)
    assert nfe.fiscal_status == "denied" and not StockDocument.all_objects.filter(inbound_nfe=nfe).exists()


def test_motivo_com_e_comercial(fiscal, monkeypatch):
    ctx, config, *_ = fiscal
    FakeSefaz(monkeypatch)
    nfe = inbound_nfe.import_xml(ctx.store, nfe_xml(), ctx.admin)
    r = ctx.client().post(f"/api/v1/inbound-nfe/{nfe.pk}/manifest/", {"code": "210240", "reason": "Mercadoria da M&M < pedido, recusada"}, format="json")
    assert r.status_code < 500, r.content[:200]


def test_xml_quebrado_no_upload(fiscal):
    ctx, *_ = fiscal
    api = ctx.client()
    for a, b in ((b'nItem="1"', b'nItem="x"'), (b"2026-10-20T10:00:00-03:00", b"2026-99-20T10:00:00-03:00"),
                 (b"<det nItem=\"1\"><prod>", b"<det nItem=\"1\"><xprod>"), (b"<nNF>1234</nNF>", b"<nNF>1234567890123</nNF>"),
                 (b"<qCom>2.0000", b"<qCom>1E+30"), (b'nItem="2"', b'nItem="1"')):
        r = api.post("/api/v1/inbound-nfe/import/", {"xml": nfe_xml().replace(a, b).decode()}, format="json")
        assert r.status_code < 500, a


def test_conta_suspensa_nao_gera(fiscal, monkeypatch):
    ctx, config, *_ = fiscal
    calls = []
    monkeypatch.setattr(dfe, "sync", lambda c, *a: calls.append(c) or {})
    Account.objects.filter(pk=ctx.account.pk).update(status=[s for s in Account.Status.values if s != "active"][-1])
    dfe.sync_all()
    assert not calls


def test_modulo_desligado_nao_busca(fiscal, monkeypatch):
    ctx, config, *_ = fiscal
    calls = []
    monkeypatch.setattr(dfe, "sync", lambda c, *a: calls.append(c) or {})
    ctx.account.extra_modules = []
    ctx.account.save()
    if ctx.account.has_module("inbound_nfe"):
        pytest.skip("plano")
    dfe.sync_all()
    assert not calls


def test_recorrencia_conta_suspensa(ctx):
    import datetime
    RecurringTitle.all_objects.create(account=ctx.account, store=ctx.store, kind="payable", description="aluguel", amount=D(10), start_date=datetime.date.today())
    Account.objects.filter(pk=ctx.account.pk).update(status=[s for s in Account.Status.values if s != "active"][-1])
    from starrp.services import recurring
    recurring.generate_all()
    assert not FinancialTitle.all_objects.filter(account=ctx.account).exists()


def test_filial_desativada_vende(ctx):
    u = ctx.user("cxx", "cashier")
    Store.all_objects.filter(pk=ctx.store.pk).update(is_active=False)
    r = ctx.client(u).post("/api/v1/sales/", {}, format="json")
    assert r.status_code >= 400, r.status_code


@pytest.mark.parametrize("v", ["Infinity", "NaN", "1e400"])
def test_metacampo_numero(ctx, v):
    from starrp.models import MetafieldDefinition
    MetafieldDefinition.all_objects.create(account=ctx.account, owner="sale", key="n", name="N", type="number")
    api = ctx.client()
    sid = api.post("/api/v1/sales/", {}, format="json").json()["id"]
    r = api.post(f"/api/v1/sales/{sid}/metafields/", {"metafields": {"n": v}}, format="json")
    assert r.status_code == 400, r.status_code


def test_cartao_cosmos_mostra_tudo():
    from starrp.services.cosmos import tools
    body = {"items": [{"a": "x" * 4100}, {"approved_discount": "100"}]}
    row = tools._preview(type("C", (), {"actor": None})(), "POST", "sales/", body, [])[0]
    assert "approved_discount" in row["detail"]
