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


def scope_to_allowed(qs, field="store"):
    """Para consultas de serviço feitas com `all_objects` (relatórios)."""
    allowed = get_allowed_store_ids()
    return qs if allowed is None else qs.filter(**{f"{field}__in": allowed})
