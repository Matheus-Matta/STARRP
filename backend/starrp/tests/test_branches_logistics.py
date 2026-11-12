"""Filiais: hierarquia (quem responde a quem) e a regra de logística de cada filial."""
from starrp.models import Store
from starrp.services import rules
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


def test_conferencia_manual_e_ligada_pela_regra_de_logistica_da_filial(ctx):
    """Filial B usa outra regra de logística (com conferência manual); a filial do contexto segue na padrão."""
    other = create_store(ctx.account, "Filial B")
    api = ctx.client(store=None)

    created = api.post("/api/v1/logistics/rules/", {"name": "Confere à mão", "allow_manual_conference": True},
                       format="json", HTTP_X_STORE_ID="*")
    moved = api.patch(f"/api/v1/stores/{other.pk}/", {"logistics_rule": created.json()["id"]}, format="json",
                      HTTP_X_STORE_ID="*")
    rows = {r["name"]: r for r in api.get("/api/v1/logistics/rules/", HTTP_X_STORE_ID="*").json()["results"]}

    assert created.status_code == 201 and moved.status_code == 200
    assert rows["Confere à mão"]["store_names"] == ["Filial B"] and rows["Confere à mão"]["is_default"] is False
    assert rows["Padrão"]["is_default"] is True and ctx.store.name in rows["Padrão"]["store_names"]
    assert rules.of_store("logistics_rule", other.pk, ctx.account.pk).allow_manual_conference is True
    assert rules.of_store("logistics_rule", ctx.store.pk, ctx.account.pk).allow_manual_conference is False
