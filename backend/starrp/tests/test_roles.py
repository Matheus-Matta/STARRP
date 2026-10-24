"""Cargos fixos do sistema, cargos somados no usuário e perfil fiscal liberado."""
from starrp.models import Role
from starrp.services.access_catalog import SYSTEM_ROLES
from starrp.services.provisioning import ensure_system_roles


def test_cargos_fixos_existem_e_a_conta_so_ajusta_desconto(ctx):
    api = ctx.client()
    listed = api.get("/api/v1/roles/?page_size=100").json()["results"]
    seller = next(r for r in listed if r["code"] == "seller")

    create = api.post("/api/v1/roles/", {"code": "x", "name": "Novo", "rank": 10, "permissions": []}, format="json")
    perms = api.patch(f"/api/v1/roles/{seller['id']}/", {"permissions": ["finance.manage"]}, format="json")
    tune = api.patch(f"/api/v1/roles/{seller['id']}/", {"max_discount_percent": "8.00"}, format="json")
    ensure_system_roles(ctx.account)  # sincronização (deploy): mantém o ajuste da conta

    codes = {r["code"] for r in listed}
    assert {spec["code"] for spec in SYSTEM_ROLES} <= codes and all(r["is_system"] for r in listed)
    assert create.status_code == 403 and perms.status_code == 400 and tune.status_code == 200
    assert str(Role.all_objects.get(pk=seller["id"]).max_discount_percent) == "8.00"
    assert "logistics.manage" in next(r for r in listed if r["code"] == "logistics")["permissions"]


def test_cargos_somados_juntam_permissoes_e_valem_o_maior(ctx):
    logistics = Role.all_objects.get(account=ctx.account, code="logistics")
    user = ctx.user("ana", "seller", is_seller=True)
    user.profile.extra_roles.set([logistics])
    me = ctx.client(user).get("/api/v1/me/").json()

    assert {"sales.manage", "logistics.manage"} <= set(me["permissions"])
    assert [r["code"] for r in me["roles"]] == ["seller", "logistics"]
    assert user.profile.rank == max(Role.all_objects.get(account=ctx.account, code=c).rank for c in ("seller", "logistics"))


def test_gerente_nao_soma_cargo_acima_do_dele(ctx):
    manager = ctx.user("gil", "manager")
    api = ctx.client(manager)
    roles = {r["code"]: r["id"] for r in api.get("/api/v1/roles/?page_size=100").json()["results"]}
    base = {"username": "novo", "password": "senha123", "role": roles["seller"], "stores": [str(ctx.store.pk)]}

    above = api.post("/api/v1/users/", {**base, "extra_roles": [roles["director"]]}, format="json")
    ok = api.post("/api/v1/users/", {**base, "extra_roles": [roles["logistics"], roles["seller"]]}, format="json")

    assert above.status_code == 400 and "extra_roles" in str(above.json())
    assert ok.status_code == 201 and ok.json()["extra_roles"] == [roles["logistics"]]  # o principal não se repete
    assert ok.json()["roles_label"] == "Vendedor + Auxiliar de logística"


def test_perfil_fiscal_pode_ser_criado_pela_conta(ctx):
    created = ctx.client().post("/api/v1/fiscal/profiles/", {
        "name": "Simples — revenda com ST interna", "cfop": "5405", "cfop_interstate": "6404", "csosn": "500"},
        format="json")
    assert created.status_code == 201, created.json()
