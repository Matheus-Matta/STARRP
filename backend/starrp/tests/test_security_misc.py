"""Achados de baixa severidade (docs/SEGURANCA.md S-18, S-19, S-21)."""
import pytest
from rest_framework.exceptions import ValidationError

from starrp.services.integrations.shopify import Shopify
from starrp.tests.conftest import Ctx


def test_operador_do_caixa_de_outra_conta_e_recusado(ctx):
    outsider = Ctx("Outra Loja").user("caixa_b", "cashier")
    response = ctx.client().patch(f"/api/v1/cash/registers/{ctx.register.pk}/", {"operator": outsider.pk},
                                  format="json")
    assert response.status_code == 400, response.json()
    assert "outsider" not in str(response.json()).lower() and outsider.first_name not in str(response.json())


@pytest.mark.parametrize("domain", ["127.0.0.1", "169.254.169.254", "evil.example.com", "loja.myshopify.com.evil.io"])
def test_shopify_so_aceita_dominio_da_shopify(domain):
    with pytest.raises(ValidationError):
        Shopify.normalize({"shop_domain": domain, "api_version": "2026-10"})
    assert Shopify.normalize({"shop_domain": "minhaloja", "api_version": "2026-10"})["shop_domain"] == \
        "minhaloja.myshopify.com"


def test_chave_de_idempotencia_nao_devolve_a_resposta_de_outro_usuario(ctx):
    manager = ctx.client(ctx.user("gerente", "manager"))
    seller = ctx.client(ctx.user("vend", "seller"))
    body = {"name": "Marca X"}

    first = manager.post("/api/v1/catalog/brands/", body, format="json", HTTP_IDEMPOTENCY_KEY="mesma-chave")
    other = seller.post("/api/v1/catalog/brands/", body, format="json", HTTP_IDEMPOTENCY_KEY="mesma-chave")

    assert first.status_code == 201
    assert other.status_code == 403  # o vendedor não cadastra marca: não ganha a resposta do gerente
    assert other.get("Idempotent-Replay") is None
