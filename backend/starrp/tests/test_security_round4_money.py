"""Rodada 4 (docs/SEGURANCA.md): venda, caixa, desconto, devolução e numeração fiscal."""
import uuid
from decimal import Decimal

from starrp.models import (
    CashDiscrepancy, CashMovement, CashSession, Customer, CustomerCredit, FinancialAccount, FiscalConfig, FiscalSeries,
    Notification, Payment, Sale, SaleReturn,
)
from starrp.services import cash, ledger, returns
from starrp.services.provisioning import create_store
from starrp.views.operations import SaleReturnViewSet

APPROVAL = {"username": "ger", "password": "senha123"}


def _sale(ctx, api, variant, qty="1", **item):
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    r = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk), "quantity": qty, **item}, format="json")
    assert r.status_code == 201, r.json()
    return sale["id"]


def _pay(ctx, api, sid, amount, kind="pix"):
    row = {"method": str(ctx.methods[kind].pk), "amount": str(amount)}
    if kind == "cash":
        row["tendered"] = str(amount)
    return api.post(f"/api/v1/sales/{sid}/checkout/", {"payments": [row]}, format="json")


def _off(ctx, variant, price="100.00", **extra):
    return {"offline_id": str(uuid.uuid4()), "installation_id": "pc-1", "local_number": 1,
            "items": [{"id": "a", "variant": str(variant.pk), "quantity": "1", "unit_price": price, "discount": "0"}],
            "payments": [{"method": str(ctx.methods["cash"].pk), "amount": price, "tendered": price}], **extra}


def _boot(api):
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")


def test_t01_park_offline_resume_conclui_sem_autorizacao(ctx):
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    seller, cashier = ctx.user("vend", "seller", is_seller=True), ctx.user("caixa", "cashier")
    body = _off(ctx, v, "1.00", park=True)
    body.pop("payments")
    r = ctx.client(seller).post("/api/v1/pdv/offline-sales/", body, format="json")
    assert r.status_code == 201, r.json()
    sid = r.json()["id"]
    api = ctx.client(cashier)
    assert api.post(f"/api/v1/sales/{sid}/resume/", {}, format="json").status_code == 200
    r = _pay(ctx, api, sid, "1.00", "cash")
    s = Sale.all_objects.get(pk=sid)
    assert not (s.status == "completed" and not s.metafields.get("_approval_unverified"))


def test_t01b_controle_mesmo_preco_online_exige_gerente(ctx):
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    api = ctx.client(ctx.user("caixa", "cashier"))
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    r = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(v.pk), "unit_price": "1.00"}, format="json")
    assert r.status_code == 403


def test_t02_venda_offline_em_turno_ja_fechado_sem_aviso(ctx):
    ctx.require_cash()
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    cashier = ctx.user("caixa", "cashier")
    ctx.user("ger", "manager")
    ctx.link(cashier)
    api = ctx.client(cashier)
    _boot(api)
    session = cash.open_session(ctx.register, cashier, Decimal("0"))
    cash.close_session(session, cashier, Decimal("0"))
    r = api.post("/api/v1/pdv/offline-sales/", _off(ctx, v, "1000.00", cash_session=str(session.pk)), format="json")
    session.refresh_from_db()
    assert r.status_code >= 400 or Notification.all_objects.exists() or CashDiscrepancy.all_objects.exists()


def test_t03_venda_offline_na_gaveta_de_outro_operador(ctx):
    ctx.require_cash()
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    a, b = ctx.user("caixaa", "cashier"), ctx.user("caixab", "cashier")
    ctx.user("ger", "manager")
    ctx.link(b)
    _boot(ctx.client(a))
    sb = cash.open_session(ctx.register, b, Decimal("0"))
    ctx.client(a).post("/api/v1/pdv/offline-sales/", _off(ctx, v, "1000.00", cash_session=str(sb.pk)), format="json")
    assert cash.expected_cash(sb) == 0 or Notification.all_objects.exists()


def test_t04_caixa_b_cobra_venda_de_a_na_gaveta_de_a(ctx):
    ctx.require_cash()
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    a, b = ctx.user("caixaa", "cashier"), ctx.user("caixab", "cashier")
    ctx.link(a)
    sa = cash.open_session(ctx.register, a, Decimal("0"))
    sid = _sale(ctx, ctx.client(a), v)
    _pay(ctx, ctx.client(b), sid, "1000.00", "cash")
    assert cash.expected_cash(sa) == 0


