"""Asaas (cobranças: boleto, Pix, cartão). Docs: https://docs.asaas.com

Por enquanto: a configuração e o teste de conexão. A emissão de boletos das contas a receber (as recorrências
geram títulos a receber, então entram juntas) e a baixa pelo webhook vêm nas próximas fases.
"""
import hmac

import requests

from .base import CheckResult, Field, IntegrationType, Purpose, register

BASE_URLS = {"sandbox": "https://api-sandbox.asaas.com/v3", "production": "https://api.asaas.com/v3"}


@register
class Asaas(IntegrationType):
    key = "asaas"
    label = "Asaas"
    description = "Boletos, Pix e cartão das contas a receber e das cobranças recorrentes, com baixa automática."
    category = "Cobrança"
    icon = "pi pi-wallet"
    logo = "/integrations/asaas.png"
    docs_url = "https://docs.asaas.com"
    supports_webhooks = True
    webhook_secret_field = "webhook_token"
    fields = (
        Field("environment", "Ambiente", "select", required=True, default="sandbox",
              options=(("sandbox", "Sandbox (testes)"), ("production", "Produção")),
              help="Comece no sandbox: as cobranças lá não são reais."),
        Field("api_key", "Chave da API", "secret", required=True, placeholder="$aact_...",
              help="No Asaas: Integrações → Chave de API. Fica guardada e não aparece de novo."),
        Field("financial_account", "Conta financeira do Asaas", "relation", relation="/finance/accounts/",
              help="Onde entram os valores recebidos (o saldo que fica no Asaas). Vazio = escolher depois."),
        Field("webhook_token", "Token do webhook", "secret",
              help="O mesmo informado no webhook do Asaas: confirma que o aviso de pagamento veio dele."),
        Field("billing_type", "Forma padrão", "select", default="BOLETO",
              options=(("BOLETO", "Boleto (com Pix)"), ("PIX", "Pix"), ("UNDEFINED", "Cliente escolhe"))),
        Field("days_before_due", "Gerar quantos dias antes do vencimento", "number", default="10",
              help="A cobrança é criada no Asaas esta quantidade de dias antes do vencimento da parcela."),
    )
    purposes = (
        Purpose("receivable_boleto", "Gerar cobrança das contas a receber",
                "Cada parcela marcada vira um boleto/Pix no Asaas — inclusive as das contas recorrentes, que já "
                "geram o título a receber.", default=True),
        Purpose("auto_settle", "Dar baixa automática ao receber",
                "O aviso de pagamento do Asaas baixa a parcela e lança a taxa como despesa.", default=True),
        Purpose("notify_customer", "O Asaas avisa o cliente",
                "E-mail/SMS do Asaas com o boleto e os lembretes de vencimento."),
    )

    @property
    def base_url(self):
        return BASE_URLS.get(self.get("environment"), BASE_URLS["sandbox"])

    def request(self, method, path, **kwargs):
        headers = {"access_token": self.get("api_key", ""), "User-Agent": "Starrp", "Content-Type": "application/json"}
        return requests.request(method, f"{self.base_url}{path}", headers=headers, timeout=20, **kwargs)

    def test(self):
        if not self.get("api_key"):
            return CheckResult(False, "Informe a chave da API.")
        try:
            response = self.request("GET", "/myAccount/commercialInfo")
        except requests.RequestException:
            return CheckResult(False, "O Asaas não respondeu. Tente de novo em instantes.")
        if response.status_code == 401:
            return CheckResult(False, "Chave da API recusada pelo Asaas (confira o ambiente: sandbox × produção).")
        if not response.ok:
            return CheckResult(False, f"O Asaas respondeu {response.status_code}.")
        try:
            body = response.json()
        except ValueError:
            body = {}
        name = body.get("companyName") or body.get("name") or ""
        where = "sandbox" if self.get("environment") == "sandbox" else "produção"
        return CheckResult(True, f"Conectado ao Asaas ({where}){': ' + name if name else ''}.",
                           {"account_name": name})

    def verify_webhook(self, raw_body, headers, payload):
        expected = str(self.get("webhook_token") or "")
        received = str(headers.get("asaas-access-token") or "")
        return bool(expected and received) and hmac.compare_digest(expected.encode(), received.encode())

    def webhook_event_id(self, headers, payload, raw_body=b""):
        return str(payload.get("id") or "")

    def webhook_event_type(self, headers, payload):
        return str(payload.get("event") or "")
