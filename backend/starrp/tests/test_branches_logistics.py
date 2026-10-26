"""Filiais: hierarquia (quem responde a quem) e configuração de logística por filial."""
from starrp.models import Store
from starrp.services.provisioning import create_store


def test_hierarquia_de_filiais_lista_em_arvore_e_recusa_ciclo(ctx):
    regional = create_store(ctx.account, "Regional Sul")
    branch = create_store(ctx.account, "Filial Curitiba")
    api = ctx.client(store=None)

    set_regional = api.patch(f"/api/v1/stores/{regional.pk}/", {"kind": "regional", "parent": str(ctx.store.pk)},
                             format="json")
    set_branch = api.patch(f"/api/v1/stores/{branch.pk}/", {"parent": str(regional.pk)}, format="json")
    cycle = api.patch(f"/api/v1/stores/{ctx.store.pk}/", {"parent": str(branch.pk)}, format="json")
    roots = api.get("/api/v1/stores/", {"root": "1"}, HTTP_X_STORE_ID="*").json()["results"]
    under_regional = api.get("/api/v1/stores/", {"parent": str(regional.pk)}, HTTP_X_STORE_ID="*").json()["results"]

    assert set_regional.status_code == 200 and set_branch.json()["parent_name"] == "Regional Sul"
    assert cycle.status_code == 400 and "subordinada" in str(cycle.json())
    assert [r["name"] for r in roots] == [ctx.store.name] and roots[0]["children_count"] == 1
    assert [r["name"] for r in under_regional] == ["Filial Curitiba"]
    assert Store.all_objects.get(pk=ctx.store.pk).parent_id is None


def test_conferencia_manual_e_ligada_por_filial(ctx):
    other = create_store(ctx.account, "Filial B")
    api = ctx.client(store=None)

    rows = {r["store_name"]: r for r in api.get("/api/v1/logistics/settings/", HTTP_X_STORE_ID="*").json()["results"]}
    turned = api.patch(f"/api/v1/logistics/settings/{rows['Filial B']['id']}/", {"allow_manual_conference": True},
                       format="json", HTTP_X_STORE_ID="*")
    again = {r["store_name"]: r for r in api.get("/api/v1/logistics/settings/", HTTP_X_STORE_ID="*").json()["results"]}
    create = api.post("/api/v1/logistics/settings/", {"allow_manual_conference": True}, format="json")

    assert set(rows) == {ctx.store.name, "Filial B"} and turned.status_code == 200
    assert again["Filial B"]["allow_manual_conference"] is True
    assert again[ctx.store.name]["allow_manual_conference"] is False
    assert create.status_code == 405
    assert other.pk
