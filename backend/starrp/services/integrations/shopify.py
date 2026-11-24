"""Shopify (loja virtual). Docs: https://shopify.dev/docs/api/admin-rest

Por enquanto: a configuração e o teste de conexão. Pedidos, produtos e estoque vêm nas próximas fases.
"""
import base64
import hashlib
import hmac
import re

import requests
from rest_framework.exceptions import ValidationError

from .base import CheckResult, Field, IntegrationType, Purpose, register

SHOP_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.myshopify\.com$")
API_VERSION = re.compile(r"^\d{4}-\d{2}$")


@register
class Shopify(IntegrationType):
    key = "shopify"
    label = "Shopify"
    description = "Loja virtual: pedidos entram como vendas, e produtos, preços e estoque vão para a loja."
    category = "E-commerce"
    icon = "pi pi-shopping-bag"
    logo = "/integrations/shopify.svg"
    docs_url = "https://shopify.dev/docs/api/admin-rest"
    available = False  # só a configuração por enquanto
    supports_webhooks = True
    webhook_secret_field = "webhook_secret"
    fields = (
        Field("shop_domain", "Domínio da loja", "text", required=True, placeholder="minhaloja.myshopify.com"),
        Field("access_token", "Token de acesso (Admin API)", "secret", required=True, placeholder="shpat_...",
              help="App personalizado da loja → Credenciais da API → Token de acesso da Admin API."),
        Field("webhook_secret", "Segredo do app para webhooks", "secret",
              help="Client secret do app Shopify. Usado somente para validar o HMAC de cada webhook."),
        Field("api_version", "Versão da API", "text", default="2026-10"),
        Field("store", "Filial dos pedidos", "relation", relation="/stores/",
              help="Os pedidos da loja virtual entram como vendas desta filial."),
        Field("location_id", "Local de estoque na Shopify", "text", help="Vazio = o local principal."),
    )
    purposes = (
        Purpose("import_orders", "Trazer os pedidos como vendas", default=True),
        Purpose("sync_products", "Enviar produtos e preços"),
        Purpose("sync_stock", "Enviar o estoque", default=True),
    )

    @classmethod
    def normalize(cls, values):
        domain = re.sub(r"^https?://", "", str(values.get("shop_domain") or "")).strip().strip("/").lower()
        if domain and "." not in domain:
            domain = f"{domain}.myshopify.com"
        # Só o domínio da Shopify (S-19): o servidor chama este endereço com o token; outro host seria SSRF
        # (rede interna, metadados da nuvem) e entregaria o token a quem o domínio apontar.
        if domain and not SHOP_DOMAIN.match(domain):
            raise ValidationError({"shop_domain": "Use o domínio da loja na Shopify: minhaloja.myshopify.com."})
        version = str(values.get("api_version") or "").strip()
        if version and not API_VERSION.match(version):
            raise ValidationError({"api_version": "Versão no formato AAAA-MM (ex.: 2026-10)."})
        return {**values, "shop_domain": domain, "api_version": version or values.get("api_version")}

    def test(self):
        domain, token = self.get("shop_domain"), self.get("access_token")
        if not (domain and token):
            return CheckResult(False, "Informe o domínio e o token.")
        try:
            response = requests.get(f"https://{domain}/admin/api/{self.get('api_version')}/shop.json",
                                    headers={"X-Shopify-Access-Token": token}, timeout=20)
        except requests.RequestException:
            return CheckResult(False, f"A loja {domain} não respondeu.")
        if response.status_code in (401, 403):
            return CheckResult(False, "Token recusado pela Shopify.")
        if not response.ok:
            return CheckResult(False, f"A Shopify respondeu {response.status_code}.")
        try:
            name = (response.json().get("shop") or {}).get("name", "")
        except ValueError:
            name = ""
        return CheckResult(True, f"Conectado à loja {name or domain}.", {"shop_name": name})

    def verify_webhook(self, raw_body, headers, payload):
        secret = str(self.get("webhook_secret") or "")
        received = str(headers.get("X-Shopify-Hmac-Sha256") or "")
        shop = str(headers.get("X-Shopify-Shop-Domain") or "").strip().lower()
        if not (secret and received and shop == str(self.get("shop_domain") or "").lower()):
            return False
        expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected.encode(), received.encode())

    def webhook_event_id(self, headers, payload, raw_body=b""):
        # O HMAC cobre só o corpo: o X-Shopify-Webhook-Id pode ser trocado por quem repete uma entrega capturada
        # (R2-24). A identidade é o corpo assinado + o tópico; a reentrega da Shopify manda o mesmo corpo.
        topic = str(headers.get("X-Shopify-Topic") or "")
        return hashlib.sha256(topic.encode() + b"\n" + raw_body).hexdigest() if raw_body else ""

    def webhook_event_type(self, headers, payload):
        return str(headers.get("X-Shopify-Topic") or "")

    def webhook_headers(self, headers):
        names = (
            "X-Shopify-Topic", "X-Shopify-Shop-Domain", "X-Shopify-API-Version",
            "X-Shopify-Webhook-Id", "X-Shopify-Triggered-At", "X-Shopify-Event-Id",
        )
        return {name: headers.get(name) for name in names if headers.get(name)}
