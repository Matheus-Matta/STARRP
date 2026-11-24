"""Ensaio da Cosmos sem efeito externo (docs/SEGURANCA.md S-05)."""
import urllib.request

import pytest
import requests

from starrp.core.dry_run import ExternalEffect, dry_run
from starrp.models import Sale
from starrp.services import invoice_cancel
from starrp.services.cosmos import bridge


def test_dentro_do_ensaio_nada_sai_para_fora():
    from starrp.tasks import housekeeping as tasks

    with dry_run():
        with pytest.raises(ExternalEffect):
            requests.get("https://sefaz.invalid/")
        with pytest.raises(ExternalEffect):
            urllib.request.urlopen("https://osrm.invalid/")  # noqa: S310
        with pytest.raises(ExternalEffect):
            tasks.housekeeping_task.delay()


def test_fora_do_ensaio_a_trava_nao_atrapalha(monkeypatch):
    called = []
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", lambda self, request, **kw: called.append(request.url))
    try:
        requests.get("https://exemplo.invalid/")
    except Exception:  # noqa: BLE001 — a resposta falsa não importa: só que a chamada aconteceu
        pass
    assert called == ["https://exemplo.invalid/"]


def test_ensaio_de_cancelamento_que_falaria_com_a_sefaz_nao_cancela_nada(ctx, monkeypatch):
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    done = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                    {"payments": [{"nsu": "1", "method": str(ctx.methods["pix"].pk), "amount": "30.00"}]}, format="json")
    assert done.status_code == 200, done.json()
    sent = []
    real_cancel = invoice_cancel.cancel_sale_and_invoices

    def cancel_with_sefaz(*args, **kwargs):
        requests.post("https://sefaz.invalid/cancelar")  # o que a nota em nuvem faria
        sent.append(True)
        return real_cancel(*args, **kwargs)

    monkeypatch.setattr(invoice_cancel, "cancel_sale_and_invoices", cancel_with_sefaz)
    actor = bridge.actor_for(ctx.admin, str(ctx.store.pk))

    result = bridge.call(actor, "POST", f"sales/{sale['id']}/cancel/", body={"reason": "teste"}, dry_run=True)

    assert result.external is True
    assert sent == []  # parou antes de sair
    assert Sale.all_objects.get(pk=sale["id"]).status == Sale.Status.COMPLETED


# ── S-08: o cartão mostra o que será gravado; acesso e segredos fora da Cosmos ─────────────────────────────

def _tool_ctx(ctx):
    from starrp.models import CosmosConversation
    from starrp.services.cosmos import tools

    ctx.account.extra_modules = sorted({*(ctx.account.extra_modules or []), "cosmos"})
    ctx.account.save(update_fields=["extra_modules"])
    actor = bridge.actor_for(ctx.admin, str(ctx.store.pk))
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin, title="Teste")
    return tools, tools.ToolContext(actor=actor, conversation=conversation)


def test_cosmos_nao_propoe_mexer_em_usuarios_cargos_nem_dados_fiscais(ctx):
    from starrp.models import CosmosAction, UserProfile

    tools, tool_ctx = _tool_ctx(ctx)
    profile = UserProfile.all_objects.get(user=ctx.admin)
    for path, body in ((f"/users/{profile.pk}/", {"extra_permissions": ["catalog.view_costs"]}),
                       ("/roles/", {"name": "Dono"}),
                       (f"/stores/{ctx.store.pk}/", {"cash_action_password": "1"})):
        tools.run(tool_ctx, "propor_alteracao", {"metodo": "PATCH" if "users" in path or "stores" in path else "POST",
                                                  "caminho": path, "corpo": body, "titulo": "Telefone: atualizado"})
    assert not CosmosAction.all_objects.exists()


def test_cartao_mostra_o_valor_real_mesmo_que_o_modelo_diga_outro(ctx):
    from starrp.models import CosmosAction

    tools, tool_ctx = _tool_ctx(ctx)
    tools.run(tool_ctx, "propor_alteracao", {
        "metodo": "POST", "caminho": "/catalog/brands/", "corpo": {"name": "Marca Real"}, "titulo": "Cadastrar marca",
        "campos": [{"chave": "name", "rotulo": "Nome", "valor": "Outra coisa inocente"}]})

    preview = CosmosAction.all_objects.get().preview
    row = next(r for r in preview if r["label"] == "Nome")
    assert row["value"] == "Marca Real"  # o que será gravado
    assert row.get("note") == "Outra coisa inocente"  # o texto do modelo é só nota
