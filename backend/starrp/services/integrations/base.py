"""Base das integrações: cada TIPO (Asaas, Shopify...) é uma classe que herda `IntegrationType`.

O tipo declara, uma vez:
- `fields`: as configurações que ele usa, com NOME FIXO (o código lê por ele), rótulo, se é obrigatória,
  se é segredo (nunca volta para a tela) e o tipo do campo no formulário;
- `purposes`: o que a integração pode fazer ("Gerar boleto das contas a receber"...) — a conta liga o que quer;
- `test()`: a conferência da conexão (opcional).

A linha da conta (`Integration`) guarda só os valores (`fields`) e o que foi ligado (`purposes`): dá para ter
várias do mesmo tipo (duas contas do Asaas, duas lojas Shopify), cada uma com o seu nome.

Para criar um tipo novo: uma subclasse com `@register` num módulo deste pacote, importado em `__init__.py`.
"""
from dataclasses import dataclass, field as dc_field
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from starrp.core.errors import BusinessError

#: Tipos de campo que o formulário sabe desenhar.
FIELD_TYPES = {"text", "secret", "url", "email", "number", "boolean", "select", "relation"}
#: Valor que a tela recebe no lugar de um segredo já guardado.
MASK = "••••••••"


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    type: str = "text"
    required: bool = False
    default: object = None
    help: str = ""
    placeholder: str = ""
    #: select: [(valor, rótulo)]
    options: tuple = ()
    #: relation: endpoint da API para escolher o registro (ex.: "/finance/accounts/").
    relation: str = ""
    #: Só vale/aparece quando outro campo tem um destes valores: {"environment": ["production"]}.
    when: dict = dc_field(default_factory=dict)

    def __post_init__(self):
        if self.type not in FIELD_TYPES:
            raise ValueError(f"Tipo de campo desconhecido: {self.type}")

    @property
    def secret(self):
        return self.type == "secret"

    def applies(self, values):
        return all(values.get(name) in allowed for name, allowed in self.when.items())

    def as_dict(self):
        return {"name": self.name, "label": self.label, "type": self.type, "required": self.required,
                "default": self.default, "help": self.help, "placeholder": self.placeholder,
                "options": [{"value": v, "label": label} for v, label in self.options],
                "relation": self.relation or None, "when": self.when or None}


@dataclass(frozen=True)
class Purpose:
    """Uma coisa que a integração faz por conta: a etapa "O que vai fazer?"."""
    key: str
    label: str
    description: str = ""
    default: bool = False

    def as_dict(self):
        return {"key": self.key, "label": self.label, "description": self.description, "default": self.default}


@dataclass
class CheckResult:
    ok: bool
    message: str
    data: dict = dc_field(default_factory=dict)


