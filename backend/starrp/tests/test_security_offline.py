"""Venda montada no PDV desktop não confia no "aprovado por" do cliente (docs/SEGURANCA.md S-06)."""
import uuid
from datetime import timedelta

from django.utils import timezone

from starrp.models import Notification, Sale
from starrp.tests.conftest import Ctx


def _body(ctx, variant, **extra):
    return {"offline_id": str(uuid.uuid4()), "installation_id": "pc-1", "local_number": 1,
            "items": [{"id": "a", "variant": str(variant.pk), "quantity": "1", "unit_price": "100.00", "discount": "0"}],
            "payments": [{"method": str(ctx.methods["cash"].pk), "amount": "50.00", "tendered": "50.00"}], **extra}


def _setup(ctx):
    variant = ctx.product(name="Cadeira", price="100.00", track_stock=False)
    cashier = ctx.user("caixa", "cashier")  # limite de 5%
    manager = ctx.user("gerente", "manager")  # limite de 30%
    api = ctx.client(cashier)
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    return variant, cashier, manager, api


def test_desconto_com_gerente_sem_comprovante_entra_marcado_e_avisa(ctx):
    variant, cashier, manager, api = _setup(ctx)

    response = api.post("/api/v1/pdv/offline-sales/",
                        _body(ctx, variant, discount="50.00", discount_approved_by=manager.pk), format="json")

    assert response.status_code == 201, response.json()
    sale = Sale.all_objects.get(pk=response.json()["id"])
    assert sale.status == Sale.Status.COMPLETED  # a venda é um fato: entra
    assert sale.metafields.get("_approval_unverified"), sale.metafields  # mas fica marcada
    assert Notification.all_objects.filter(account=ctx.account, object_id=str(sale.pk)).exists()


def test_desconto_com_comprovante_do_servidor_entra_limpo(ctx):
    variant, cashier, manager, api = _setup(ctx)
    auth = api.post("/api/v1/pdv/authorize/", {"code": "sales.discount", "percent": "20",
                                                "approval": {"username": "gerente", "password": "senha123"}},
                    format="json")
    assert auth.status_code == 200, auth.json()

    response = api.post("/api/v1/pdv/offline-sales/",
                        _body(ctx, variant, discount="20.00", discount_approved_by=manager.pk,
                              payments=[{"method": str(ctx.methods["cash"].pk), "amount": "80.00", "tendered": "80.00"}],
                              approval_proofs=[auth.json()["proof"]]), format="json")

    assert response.status_code == 201, response.json()
    assert not Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")


def test_comprovante_forjado_ou_de_outro_operador_nao_vale(ctx):
    variant, cashier, manager, api = _setup(ctx)
    other_cashier = ctx.user("caixa2", "cashier")
    auth = ctx.client(other_cashier).post("/api/v1/pdv/authorize/", {
        "code": "sales.discount", "percent": "20", "approval": {"username": "gerente", "password": "senha123"}},
        format="json")
    proofs = [auth.json()["proof"], auth.json()["proof"][:-3] + "abc"]

    response = api.post("/api/v1/pdv/offline-sales/",
                        _body(ctx, variant, discount="20.00", discount_approved_by=manager.pk,
                              payments=[{"method": str(ctx.methods["cash"].pk), "amount": "80.00", "tendered": "80.00"}],
                              approval_proofs=proofs), format="json")

    assert response.status_code == 201
    assert Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")


def test_autorizador_ou_vendedor_de_outra_conta_e_recusado(ctx):
    variant, cashier, manager, api = _setup(ctx)
    outsider = Ctx("Outra Loja").user("gerente_b", "manager")

    approver = api.post("/api/v1/pdv/offline-sales/",
                        _body(ctx, variant, discount="50.00", discount_approved_by=outsider.pk), format="json")
    seller = api.post("/api/v1/pdv/offline-sales/", _body(ctx, variant, seller=outsider.pk), format="json")

    assert approver.status_code == 422 and approver.json()["error"]["code"] == "offline_user_unknown"
    assert seller.status_code == 422 and seller.json()["error"]["code"] == "offline_user_unknown"


def test_preco_abaixo_do_limite_do_operador_sem_autorizador_fica_marcado(ctx):
    variant, cashier, manager, api = _setup(ctx)
    body = _body(ctx, variant)
    body["items"][0]["unit_price"] = "0.01"
    body["payments"][0].update(amount="0.01", tendered="0.01")

    response = api.post("/api/v1/pdv/offline-sales/", body, format="json")

    assert response.status_code == 201, response.json()
    assert Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")


def test_hora_da_venda_no_futuro_nao_vale(ctx):
    variant, cashier, manager, api = _setup(ctx)
    future = (timezone.now() + timedelta(days=10)).isoformat()
    body = _body(ctx, variant, completed_at=future)
    body["items"][0]["unit_price"] = "50.00"

    response = api.post("/api/v1/pdv/offline-sales/", body, format="json")

    sale = Sale.all_objects.get(pk=response.json()["id"])
    assert sale.completed_at <= timezone.now()
    assert sale.metafields.get("_approval_unverified")


