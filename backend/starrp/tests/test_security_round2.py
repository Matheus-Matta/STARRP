"""Rodada 2 da auditoria (docs/SEGURANCA.md): dinheiro, estoque e disponibilidade."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from xml.etree.ElementTree import fromstring

import pytest
from django.utils import timezone

from starrp.core.errors import ApprovalRequired, BusinessError, StateConflict
from starrp.models import (
    CashSession, Commission, Coupon, Customer, FinancialAccount, FinancialTitle, FinancialTransaction, RecurringTitle,
    Sale, SaleItem, StockMovement,
)
from starrp.services import checkout, finance, ledger, media, nfe_xml, recurring, returns, sales, stock


def _open_sale(ctx, *lines, user=None, customer=None):
    sale = sales.create(ctx.store, user or ctx.admin, customer=customer)
    for variant, quantity in lines:
        sales.add_item(sale, variant, Decimal(quantity), user or ctx.admin)
    sale.refresh_from_db()
    return sale


def _paid(ctx, sale, kind="pix"):
    sale.refresh_from_db()
    checkout.add_payment(sale, ctx.methods[kind], sale.total, ctx.admin, nsu="123")
    sale.refresh_from_db()
    checkout.complete(sale, ctx.admin)
    sale.refresh_from_db()
    return sale


# ── devolução (R2-02, R2-13) e arredondamento ───────────────────────────────
def test_mesmo_item_em_duas_linhas_nao_devolve_em_dobro(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana")
    sale = _paid(ctx, _open_sale(ctx, (ctx.product(track_stock=False), "1"), customer=customer))
    row = {"sale_item": sale.items.get(), "quantity": Decimal("1")}
    with pytest.raises(BusinessError):
        returns.create(sale, ctx.admin, [row, dict(row)], reason="defeito")


def test_troca_exige_cliente_identificado(ctx):
    sale = _paid(ctx, _open_sale(ctx, (ctx.product(track_stock=False), "1")))
    with pytest.raises(BusinessError, match="cliente"):
        returns.create(sale, ctx.admin, [{"sale_item": sale.items.get(), "quantity": Decimal("1")}], reason="troca",
                       refund_method="exchange")


def test_devolucao_em_partes_soma_exatamente_o_que_foi_pago(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana")
    sale = _paid(ctx, _open_sale(ctx, (ctx.product(price="10.00", track_stock=False), "3"), customer=customer))
    SaleItem.all_objects.filter(sale=sale).update(total=Decimal("10.00"))
    Sale.all_objects.filter(pk=sale.pk).update(subtotal=Decimal("10.00"), total=Decimal("10.00"))
    totals = []
    for _ in range(3):
        sale = Sale.all_objects.get(pk=sale.pk)
        done = returns.create(sale, ctx.admin, [{"sale_item": sale.items.get(), "quantity": Decimal("1")}],
                              reason="defeito")
        returns.complete(done, ctx.admin)
        totals.append(done.total)
    assert sum(totals) == Decimal("10.00")


def test_cupom_de_frete_nao_reduz_o_valor_do_produto(ctx):
    sale = _open_sale(ctx, (ctx.product(price="100.00", track_stock=False), "1"))
    coupon = Coupon(code="FRETE", kind=Coupon.Kind.FREE_SHIPPING)
    coupon.pk = sale.pk  # em memória basta para a conta
    sale.coupon, sale.coupon_discount = coupon, Decimal("20")
    assert sales.header_discount(sale) == 0


# ── desconto (R2-05) e conclusão (R2-06) ────────────────────────────────────
def test_desconto_do_item_nao_sobrevive_a_queda_da_quantidade(ctx):
    cashier = ctx.user("caixa1", "cashier")
    sale = _open_sale(ctx, (ctx.product(price="10.00", track_stock=False), "100"), user=cashier)
    SaleItem.all_objects.filter(sale=sale).update(discount=Decimal("10"))  # 1%
    with pytest.raises(ApprovalRequired):
        sales.update_item(sale.items.get(), cashier, quantity=Decimal("2"))  # viraria 50%


def test_conclusao_reconfere_o_desconto_da_venda(ctx):
    cashier = ctx.user("caixa1", "cashier")
    sale = _open_sale(ctx, (ctx.product(price="100.00", track_stock=False), "1"), user=cashier)
    sale.discount = Decimal("60")
    with pytest.raises(ApprovalRequired):
        sales.check_discounts(sale, cashier, list(sale.items.all()))
    sale.discount_approved_by = ctx.admin  # quem autorizou tem limite: passa
    sales.check_discounts(sale, cashier, list(sale.items.all()))


def test_metadado_interno_do_item_nao_vem_do_cliente(ctx):
    sale = _open_sale(ctx)
    sales.add_item(sale, ctx.product(track_stock=False), Decimal("1"), ctx.admin,
                   metafields={"_discount_by": ctx.admin.pk, "cor": "azul"})
    saved = sale.items.get().metafields
    assert "_discount_by" not in saved and saved["cor"] == "azul"


def test_venda_paga_a_mais_nao_conclui(ctx):
    sale = _open_sale(ctx, (ctx.product(price="50.00", track_stock=False), "1"))
    checkout.add_payment(sale, ctx.methods["pix"], sale.total, ctx.admin, nsu="1")
    sale.payments.update(amount=Decimal("80"))
    Sale.all_objects.filter(pk=sale.pk).update(paid_amount=Decimal("80"))
    sale.refresh_from_db()
    with pytest.raises(StateConflict):
        checkout.complete(sale, ctx.admin)


def test_duas_vendas_no_crediario_nao_passam_do_limite(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana", credit_limit=Decimal("100"))
    pair = [_open_sale(ctx, (ctx.product(name, "80.00", track_stock=False), "1"), customer=customer)
            for name in ("Bolsa", "Cinto")]
    for sale in pair:
        checkout.add_payment(sale, ctx.methods["installment_plan"], sale.total, ctx.admin)
        sale.refresh_from_db()
    checkout.complete(pair[0], ctx.admin)
    with pytest.raises(BusinessError, match="Limite"):
        checkout.complete(pair[1], ctx.admin)


def test_caixa_nao_muda_limite_de_crediario(ctx):
    cashier = ctx.user("caixa1", "cashier")
    customer = Customer.all_objects.create(account=ctx.account, name="Ana")
    url = f"/api/v1/customers/{customer.pk}/"
    response = ctx.client(cashier).patch(url, {"credit_limit": "9999.00"}, format="json")
    customer.refresh_from_db()
    assert response.status_code in (400, 403, 422) and customer.credit_limit == 0


def test_troca_de_cliente_com_crediario_lancado(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana", credit_limit=Decimal("100"))
    stranger = Customer.all_objects.create(account=ctx.account, name="Bia")
    sale = _open_sale(ctx, (ctx.product(price="50.00", track_stock=False), "1"), customer=customer)
    checkout.add_payment(sale, ctx.methods["installment_plan"], sale.total, ctx.admin)
    response = ctx.client().post(f"/api/v1/sales/{sale.pk}/customer/", {"customer": str(stranger.pk)}, format="json")
    assert response.status_code == 409, response.json()


# ── comissão (R2-14), razão (R2-19) e títulos (R2-20) ───────────────────────
def _paid_commission(ctx, sale):
    sale.commissions.all().delete()
    return Commission.all_objects.create(
        account=ctx.account, store=ctx.store, seller=ctx.admin, sale=sale, sale_item=sale.items.get(),
        base_amount=Decimal("50"), rate=Decimal("5"), amount=Decimal("2.5"), status=Commission.Status.PAID)


def test_comissao_paga_nao_volta_para_pendente_pela_api(ctx):
    row = _paid_commission(ctx, _paid(ctx, _open_sale(ctx, (ctx.product(track_stock=False), "1"))))
    ctx.client().patch(f"/api/v1/commissions/{row.pk}/", {"status": "pending"}, format="json")
    row.refresh_from_db()
    assert row.status == Commission.Status.PAID


def test_cancelar_venda_com_comissao_paga_gera_estorno(ctx):
    sale = _paid(ctx, _open_sale(ctx, (ctx.product(track_stock=False), "1")))
    _paid_commission(ctx, sale)
    checkout.cancel(sale, ctx.admin, "erro no pedido")
    amounts = sorted(sale.commissions.exclude(status="cancelled").values_list("amount", flat=True))
    assert amounts == [Decimal("-2.50"), Decimal("2.50")]


def test_estorno_de_transferencia_volta_as_duas_pernas(ctx):
    a = FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="A")
    b = FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="B")
    ledger.transfer(a, b, Decimal("40"), description="sobra", user=ctx.admin)
    ledger.reverse(FinancialTransaction.all_objects.get(financial_account=a), user=ctx.admin)
    for account in (a, b):
        rows = FinancialTransaction.all_objects.filter(financial_account=account)
        assert rows.count() == 2 and rows.filter(reversal_of__isnull=False).count() == 1


def test_parcela_nunca_negativa():
    parts = finance.split(Decimal("0.15"), 10)
    assert sum(parts) == Decimal("0.15") and all(p >= 0 for p in parts)


def test_titulo_lancado_nao_muda_de_valor(ctx):
    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    title = finance.create_title(store=ctx.store, kind="payable", total=Decimal("100"), user=ctx.admin,
                                 first_due=timezone.localdate(), description="Luz")
    response = ctx.client().patch(f"/api/v1/finance/titles/{title.pk}/", {"total": "1.00"}, format="json")
    assert response.status_code in (400, 422), response.json()
    assert FinancialTitle.all_objects.get(pk=title.pk).total == Decimal("100.00")


# ── estoque (R2-03) ─────────────────────────────────────────────────────────
def test_estoque_recusa_produto_de_outra_conta_e_custo_negativo(ctx, other):
    warehouse = stock.default_warehouse(ctx.store)
    with pytest.raises(BusinessError):
        stock.move(other.product(), warehouse, Decimal("1"), StockMovement.Kind.PURCHASE)
    with pytest.raises(BusinessError):
        stock.move(ctx.product(), warehouse, Decimal("1"), StockMovement.Kind.PURCHASE, unit_cost=Decimal("-5"))


def test_documento_de_estoque_recusa_produto_de_outra_conta(ctx, other):
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    api, warehouse = ctx.client(), stock.default_warehouse(ctx.store)
    body = {"kind": "entry", "warehouse": str(warehouse.pk), "effective_date": str(timezone.localdate())}
    foreign = api.post("/api/v1/stock/documents/", {**body, "items": [
        {"variant": str(other.product().pk), "quantity": "1", "unit_cost": "1"}]}, format="json")
    own = api.post("/api/v1/stock/documents/", {**body, "items": [
        {"variant": str(ctx.product().pk), "quantity": "1", "unit_cost": "1"}]}, format="json")
    assert own.status_code == 201, own.json()
    assert foreign.status_code in (400, 422), foreign.json()


# ── disponibilidade (R2-08, R2-15, R2-17) e arquivos (R2-16, R2-21) ─────────
def test_recorrencia_com_defeito_nao_para_as_outras(ctx, monkeypatch):
    for name in ("Ruim", "Boa"):
        RecurringTitle.all_objects.create(account=ctx.account, store=ctx.store, kind="payable", description=name,
                                          amount=Decimal("10"), start_date=timezone.localdate())
    real = recurring.generate_one

    def flaky(rec, today=None, user=None):
        if rec.description == "Ruim":
            raise RuntimeError("defeito")
        return real(rec, today, user)

    monkeypatch.setattr(recurring, "generate_one", flaky)
    assert recurring.generate_all(ctx.account) >= 1


def test_imagem_com_pixels_demais_e_recusada_sem_descomprimir():
    from PIL import Image

    buffer = BytesIO()
    Image.new("1", (8000, 8000)).save(buffer, "PNG")  # 64 MP em poucos KB
    with pytest.raises(BusinessError):
        media._open(buffer.getvalue(), "inválida")


def test_planilha_que_descompacta_demais_e_recusada(monkeypatch):
    import zipfile

    from starrp.services.cosmos import attachments

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as book:
        book.writestr("xl/worksheets/sheet1.xml", b"0" * (2 * 1024 * 1024))
    monkeypatch.setattr(attachments, "MAX_UNZIPPED", 1024 * 1024)
    with pytest.raises(attachments.AttachmentError):
        attachments.check_zip(buffer.getvalue())


def test_grafico_diario_de_seculos_e_recusado():
    from starrp.services import report_book

    with pytest.raises(BusinessError):
        report_book._buckets({"date_from": "1000-01-01", "date_to": "2900-01-01"})


def test_nfe_com_valor_negativo_e_recusada():
    node = fromstring('<n xmlns="http://www.portalfiscal.inf.br/nfe"><v>-1</v><x>NaN</x></n>')
    for path in ("n:v", "n:x"):
        with pytest.raises(BusinessError):
            nfe_xml._dec(node, path)


# ── caixa offline (R2-11, R2-12) e ocorrências (R2-27) ──────────────────────
def _open_offline(ctx, api, opened_at, offline_id="t1"):
    return api.post("/api/v1/pdv/offline-cash/", {
        "event": "open", "offline_id": offline_id, "register": str(ctx.register.pk), "opening_amount": "0.00",
        "installation_id": "pc-1", "opened_at": opened_at.isoformat()}, format="json")


def test_abertura_offline_muito_antiga_vale_agora(ctx):
    ctx.require_cash()
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    response = _open_offline(ctx, api, timezone.now() - timedelta(days=90))
    assert response.status_code == 201, response.json()
    assert CashSession.all_objects.get(offline_id="t1").opened_at > timezone.now() - timedelta(hours=1)


def test_caixa_nao_fecha_o_turno_offline_de_outro(ctx):
    ctx.require_cash()
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    assert _open_offline(ctx, api, timezone.now()).status_code == 201
    stranger = ctx.user("caixa2", "cashier")
    response = ctx.client(stranger).post("/api/v1/pdv/offline-cash/", {
        "event": "close", "offline_id": "c9", "session": "off:t1", "counted_amount": "0.00",
        "installation_id": "pc-1"}, format="json")
    assert response.status_code in (403, 409, 422), response.json()
    assert CashSession.all_objects.get(offline_id="t1").closed_at is None


def test_ocorrencia_de_caixa_nao_se_cria_nem_apaga(ctx):
    from starrp.views.operations import CashDiscrepancyViewSet

    assert "delete" not in CashDiscrepancyViewSet.http_method_names
    assert "patch" not in CashDiscrepancyViewSet.http_method_names


# ── redefinição de senha (R2-28) ────────────────────────────────────────────
def test_redefinir_senha_invalida_os_outros_links(ctx):
    from starrp.models import PasswordResetRequest
    from starrp.services.password_reset import token_hash as _token_hash

    for token in ("um", "dois"):
        PasswordResetRequest.objects.create(user=ctx.admin, token_hash=_token_hash(token),
                                            expires_at=timezone.now() + timedelta(hours=1))
    from rest_framework.test import APIClient

    first = APIClient().post("/api/v1/auth/password-reset/confirm/", {"token": "um", "password": "OutraSenha!2026"},
                             format="json")
    second = APIClient().post("/api/v1/auth/password-reset/confirm/", {"token": "dois", "password": "MaisUma!2026"},
                              format="json")
    assert first.status_code == 200, first.json()
    assert second.status_code in (400, 422)
