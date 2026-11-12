"""Regras compartilhadas entre filiais: nascem com a conta, a filial nova fica com a padrão,
uma regra serve a várias filiais e a padrão / a última / a em uso não se excluem."""
import pytest

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import LogisticsRule, StockRule, Store, StoreRule
from starrp.services import rules
from starrp.services.provisioning import create_store

URLS = {"rule": "/api/v1/stores/rules/", "logistics_rule": "/api/v1/logistics/rules/", "stock_rule": "/api/v1/stock/rules/"}


@pytest.fixture
def api(ctx):
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    return ctx.client(store=None)


def test_conta_nasce_com_uma_padrao_de_cada_tipo_e_a_filial_nova_fica_com_ela(ctx):
    nova = create_store(ctx.account, "Filial Nova")

    for field, model in rules.store_rule_fields().items():
        alive = model.all_objects.filter(account=ctx.account, deleted_at__isnull=True)
        assert alive.count() == 1 and alive.get().is_default
        assert getattr(nova, f"{field}_id") == getattr(ctx.store, f"{field}_id") == alive.get().pk


def test_uma_regra_serve_a_varias_filiais(ctx, api):
    b, c = create_store(ctx.account, "Filial B"), create_store(ctx.account, "Filial C")
    created = api.post(URLS["rule"], {"name": "Shopping", "require_seller": True}, format="json", HTTP_X_STORE_ID="*")
    for store in (b, c):
        api.patch(f"/api/v1/stores/{store.pk}/", {"rule": created.json()["id"]}, format="json", HTTP_X_STORE_ID="*")
    shopping = api.get(f"{URLS['rule']}{created.json()['id']}/", HTTP_X_STORE_ID="*").json()

    assert created.status_code == 201 and created.json()["is_default"] is False
    assert shopping["store_names"] == ["Filial B", "Filial C"] and shopping["store_count"] == 2
    assert StoreRule.all_objects.get(pk=ctx.store.rule_id).is_default  # a do contexto segue na padrão


def test_marcar_outra_como_padrao_troca_a_padrao_e_filial_nova_vai_para_ela(ctx, api):
    old = StoreRule.all_objects.get(pk=ctx.store.rule_id)
    created = api.post(URLS["rule"], {"name": "Nova padrão", "is_default": True}, format="json", HTTP_X_STORE_ID="*")
    nova = create_store(ctx.account, "Filial Depois")

    old.refresh_from_db()
    assert created.json()["is_default"] is True and old.is_default is False
    assert str(nova.rule_id) == created.json()["id"]
    assert StoreRule.all_objects.filter(account=ctx.account, is_default=True, deleted_at__isnull=True).count() == 1


@pytest.mark.parametrize("field", list(URLS))
def test_validadores_nao_deixam_o_sistema_sem_regra(ctx, api, field):
    url = URLS[field]
    default_id = str(getattr(ctx.store, f"{field}_id"))
    other = api.post(url, {"name": "Outra"}, format="json", HTTP_X_STORE_ID="*").json()
    store = create_store(ctx.account, "Filial Que Usa")
    api.patch(f"/api/v1/stores/{store.pk}/", {field: other["id"]}, format="json", HTTP_X_STORE_ID="*")

    unset = api.patch(f"{url}{default_id}/", {"is_default": False}, format="json", HTTP_X_STORE_ID="*")
    delete_default = api.delete(f"{url}{default_id}/", HTTP_X_STORE_ID="*")
    delete_in_use = api.delete(f"{url}{other['id']}/", HTTP_X_STORE_ID="*")
    bulk = api.post(f"{url}bulk/", {"action": "delete", "ids": [default_id, other["id"]]}, format="json",
                    HTTP_X_STORE_ID="*")

    assert unset.status_code == 400 and "padrão" in str(unset.json())
    assert delete_default.status_code == 409 and "padrão" in str(delete_default.json())
    assert delete_in_use.status_code == 409 and "Filial Que Usa" in str(delete_in_use.json())
    assert bulk.status_code == 200 and bulk.json()["affected"] == 0 and len(bulk.json()["skipped"]) == 2

    # Sem filial usando, a não padrão sai; a padrão (agora a única) continua.
    api.patch(f"/api/v1/stores/{store.pk}/", {field: default_id}, format="json", HTTP_X_STORE_ID="*")
    gone = api.delete(f"{url}{other['id']}/", HTTP_X_STORE_ID="*")
    rows = api.get(url, HTTP_X_STORE_ID="*").json()["results"]
    assert gone.status_code == 204 and [r["id"] for r in rows] == [default_id]


def test_no_modelo_tambem_a_padrao_e_a_ultima_ficam(ctx):
    for model in (StoreRule, LogisticsRule, StockRule):
        only = model.all_objects.get(account=ctx.account, is_default=True)
        with pytest.raises(StateConflict):
            only.delete()
        only.is_default = False
        with pytest.raises(BusinessError):
            only.save()


def test_filial_sem_regra_escolhida_recebe_a_padrao_ao_salvar(ctx):
    store = Store.all_objects.get(pk=ctx.store.pk)
    store.rule = None
    store.save(update_fields=["name"])

    assert Store.all_objects.get(pk=store.pk).rule_id == StoreRule.all_objects.get(account=ctx.account, is_default=True).pk