def test_comprovante_de_desconto_pequeno_nao_cobre_desconto_maior(ctx):
    """Rodada 1 (S-06): o comprovante vale até o percentual autorizado, não até o limite do gerente."""
    variant, cashier, manager, api = _setup(ctx)
    small = api.post("/api/v1/pdv/authorize/", {"code": "sales.discount", "percent": "10",
                                                 "approval": {"username": "gerente", "password": "senha123"}},
                     format="json").json()["proof"]

    response = api.post("/api/v1/pdv/offline-sales/",
                        _body(ctx, variant, discount="25.00", discount_approved_by=manager.pk,
                              payments=[{"method": str(ctx.methods["cash"].pk), "amount": "75.00", "tendered": "75.00"}],
                              approval_proofs=[small]), format="json")

    assert response.status_code == 201, response.json()
    assert Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")


# ── Rodada 1 de verificação (P-3, P-4, P-5 e o alerta falso em promoção) ─────────────────────────────────

def _open_offline(ctx, api, offline_id="t1"):
    response = api.post("/api/v1/pdv/offline-cash/", {
        "event": "open", "offline_id": offline_id, "register": str(ctx.register.pk), "opening_amount": "100.00",
        "installation_id": "pc-1"}, format="json")
    assert response.status_code == 201, response.json()


def _withdrawal(api, offline_id, **extra):
    return api.post("/api/v1/pdv/offline-cash/", {"event": "movement", "offline_id": offline_id, "session": "off:t1",
                                                  "kind": "withdrawal", "amount": "90.00", "reason": "Cofre", **extra},
                    format="json")


def test_sangria_offline_sem_comprovante_nao_e_aprovada_e_de_outra_conta_e_recusada(ctx):
    from starrp.models import CashMovement

    variant, cashier, manager, api = _setup(ctx)
    ctx.link(cashier)
    _open_offline(ctx, api)
    outsider = Ctx("Outra Loja").user("admin_b", "manager")

    by_password = _withdrawal(api, "m1", by_password=True)
    foreign = _withdrawal(api, "m2", approved_by=outsider.pk)
    claimed = _withdrawal(api, "m3", approved_by=manager.pk)
    assert claimed.status_code == 201

    assert by_password.status_code == 201
    assert CashMovement.all_objects.get(offline_id="m1").status == CashMovement.Status.PENDING
    assert foreign.status_code == 422 and foreign.json()["error"]["code"] == "offline_user_unknown"
    assert CashMovement.all_objects.get(offline_id="m3").status == CashMovement.Status.PENDING
    assert Notification.all_objects.filter(account=ctx.account, category="cash").exists()


def test_sangria_offline_com_comprovante_e_aprovada_uma_vez_so(ctx):
    from starrp.models import CashMovement

    variant, cashier, manager, api = _setup(ctx)
    ctx.link(cashier)
    _open_offline(ctx, api)
    proof = api.post("/api/v1/pdv/authorize/", {"code": "cash.approve",
                                                 "approval": {"username": "gerente", "password": "senha123"}},
                     format="json").json()["proof"]

    _withdrawal(api, "m1", approved_by=manager.pk, approval_proofs=[proof])
    _withdrawal(api, "m2", approved_by=manager.pk, approval_proofs=[proof])  # mesmo comprovante de novo

    assert CashMovement.all_objects.get(offline_id="m1").status == CashMovement.Status.APPROVED
    assert CashMovement.all_objects.get(offline_id="m2").status == CashMovement.Status.PENDING


def test_operador_informado_nao_empresta_o_limite_dele(ctx):
    variant, cashier, manager, api = _setup(ctx)
    response = api.post("/api/v1/pdv/offline-sales/", _body(ctx, variant, operator=manager.pk, discount="25.00",
                        payments=[{"method": str(ctx.methods["cash"].pk), "amount": "75.00", "tendered": "75.00"}]),
                        format="json")
    assert response.status_code == 201, response.json()
    assert Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")


def test_comprovante_serve_uma_venda_so(ctx):
    variant, cashier, manager, api = _setup(ctx)
    proof = api.post("/api/v1/pdv/authorize/", {"code": "sales.discount", "percent": "20",
                                                 "approval": {"username": "gerente", "password": "senha123"}},
                     format="json").json()["proof"]
    flags = []
    for _ in range(2):
        response = api.post("/api/v1/pdv/offline-sales/", _body(
            ctx, variant, discount="20.00", discount_approved_by=manager.pk, approval_proofs=[proof],
            payments=[{"method": str(ctx.methods["cash"].pk), "amount": "80.00", "tendered": "80.00"}]), format="json")
        flags.append(bool(Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")))
    assert flags == [False, True]


def test_preco_promocional_do_servidor_nao_gera_alerta(ctx, monkeypatch):
    from decimal import Decimal

    from starrp.services import sales

    variant, cashier, manager, api = _setup(ctx)
    real_add = sales.add_item

    def promo(*args, **kwargs):  # a promoção do servidor deixa o item por R$ 60
        item = real_add(*args, **kwargs)
        item.unit_price = Decimal("60.00")
        item.save(update_fields=["unit_price"])
        return item

    monkeypatch.setattr(sales, "add_item", promo)
    body = _body(ctx, variant)
    body["items"][0]["unit_price"] = "60.00"
    body["payments"][0].update(amount="60.00", tendered="60.00")

    response = api.post("/api/v1/pdv/offline-sales/", body, format="json")

    assert response.status_code == 201, response.json()
    assert not Sale.all_objects.get(pk=response.json()["id"]).metafields.get("_approval_unverified")