def test_t05_cancelar_devolucao_correndo_com_a_conclusao(ctx, monkeypatch):
    v = ctx.product(name="TV", price="100.00", track_stock=False)
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    api = ctx.client()
    sid = _sale(ctx, api, v)
    api.post(f"/api/v1/sales/{sid}/customer/", {"customer": str(c.pk)}, format="json")
    assert _pay(ctx, api, sid, "100.00").status_code == 200
    item = Sale.all_objects.get(pk=sid).items.first()
    body = {"items": [{"sale_item": str(item.pk), "quantity": "1"}], "refund_method": "store_credit", "reason": "x"}
    rid = api.post(f"/api/v1/sales/{sid}/returns/", body, format="json").json()["id"]
    stale = SaleReturn.all_objects.get(pk=rid)  # o cancelamento leu o rascunho...
    real = SaleReturnViewSet.get_object

    def racing(self):
        if self.action == "cancel":
            returns.complete(SaleReturn.all_objects.get(pk=rid), ctx.admin)  # ...e a conclusao gravou no meio
            return stale
        return real(self)

    monkeypatch.setattr(SaleReturnViewSet, "get_object", racing)
    api.post(f"/api/v1/returns/{rid}/cancel/", {}, format="json")
    monkeypatch.setattr(SaleReturnViewSet, "get_object", real)
    again = api.post(f"/api/v1/sales/{sid}/returns/", body, format="json")
    if again.status_code == 201:
        api.post(f"/api/v1/returns/{again.json()['id']}/complete/", {}, format="json")
    total = sum(x.amount for x in CustomerCredit.all_objects.filter(customer=c, deleted_at__isnull=True))
    assert total <= 100


def test_t10_conta_da_rede_por_gerente_de_filial(ctx):
    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    create_store(ctx.account, name="B")
    bank = FinancialAccount.all_objects.get(account=ctx.account, store=None, kind="bank")
    vault = FinancialAccount.all_objects.filter(account=ctx.account, store=ctx.store, kind="cash").first()
    api = ctx.client(ctx.user("ger", "manager"))
    r = api.post("/api/v1/finance/accounts/transfer/", {"source": str(bank.pk), "target": str(vault.pk),
                 "amount": "50000", "description": "x"}, format="json")
    tx = ledger.post(bank, "in", 777, description="deposito da rede")
    r2 = api.post(f"/api/v1/finance/transactions/{tx.pk}/reverse/", {}, format="json")
    assert r.status_code == 403 and r2.status_code == 403


def test_t14_troca_de_pagamento_depois_da_devolucao(ctx):
    v = ctx.product(name="TV", price="100.00", track_stock=False)
    c = Customer.all_objects.create(account=ctx.account, name="Ze")
    CustomerCredit.all_objects.create(account=ctx.account, customer=c, kind="adjustment", amount=100)
    mgr = ctx.user("ger", "manager")
    api = ctx.client(mgr)
    cash.open_session(ctx.register, mgr, Decimal("500"))
    sid = _sale(ctx, api, v)
    api.post(f"/api/v1/sales/{sid}/customer/", {"customer": str(c.pk)}, format="json")
    assert _pay(ctx, api, sid, "100.00").status_code == 200
    s = Sale.all_objects.get(pk=sid)
    rid = api.post(f"/api/v1/sales/{sid}/returns/", {"items": [{"sale_item": str(s.items.first().pk), "quantity": "1"}],
                   "refund_method": "cash", "reason": "x"}, format="json").json()["id"]
    r = api.post(f"/api/v1/returns/{rid}/complete/", {}, format="json")
    assert r.status_code == 200, r.json()
    p = Payment.all_objects.get(sale=s)
    r = api.post(f"/api/v1/sales/{sid}/payments/{p.pk}/change/", {"method": str(ctx.methods["store_credit"].pk),
                 "reason": "erro"}, format="json")
    assert r.status_code >= 400


