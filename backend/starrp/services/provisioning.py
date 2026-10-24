"""Criação de conta pronta para vender: tudo que o PDV precisa no primeiro dia."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from starrp.models import (
    Account, CashRegister, Permission, Role, StockSettings, Store,
    UserProfile, Warehouse,
)
from starrp.services import fiscal_data
from starrp.services.access_catalog import SYSTEM_ROLES, permission_rows
from starrp.services.finance_setup import ensure_defaults, vault_for



def sync_permissions():
    for code, name, group, module, order in permission_rows():
        Permission.objects.update_or_create(
            code=code, defaults={"name": name, "group": group, "module": module, "sort_order": order}
        )


ACCOUNT_TUNABLE = ("max_discount_percent",)  # o que a conta pode ajustar no cargo fixo (e is_active)


def ensure_system_roles(account):
    """Cargos fixos da conta, sempre iguais ao catálogo. O desconto máximo e o "ativo" ficam
    como a conta deixou; nome, nível, área, descrição e permissões vêm do catálogo."""
    roles = {}
    for spec in SYSTEM_ROLES:
        spec = dict(spec)
        codes, code = spec.pop("permissions"), spec.pop("code")
        role = Role.all_objects.filter(account=account, code=code, deleted_at=None).first()
        if role is None:
            role = Role.all_objects.create(account=account, code=code, is_system=True, **spec)
        else:
            for field, value in spec.items():
                if field not in ACCOUNT_TUNABLE or not role.is_system:
                    setattr(role, field, value)
            role.is_system = True
            role.save()
        role.permissions.set(Permission.objects.filter(code__in=codes))
        roles[role.code] = role
    return roles


@transaction.atomic
def create_store(account, name, **fields):
    store = Store.all_objects.create(account=account, name=name, **fields)
    Warehouse.all_objects.create(account=account, store=store, name="Loja", kind=Warehouse.Kind.SALES_FLOOR,
                                 is_default=True)
    CashRegister.all_objects.create(account=account, store=store, name="Caixa 01", code="01")
    if store.cnpj:
        fiscal_data.from_store(store)
    vault_for(store)
    return store


@transaction.atomic
def create_account(*, name, admin_username, admin_password, admin_email="", store_name=None, document=""):
    sync_permissions()
    base_slug = slugify(name) or "conta"
    slug, n = base_slug, 1
    while Account.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base_slug}-{n}"
    account = Account.objects.create(name=name, slug=slug, document=document)
    roles = ensure_system_roles(account)
    store = create_store(account, store_name or name)
    StockSettings.all_objects.create(account=account)
    # Formas de pagamento e perfis fiscais: o sinal de Account já criou (services/system_data.py).
    ensure_defaults(account)
    user = get_user_model().objects.create_user(admin_username, email=admin_email, password=admin_password)
    UserProfile.all_objects.create(account=account, user=user, role=roles["admin"])
    return account, store, user
