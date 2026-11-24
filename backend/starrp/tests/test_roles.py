"""Cargos fixos do sistema, cargos somados no usuário e perfil fiscal liberado."""
from starrp.core.permissions import has_permission_code
from starrp.models import Role
from starrp.services.access_catalog import SYSTEM_ROLES
from starrp.services.provisioning import ensure_system_roles


def test_cargos_fixos_existem_e_a_conta_personaliza_permissoes(ctx):
    api = ctx.client()
    listed = api.get("/api/v1/roles/?page_size=100").json()["results"]
    seller = next(r for r in listed if r["code"] == "seller")

    create = api.post("/api/v1/roles/", {"code": "x", "name": "Novo", "rank": 10, "permissions": []}, format="json")
    perms = api.patch(f"/api/v1/roles/{seller['id']}/", {"permissions": ["finance.view"]}, format="json")
    tune = api.patch(f"/api/v1/roles/{seller['id']}/", {"max_discount_percent": "8.00"}, format="json")
    ensure_system_roles(ctx.account)  # sincronização (deploy): mantém o ajuste da conta

    codes = {r["code"] for r in listed}
    assert {spec["code"] for spec in SYSTEM_ROLES} <= codes and all(r["is_system"] for r in listed)
    assert create.status_code == 403 and perms.status_code == 200 and tune.status_code == 200
    assert str(Role.all_objects.get(pk=seller["id"]).max_discount_percent) == "8.00"
    assert set(Role.all_objects.get(pk=seller["id"]).permissions.values_list("code", flat=True)) == {"finance.view"}
    assert "logistics.manage" in next(r for r in listed if r["code"] == "logistics")["permissions"]
    assert "partners.credit" in next(r for r in listed if r["code"] == "director")["permissions"]
    assert "partners.credit" not in next(r for r in listed if r["code"] == "manager")["permissions"]
    assert "partners.credit" not in seller["permissions"]


def test_permissoes_crud_do_cargo_sao_independentes(ctx):
    seller = ctx.user("crud", "seller", is_seller=True)
    role = seller.profile.role
    admin = ctx.client()

    configured = admin.patch(f"/api/v1/roles/{role.pk}/", {
        "permissions": ["partners.view", "partners.create"],
    }, format="json")
    seller_api = ctx.client(seller)
    created = seller_api.post("/api/v1/customers/", {"name": "Cliente CRUD"}, format="json")
    customer_id = created.json()["id"]
    denied_update = seller_api.patch(f"/api/v1/customers/{customer_id}/", {"name": "Alterado"}, format="json")
    denied_delete = seller_api.delete(f"/api/v1/customers/{customer_id}/")

    assert configured.status_code == 200, configured.json()
    assert "partners.manage" not in configured.json()["permissions"]
    assert created.status_code == 201, created.json()
    assert denied_update.status_code == 403
    assert denied_delete.status_code == 403

    configured = admin.patch(f"/api/v1/roles/{role.pk}/", {
        "permissions": ["partners.view", "partners.create", "partners.update", "partners.delete"],
    }, format="json")
    updated = ctx.client(seller).patch(f"/api/v1/customers/{customer_id}/", {"name": "Alterado"}, format="json")
    deleted = ctx.client(seller).delete(f"/api/v1/customers/{customer_id}/")

    assert configured.status_code == 200, configured.json()
    assert "partners.manage" in configured.json()["permissions"]
    assert updated.status_code == 200, updated.json()
    assert deleted.status_code == 204


def test_acessos_especiais_de_ia_precificacao_e_seo_tem_nivel_normal_e_total(ctx):
    ctx.account.extra_modules = ["cosmos", "pricing", "seo"]
    ctx.account.save(update_fields=["extra_modules", "updated_at"])
    user = ctx.user("recursos-especiais", "seller", cosmos_enabled=True)
    role = user.profile.role
    admin = ctx.client()

    full = admin.patch(f"/api/v1/roles/{role.pk}/", {
        "permissions": ["cosmos.full", "pricing.full", "seo.full"],
    }, format="json")
    assert full.status_code == 200, full.json()
    assert {"cosmos.access", "cosmos.full", "pricing.access", "pricing.full", "seo.access", "seo.full"} <= set(
        full.json()["permissions"])

    user.refresh_from_db()
    assert has_permission_code(user, "cosmos.view") and has_permission_code(user, "cosmos.manage")
    api = ctx.client(user)
    assert api.get("/api/v1/price-checks/").status_code == 200
    assert api.get("/api/v1/price-checks/rules/").status_code == 200
    assert api.get("/api/v1/seo-checks/").status_code == 200
    assert api.get("/api/v1/seo-checks/rules/").status_code == 200
    assert api.get("/api/v1/background-tasks/").status_code == 200

    normal = admin.patch(f"/api/v1/roles/{role.pk}/", {
        "permissions": ["cosmos.access", "pricing.access", "seo.access"],
    }, format="json")
    assert normal.status_code == 200, normal.json()
    api = ctx.client(user)
    assert api.get("/api/v1/price-checks/").status_code == 200
    assert api.get("/api/v1/price-checks/rules/").status_code == 403
    assert api.get("/api/v1/seo-checks/").status_code == 200
    assert api.get("/api/v1/seo-checks/rules/").status_code == 403
    assert api.get("/api/v1/background-tasks/").status_code == 200


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
    base = {"username": "novo", "password": "S3nha-Forte-2026", "role": roles["seller"], "stores": [str(ctx.store.pk)]}

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