def test_t15_desconto_autorizado_em_valor_sobe_ao_reduzir_quantidade(ctx):
    v = ctx.product(name="Caro", price="1000.00", track_stock=False)
    cashier = ctx.user("caixa", "cashier")  # 5%
    ctx.user("ger", "manager")  # 30%
    api = ctx.client(cashier)
    sid = _sale(ctx, api, v, qty="10")
    r = api.post(f"/api/v1/sales/{sid}/discount/", {"amount": "1000.00", "approval": APPROVAL}, format="json")  # 10%
    assert r.status_code == 200, r.json()
    item = Sale.all_objects.get(pk=sid).items.first()
    api.patch(f"/api/v1/sales/{sid}/items/{item.pk}/", {"quantity": "3.334"}, format="json")
    s = Sale.all_objects.get(pk=sid)
    r = _pay(ctx, api, sid, s.total)
    s.refresh_from_db()
    assert s.status != "completed"


def test_t16_desconto_do_item_mais_o_da_venda(ctx):
    v = ctx.product(name="Caro", price="1000.00", track_stock=False)
    api = ctx.client(ctx.user("caixa", "cashier"))  # 5%
    sid = _sale(ctx, api, v, discount="50.00")
    api.post(f"/api/v1/sales/{sid}/discount/", {"percent": "5"}, format="json")
    s = Sale.all_objects.get(pk=sid)
    _pay(ctx, api, sid, s.total)
    s.refresh_from_db()
    assert not (s.status == "completed" and s.total < 950)


def test_t21_vendedor_queima_a_numeracao_fiscal(ctx):
    cfg = FiscalConfig.all_objects.create(account=ctx.account, name="B", legal_name="B", cnpj="11222333000181")
    ctx.store.fiscal_config = cfg
    ctx.store.save(update_fields=["fiscal_config"])
    other = FiscalSeries.all_objects.create(account=ctx.account, config=cfg, series=7, document_model="65")
    v = ctx.product(name="TV", price="10.00", track_stock=False)
    api = ctx.client(ctx.user("vend", "seller", is_seller=True))
    body = _off(ctx, v, "10.00", park=True)
    body.pop("payments")
    body["invoice"] = {"document_model": "65", "series": 7, "number": 999999999, "result": {"erro": "x"}}
    api.post("/api/v1/pdv/offline-sales/", body, format="json")
    other.refresh_from_db()
    assert other.next_number < 100


def test_t27_abre_turno_em_nome_do_colega(ctx):
    a, b = ctx.user("caixaa", "cashier"), ctx.user("caixab", "cashier")
    ctx.link(b)
    api = ctx.client(a)
    _boot(api)
    r = api.post("/api/v1/pdv/offline-cash/", {"event": "open", "offline_id": "z", "register": str(ctx.register.pk),
                 "opening_amount": "999", "operator": b.pk}, format="json")
    assert r.status_code >= 400 and not CashSession.all_objects.filter(register=ctx.register).exists()


def test_t28_comprovante_de_sangria_nao_tem_valor(ctx):
    cashier, manager = ctx.user("caixa", "cashier"), ctx.user("ger", "manager")
    ctx.link(cashier)
    api = ctx.client(cashier)
    _boot(api)
    s = cash.open_session(ctx.register, cashier, Decimal("10000"))
    proof = api.post("/api/v1/pdv/authorize/", {"code": "cash.approve", "approval": APPROVAL}, format="json").json()["proof"]
    api.post("/api/v1/pdv/offline-cash/", {"event": "movement", "offline_id": "m1", "session": str(s.pk),
                 "kind": "withdrawal", "amount": "9500", "approved_by": manager.pk, "approval_proofs": [proof]}, format="json")
    m = CashMovement.all_objects.get(session=s)
    assert m.status == "pending"


def test_t28b_comprovante_de_preco_serve_para_qualquer_item(ctx):
    v = ctx.product(name="TV", price="1000.00", track_stock=False)
    cashier, manager = ctx.user("caixa", "cashier"), ctx.user("ger", "manager")
    api = ctx.client(cashier)
    _boot(api)
    proof = api.post("/api/v1/pdv/authorize/", {"code": "sales.price_override", "approval": APPROVAL}, format="json").json()["proof"]
    body = _off(ctx, v, "700.00", approval_proofs=[proof])
    body["items"][0]["approved_by"] = manager.pk
    r = api.post("/api/v1/pdv/offline-sales/", body, format="json")
    s = Sale.all_objects.get(pk=r.json()["id"])
    assert s.metafields.get("_approval_unverified")
