"""Escalada de privilégio pela gestão de usuários (docs/SEGURANCA.md S-03 e S-24)."""
from starrp.models import Permission, UserProfile


def _profile(user):
    return UserProfile.all_objects.get(user=user)


def test_suporte_de_ti_nao_concede_a_si_mesmo_permissao_que_nao_tem(ctx):
    it = ctx.user("ti", "it")
    api = ctx.client(it)
    profile = _profile(it)

    response = api.patch(f"/api/v1/users/{profile.pk}/", {"extra_permissions": ["catalog.view_costs", "cash.approve"]},
                         format="json")

    assert response.status_code == 400, response.json()
    assert not {"catalog.view_costs", "cash.approve"} & _profile(it).permission_codes()


def test_ninguem_altera_o_proprio_acesso(ctx):
    manager = ctx.user("gerente", "manager")
    api = ctx.client(manager)
    profile = _profile(manager)
    granted = sorted(_profile(manager).permission_codes())[:1]  # até o que ele tem: não no próprio perfil

    response = api.patch(f"/api/v1/users/{profile.pk}/", {"extra_permissions": granted}, format="json")
    own_name = api.patch(f"/api/v1/users/{profile.pk}/", {"first_name": "Gê"}, format="json")

    assert response.status_code == 400, response.json()
    assert own_name.status_code == 200, own_name.json()


def test_nao_cria_usuario_com_permissao_acima_da_sua(ctx):
    it = ctx.user("ti", "it")
    seller_role = ctx.user_role("seller")
    body = {"username": "novo", "password": "S3nha-Forte-2026", "role": str(seller_role.pk), "stores": [str(ctx.store.pk)],
            "extra_permissions": ["cash.approve", "sales.cancel"]}

    response = ctx.client(it).post("/api/v1/users/", body, format="json")

    assert response.status_code == 400, response.json()


def test_cargo_novo_com_acesso_que_quem_grava_nao_tem_e_recusado(ctx):
    it = ctx.user("ti", "it")
    seller = ctx.user("vend", "seller")
    stockist = ctx.user_role("stockist")  # dá custo/margem, que o TI não tem
    assert "catalog.view_costs" in set(stockist.permissions.values_list("code", flat=True))

    response = ctx.client(it).patch(f"/api/v1/users/{_profile(seller).pk}/",
                                    {"extra_roles": [str(stockist.pk)]}, format="json")

    assert response.status_code == 400, response.json()


def test_suporte_de_ti_nao_troca_senha_nem_exclui_quem_esta_acima(ctx):
    it = ctx.user("ti", "it")
    manager = ctx.user("gerente", "manager")
    api = ctx.client(it)
    target = _profile(manager)

    password = api.patch(f"/api/v1/users/{target.pk}/", {"password": "Tomada-De-Conta-99"}, format="json")
    deleted = api.delete(f"/api/v1/users/{target.pk}/")
    admin = api.patch(f"/api/v1/users/{_profile(ctx.admin).pk}/", {"password": "Tomada-De-Conta-99"}, format="json")

    assert password.status_code == 400, password.json()
    assert deleted.status_code == 403
    assert admin.status_code == 400
    manager.refresh_from_db()
    assert manager.check_password("senha123")


def test_admin_da_conta_concede_normalmente_e_senha_fraca_e_recusada(ctx):
    seller = ctx.user("vend", "seller")
    api = ctx.client()
    profile = _profile(seller)

    granted = api.patch(f"/api/v1/users/{profile.pk}/", {"extra_permissions": ["catalog.view_costs"]}, format="json")
    weak = api.patch(f"/api/v1/users/{profile.pk}/", {"password": "123456"}, format="json")

    assert granted.status_code == 200, granted.json()
    assert "catalog.view_costs" in _profile(seller).permission_codes()
    assert weak.status_code == 400
    assert Permission.objects.filter(code="catalog.view_costs").exists()


def test_acao_em_massa_nao_desativa_quem_esta_acima_nem_o_proprio(ctx):
    """Rodada 1 (S-24 por outro caminho): /users/bulk/ deactivate passava por fora do serializer."""
    it = ctx.user("ti", "it")
    manager = ctx.user("gerente", "manager")
    seller = ctx.user("vend", "seller")
    api = ctx.client(it)

    for target in (ctx.admin, manager, it):
        response = api.post("/api/v1/users/bulk/", {"action": "deactivate", "ids": [str(_profile(target).pk)]},
                            format="json")
        assert response.status_code == 403, (target.username, response.json())
        assert _profile(target).is_active
    # O vendedor tem acesso que o TI não tem (vende): o TI não mexe nele; o gerente (que tem tudo dele) mexe.
    assert api.post("/api/v1/users/bulk/", {"action": "deactivate", "ids": [str(_profile(seller).pk)]},
                    format="json").status_code == 403
    below = ctx.client(manager).post("/api/v1/users/bulk/", {"action": "deactivate", "ids": [str(_profile(seller).pk)]},
                                     format="json")
    assert below.status_code == 200, below.json()
