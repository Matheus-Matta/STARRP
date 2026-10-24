"""Dados fixos: nascem com a conta (sinal) e só o superusuário cria ou exclui."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from starrp.models import FiscalProfile, PaymentMethod
from starrp.services.system_data import FISCAL_PROFILES, PAYMENT_METHODS


def test_conta_nova_ja_tem_formas_de_pagamento_e_perfis_fiscais(ctx):
    methods = PaymentMethod.all_objects.filter(account=ctx.account, deleted_at__isnull=True)
    profiles = FiscalProfile.all_objects.filter(account=ctx.account, deleted_at__isnull=True)

    assert methods.count() == len(PAYMENT_METHODS) and profiles.count() == len(FISCAL_PROFILES) == 10
    assert profiles.filter(is_default=True).count() == 1
    assert methods.get(kind="cash").opens_drawer is True


def test_admin_da_loja_ajusta_mas_nao_cria_nem_exclui(ctx):
    api = ctx.client()
    card = PaymentMethod.all_objects.get(account=ctx.account, kind="credit_card")
    profile = FiscalProfile.all_objects.filter(account=ctx.account).first()

    created = api.post("/api/v1/payment-methods/", {"name": "Cheque", "kind": "other"}, format="json")
    deleted = api.delete(f"/api/v1/fiscal/profiles/{profile.pk}/")  # pré-pronto: não exclui (cria, sim)
    adjusted = api.patch(f"/api/v1/payment-methods/{card.pk}/", {"fee_percent": "2.99"}, format="json")
    actions = [a["name"] for a in api.get("/api/v1/payment-methods/bulk/").json()]

    assert created.status_code == 403 and deleted.status_code == 409
    assert adjusted.status_code == 200 and PaymentMethod.all_objects.get(pk=card.pk).fee_percent == Decimal("2.99")
    assert "delete" not in actions and "deactivate" in actions


def test_superusuario_cria(ctx):
    root = get_user_model().objects.create_superuser("suporte", password="x")
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(root).access_token}",
                    HTTP_X_STORE_ID=str(ctx.store.pk), HTTP_X_ACCOUNT_ID=str(ctx.account.pk))

    response = api.post("/api/v1/payment-methods/", {"name": "Cheque", "kind": "other"}, format="json")

    assert response.status_code == 201, response.json()
    assert PaymentMethod.all_objects.filter(account=ctx.account, name="Cheque").exists()
