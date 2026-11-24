"""Integrações: configuração, teste de conexão e recepção segura de webhooks."""
import base64
import hashlib
import hmac
import json
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from starrp.models import Integration, IntegrationWebhookEvent
from starrp.services import integrations
from starrp.services.integrations import MASK


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body, self.ok = status, body, 200 <= status < 300

    def json(self):
        return self._body


def test_tipos_declaram_campos_e_o_que_fazem(ctx):
    types = {t["key"]: t for t in ctx.client().get("/api/v1/integrations/types/").json()}
    asaas = types["asaas"]
    fields = {f["name"]: f for f in asaas["fields"]}
    assert fields["api_key"]["type"] == "secret" and fields["api_key"]["required"]
    assert fields["environment"]["default"] == "sandbox"
    keys = {p["key"] for p in asaas["purposes"]}
    assert {"receivable_boleto", "auto_settle"} <= keys and "recurring_boleto" not in keys
    assert "shopify" in types and asaas["testable"] and asaas["logo"] == "/integrations/asaas.png"


def test_duas_contas_do_asaas_com_segredo_guardado_e_uma_padrao(ctx):
    api = ctx.client()
    first = api.post("/api/v1/integrations/", {"kind": "asaas", "name": "Asaas — Empresa A",
                                               "fields": {"api_key": "$aact_A", "environment": "production"}},
                     format="json")
    second = api.post("/api/v1/integrations/", {"kind": "asaas", "name": "Asaas — Empresa B", "is_default": True,
                                                "fields": {"api_key": "$aact_B"},
                                                "purposes": ["receivable_boleto", "inventado"]}, format="json")

    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()
    a, b = first.json(), second.json()
    assert a["fields"]["api_key"] == MASK and a["purposes"] == ["receivable_boleto", "auto_settle"]
    assert b["fields"]["environment"] == "sandbox" and b["purposes"] == ["receivable_boleto"]
    assert Integration.all_objects.get(pk=a["id"]).is_default is False  # a B virou a padrão
    # editar sem mandar a chave (ou com a máscara) mantém a guardada
    api.patch(f"/api/v1/integrations/{a['id']}/", {"fields": {"api_key": MASK, "environment": "sandbox"}}, format="json")
    assert Integration.all_objects.get(pk=a["id"]).fields["api_key"] == "$aact_A"
    chosen = integrations.active("asaas", account=ctx.account, purpose="receivable_boleto")
    assert chosen.get("api_key") == "$aact_B"
    assert integrations.active("asaas", account=ctx.account, pk=a["id"]).get("api_key") == "$aact_A"


def test_obrigatorio_e_tipo_fixo(ctx):
    api = ctx.client()
    missing = api.post("/api/v1/integrations/", {"kind": "asaas", "name": "Sem chave", "fields": {}}, format="json")
    unknown = api.post("/api/v1/integrations/", {"kind": "nada", "name": "X"}, format="json")
    shop = api.post("/api/v1/integrations/", {"kind": "shopify", "name": "Loja", "fields": {
        "shop_domain": "https://MinhaLoja.myshopify.com/", "access_token": "shpat_x"}}, format="json").json()
    changed = api.patch(f"/api/v1/integrations/{shop['id']}/", {"kind": "asaas"}, format="json")

    assert missing.status_code == 400 and "api_key" in str(missing.json())
    assert unknown.status_code in (400, 422)
    assert shop["fields"]["shop_domain"] == "minhaloja.myshopify.com"
    assert changed.status_code == 400


def test_testa_a_conexao_antes_e_depois_de_salvar(ctx):
    api = ctx.client()
    with mock.patch("starrp.services.integrations.asaas.requests.request",
                    return_value=_Response(200, {"companyName": "Empresa A"})) as call:
        draft = api.post("/api/v1/integrations/check/", {"kind": "asaas", "fields": {"api_key": "$aact_A"}},
                         format="json").json()
    assert draft["ok"] and "Empresa A" in draft["message"]
    assert call.call_args.kwargs["headers"]["access_token"] == "$aact_A"
    assert call.call_args.args[1].startswith("https://api-sandbox.asaas.com/v3/")

    saved = api.post("/api/v1/integrations/", {"kind": "asaas", "name": "A", "fields": {"api_key": "$aact_A"}},
                     format="json").json()
    with mock.patch("starrp.services.integrations.asaas.requests.request", return_value=_Response(401, {})):
        refused = api.post(f"/api/v1/integrations/{saved['id']}/test/").json()
    assert not refused["ok"]
    row = Integration.all_objects.get(pk=saved["id"])
    assert row.last_check_ok is False and "recusada" in row.last_check_message


