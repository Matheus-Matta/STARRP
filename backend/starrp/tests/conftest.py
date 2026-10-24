from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from starrp.core.tenant import tenant_context
from starrp.models import CashRegister, PaymentMethod, Role, UserProfile
from starrp.services import catalog
from starrp.services.provisioning import create_account


class Ctx:
    """Uma conta pronta (via provisionamento real) e clientes autenticados."""

    def __init__(self, name="Loja Teste"):
        self.account, self.store, self.admin = create_account(
            name=name, admin_username=f"admin-{name}".replace(" ", "").lower(), admin_password="senha123"
        )
        self.register = CashRegister.all_objects.get(store=self.store)
        self.methods = {m.kind: m for m in PaymentMethod.all_objects.filter(account=self.account)}

    def client(self, user=None, store="default"):
        """`store=None` não manda X-Store-ID (a API decide pela loja padrão/única)."""
        client = APIClient()
        token = RefreshToken.for_user(user or self.admin).access_token
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        store = self.store if store == "default" else store
        if store is not None:
            headers["HTTP_X_STORE_ID"] = str(store.pk)
        client.credentials(**headers)
        return client

    def user(self, username, role_code, stores=None, **profile):
        """Usuário com acesso às `stores` (padrão: a loja do contexto)."""
        user = get_user_model().objects.create_user(username, password="senha123", first_name=username.title())
        role = Role.all_objects.get(account=self.account, code=role_code)
        created = UserProfile.all_objects.create(account=self.account, user=user, role=role, **profile)
        if not profile.get("all_stores"):
            created.stores.set(stores if stores is not None else [self.store])
        return user

    def user_role(self, code):
        return Role.all_objects.get(account=self.account, code=code)

    VARIANT_FIELDS = ("promotional_price", "scale_code", "min_stock")

    def product(self, name="Camiseta", price="50.00", barcode=None, **fields):
        """Produto simples; devolve a VARIANTE (é ela que se vende e estoca)."""
        extra = {k: fields.pop(k) for k in self.VARIANT_FIELDS if k in fields}
        variant = catalog.create_simple(
            self.account.id, self.admin, name=name, sku=fields.pop("sku", name.upper()[:10]), price=Decimal(price),
            barcodes=[barcode] if barcode else [], **fields,
        )
        for key, value in extra.items():
            setattr(variant, key, value)
        if extra:
            variant.save()
        return variant

    def tenant(self):
        return tenant_context(self.account)


@pytest.fixture
def ctx(db):
    return Ctx()


@pytest.fixture
def other(db):
    return Ctx(name="Outra Loja")
