"""Entrada no sistema: login, /me, bootstrap do PDV e permissões por cargo."""
from rest_framework.test import APIClient


def test_login_me_e_bootstrap_do_pdv(ctx):
    """O PDV loga, descobre quem é e registra o terminal numa chamada só."""
    client = APIClient()
    login = client.post("/api/v1/auth/login/", {"username": ctx.admin.username, "password": "senha123"},
                        format="json")
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}", HTTP_X_STORE_ID=str(ctx.store.pk))

    me = client.get("/api/v1/me/").json()
    boot = client.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-01", "name": "Caixa 1"}, format="json")

    assert me["role"]["code"] == "admin" and "*" in me["permissions"]
    assert boot.status_code == 200, boot.json()
    assert boot.json()["terminal"]["installation_id"] == "pc-01"
    assert {m["kind"] for m in boot.json()["payment_methods"]} >= {"cash", "pix", "credit_card"}


def test_vendedor_nao_cadastra_produto_nem_cancela_venda(ctx):
    """Cargo sem `catalog.manage` recebe 403 no cadastro; cancelar exige `sales.cancel` ou autorização."""
    seller = ctx.user("vend", "seller", is_seller=True)
    api = ctx.client(seller)

    create = api.post("/api/v1/catalog/products/", {"name": "X", "variants": [{"sku": "X1", "price": "1.00"}]}, format="json")
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    cancel = api.post(f"/api/v1/sales/{sale['id']}/cancel/", {"reason": "teste"}, format="json")

    assert create.status_code == 403
    assert cancel.status_code == 403
    assert cancel.json()["error"]["code"] == "approval_required"


def test_sem_token_recebe_401_no_envelope(db):
    """Erro sai sempre no mesmo envelope, inclusive o 401."""
    response = APIClient().get("/api/v1/sales/")

    assert response.status_code == 401
    assert response.json()["success"] is False


def test_admin_de_conta_com_uma_loja_ja_entra_com_ela_ativa(ctx):
    """Sem header e sem loja padrão: com uma loja visível só, ela é a ativa (o PDV não pede para escolher)."""
    me = ctx.client(store=None).get("/api/v1/me/").json()

    assert me["active_store_id"] == str(ctx.store.pk)