def test_so_o_administrador(ctx):
    seller = ctx.client(ctx.user("vend", "seller"))
    assert seller.get("/api/v1/integrations/").status_code == 403
    assert seller.get("/api/v1/integrations/types/").status_code == 403


@override_settings(API_URL="https://api.starrp.example")
def test_url_publica_do_webhook_usa_dominio_configurado(ctx):
    token = "token-seguro-do-webhook-com-mais-de-32-caracteres"
    response = ctx.client().post("/api/v1/integrations/", {
        "kind": "asaas", "name": "Asaas webhook",
        "fields": {"api_key": "$aact_A", "webhook_token": token},
    }, format="json")

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["webhook_url"] == (
        f"https://api.starrp.example/api/v1/public/webhooks/asaas/{body['id']}/"
    )
    assert body["webhook_ready"] is True


def test_webhook_asaas_autentica_persiste_e_deduplica(ctx):
    token = "token-seguro-do-webhook-com-mais-de-32-caracteres"
    integration = Integration.all_objects.create(
        account=ctx.account, kind="asaas", name="Asaas webhook", is_active=True,
        fields={"api_key": "$aact_A", "webhook_token": token},
    )
    url = f"/api/v1/public/webhooks/asaas/{integration.pk}/"
    payload = {"id": "evt_123", "event": "PAYMENT_RECEIVED", "payment": {"id": "pay_1"}}
    public = APIClient()

    refused = public.post(url, payload, format="json", HTTP_ASAAS_ACCESS_TOKEN="incorreto")
    first = public.post(url, payload, format="json", HTTP_ASAAS_ACCESS_TOKEN=token)
    repeated = public.post(url, payload, format="json", HTTP_ASAAS_ACCESS_TOKEN=token)

    assert refused.status_code == 401
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert repeated.status_code == 200 and repeated.json()["duplicate"] is True
    event = IntegrationWebhookEvent.objects.get(integration=integration)
    assert event.provider_event_id == "evt_123" and event.event_type == "PAYMENT_RECEIVED"
    assert event.payload["payment"]["id"] == "pay_1"


def test_webhook_shopify_valida_hmac_corpo_e_loja(ctx):
    secret = "shopify-client-secret"
    integration = Integration.all_objects.create(
        account=ctx.account, kind="shopify", name="Shopify webhook", is_active=True,
        fields={
            "shop_domain": "minhaloja.myshopify.com", "access_token": "shpat_x",
            "webhook_secret": secret,
        },
    )
    url = f"/api/v1/public/webhooks/shopify/{integration.pk}/"
    raw = json.dumps({"id": 99, "name": "Pedido #99"}, separators=(",", ":")).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    headers = {
        "HTTP_X_SHOPIFY_HMAC_SHA256": signature,
        "HTTP_X_SHOPIFY_SHOP_DOMAIN": "minhaloja.myshopify.com",
        "HTTP_X_SHOPIFY_TOPIC": "orders/create",
        "HTTP_X_SHOPIFY_WEBHOOK_ID": "delivery-99",
        "HTTP_X_SHOPIFY_API_VERSION": "2026-10",
    }

    response = APIClient().post(url, raw, content_type="application/json", **headers)

    assert response.status_code == 200, response.json()
    event = IntegrationWebhookEvent.objects.get(integration=integration)
    # A identidade é o corpo assinado: repetir a entrega com outro X-Shopify-Webhook-Id não cria outro evento (R2-24).
    again = APIClient().post(url, raw, content_type="application/json",
                             **{**headers, "HTTP_X_SHOPIFY_WEBHOOK_ID": "forjado"})
    assert again.json()["duplicate"] is True
    assert event.headers["X-Shopify-Webhook-Id"] == "delivery-99" and event.event_type == "orders/create"
    assert event.headers["X-Shopify-API-Version"] == "2026-10"
    assert "X-Shopify-Hmac-Sha256" not in event.headers