class IntegrationType:
    """Um tipo de integração. Subclasse = um serviço externo."""

    key = ""
    label = ""
    description = ""
    category = "Outros"
    icon = "pi pi-link"
    #: Marca do serviço (arquivo em frontend/public/integrations/). Sem ela, o `icon`.
    logo = ""
    docs_url = ""
    fields: tuple[Field, ...] = ()
    purposes: tuple[Purpose, ...] = ()
    #: Dá para ter mais de uma por conta (duas contas do Asaas)?
    multiple = True
    #: Já faz algo no sistema ou só guarda a configuração (o trabalho vem depois)?
    available = True
    #: O tipo possui endpoint público para receber eventos.
    supports_webhooks = False
    #: Campo secreto usado para autenticar as entregas.
    webhook_secret_field = ""

    def __init__(self, integration=None, values=None):
        self.integration = integration
        self.values = dict(values if values is not None else (integration.fields if integration else {}))

    # --- leitura -----------------------------------------------------------------------------------
    def get(self, name, default=None):
        value = self.values.get(name)
        if value in (None, ""):
            spec = self.field(name)
            return spec.default if spec and spec.default is not None else default
        return value

    def does(self, purpose):
        return bool(self.integration and purpose in (self.integration.purposes or []))

    @property
    def webhook_ready(self):
        return bool(self.supports_webhooks and self.webhook_secret_field and self.get(self.webhook_secret_field))

    def verify_webhook(self, raw_body, headers, payload):
        """Valida a origem da entrega. Cada provedor implementa sua assinatura/token."""
        return False

    def webhook_event_id(self, headers, payload, raw_body=b""):
        return ""

    def webhook_event_type(self, headers, payload):
        return ""

    def webhook_headers(self, headers):
        """Metadados seguros para auditoria; nunca persiste o segredo recebido."""
        return {}

    @classmethod
    def field(cls, name):
        return next((f for f in cls.fields if f.name == name), None)

    @classmethod
    def describe(cls):
        return {"key": cls.key, "label": cls.label, "description": cls.description, "category": cls.category,
                "icon": cls.icon, "logo": cls.logo or None, "docs_url": cls.docs_url, "multiple": cls.multiple, "available": cls.available,
                "testable": cls.test is not IntegrationType.test,
                "fields": [f.as_dict() for f in cls.fields], "purposes": [p.as_dict() for p in cls.purposes]}

    # --- gravação ----------------------------------------------------------------------------------
    @classmethod
    def clean(cls, incoming, current=None):
        """Os valores que vão para o banco. Segredo em branco (ou a máscara) mantém o guardado; campo que
        não é do tipo é descartado; obrigatório que vale (`when`) e está vazio vira erro com o rótulo."""
        current = current or {}
        incoming = incoming if isinstance(incoming, dict) else {}
        out, errors = {}, {}
        for spec in cls.fields:
            raw = incoming.get(spec.name, current.get(spec.name) if spec.name not in incoming else None)
            if spec.secret and raw in (None, "", MASK):
                raw = current.get(spec.name, "")
            try:
                out[spec.name] = cls._coerce(spec, raw)
            except ValueError as error:
                errors[spec.name] = str(error)
        for spec in cls.fields:
            if spec.required and spec.applies(out) and out.get(spec.name) in (None, "") and spec.name not in errors:
                errors[spec.name] = f"Informe {spec.label}."
        if errors:
            raise ValidationError(errors)
        return cls.normalize(out)

    @staticmethod
    def _coerce(spec, raw):
        if raw is None or raw == "":
            if spec.type == "boolean":
                return bool(spec.default)
            return "" if spec.default is None else spec.default
        if spec.type == "boolean":
            return raw in (True, "true", "1", 1, "on")
        if spec.type == "number":
            try:
                return str(Decimal(str(raw)))
            except InvalidOperation:
                raise ValueError(f"{spec.label}: número inválido.") from None
        value = str(raw).strip()
        if spec.type == "select" and spec.options and value not in {v for v, _ in spec.options}:
            raise ValueError(f"{spec.label}: opção inválida.")
        if spec.type == "url" and not value.startswith(("http://", "https://")):
            raise ValueError(f"{spec.label}: o endereço começa com https://.")
        return value

    @classmethod
    def normalize(cls, values):
        """Ajuste final do tipo (ex.: o domínio da Shopify sem https://). Padrão: nada."""
        return values

    @classmethod
    def clean_purposes(cls, purposes):
        allowed = {p.key for p in cls.purposes}
        return [p for p in dict.fromkeys(purposes or []) if p in allowed]

    @classmethod
    def public(cls, values):
        """O que a tela recebe: segredo guardado vira a máscara (nunca o valor)."""
        values = values or {}
        out = {}
        for spec in cls.fields:
            value = values.get(spec.name, "")
            out[spec.name] = (MASK if value else "") if spec.secret else value
        return out

    # --- conexão -----------------------------------------------------------------------------------
    def test(self) -> CheckResult:
        """Confere a conexão com o serviço. Sem teste: a configuração só é guardada."""
        return CheckResult(True, "Configuração guardada (este tipo não tem teste de conexão).")


REGISTRY: dict[str, type[IntegrationType]] = {}


def register(cls):
    if not cls.key or cls.key in REGISTRY:
        raise ValueError(f"Tipo de integração sem chave ou repetido: {cls.key!r}")
    REGISTRY[cls.key] = cls
    return cls


def get_type(key):
    try:
        return REGISTRY[key]
    except KeyError:
        raise BusinessError(f"Tipo de integração desconhecido: {key}.", code="integration_kind") from None


def kind_choices():
    return [(key, cls.label) for key, cls in REGISTRY.items()]
