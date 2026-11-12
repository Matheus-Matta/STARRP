"""Quem acessa quais lojas. Fonte única para usuários, vendedores e relatórios.

A regra do perfil (`UserProfile.allowed_store_ids`) vista ao contrário:
dada uma loja, quais perfis a enxergam.
"""
from django.db.models import Q

from starrp.core.tenant import get_allowed_store_ids


def profiles_reaching(store_ids):
    """Filtro de perfis com acesso a ao menos uma das lojas."""
    return Q(all_stores=True) | Q(role__is_account_admin=True) | Q(extra_roles__is_account_admin=True) | Q(stores__in=list(store_ids))


def visible_profiles(qs):
    """Usuário de filial só enxerga colegas das lojas dele (e quem acessa todas)."""
    allowed = get_allowed_store_ids()
    return qs if allowed is None else qs.filter(profiles_reaching(allowed)).distinct()


def sellers_of(store):
    from starrp.models import UserProfile

    return (
        UserProfile.objects.filter(profiles_reaching([store.pk]), is_seller=True, is_active=True)
        .select_related("user")
        .distinct()
    )


def visible_stores(account, store=None):
    """Filiais que um relatório POR FILIAL lista: a da tela, ou todas as que o usuário enxerga.
    Serve para mostrar também quem não teve movimento (zerada) — ausência também é informação."""
    from starrp.models import Store

    if store is not None:
        return [store]
    qs = Store.all_objects.filter(account=account, deleted_at__isnull=True)
    return list(scope_to_allowed(qs, "pk").order_by("name"))


def include_empty(params):
    """Lojas sem movimento entram, a não ser que peçam para tirar (`include_empty=0/false/nao`)."""
    value = str((params or {}).get("include_empty", "1")).strip().lower()
    return value not in ("0", "false", "nao", "não", "no")


def scope_to_allowed(qs, field="store"):
    """Para consultas de serviço feitas com `all_objects` (relatórios)."""
    allowed = get_allowed_store_ids()
    return qs if allowed is None else qs.filter(**{f"{field}__in": allowed})
