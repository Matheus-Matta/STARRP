"""O que a API oferece, lido do próprio OpenAPI (drf-spectacular), para a Cosmos se achar.

O modelo não decora endpoints: ele procura (`search`) e pede os campos de um (`describe`).
Tudo sai recortado pela permissão do usuário — a mesma regra do `HasViewPermission` —,
então a Cosmos nem cogita o que ele não pode fazer.

    search(actor, "produto")  →  ["GET /catalog/products/ — Produto com as variantes...", ...]
    describe(actor, "POST", "/catalog/products/")  →  campos, obrigatórios, opções
"""
import re
from functools import lru_cache

from django.urls import Resolver404, resolve
from rest_framework.permissions import SAFE_METHODS

from starrp.core.permissions import has_permission_code, is_account_admin
from starrp.models.platform import MODULE_BASE
from starrp.services.cosmos.bridge import API_PREFIX, blocked, normalize

DUMMY = "00000000-0000-0000-0000-000000000000"
PARAM = re.compile(r"\{[^}]+\}")
MAX_DEPTH = 3


@lru_cache(maxsize=1)
def schema():
    from drf_spectacular.drainage import GENERATOR_STATS
    from drf_spectacular.generators import SchemaGenerator

    # O gerador reclama das APIViews sem serializer (relatórios, PDV); para a Cosmos, tanto faz.
    with GENERATOR_STATS.silence():
        return SchemaGenerator().get_schema(request=None, public=True)


@lru_cache(maxsize=1)
def operations():
    """[(método, caminho sem /api/v1, operação)] de toda a API."""
    out = []
    for raw_path, item in schema()["paths"].items():
        if not raw_path.startswith(API_PREFIX):
            continue
        path = "/" + raw_path[len(API_PREFIX):]
        if blocked(path):
            continue
        for method, op in item.items():
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.append((method.upper(), path, op))
    return out


def _view_rule(method, path):
    """(código de permissão, módulo) que a view exige para este método — ou (None, base)."""
    try:
        match = resolve(API_PREFIX + PARAM.sub(DUMMY, normalize(path)))
    except Resolver404:
        return None, MODULE_BASE
    cls = getattr(match.func, "cls", None)
    if cls is None:
        return None, MODULE_BASE
    actions = getattr(match.func, "actions", None) or {}
    current = actions.get(method.lower())
    codes = getattr(cls, "action_permissions", {}) or {}
    module = getattr(cls, "required_module", MODULE_BASE)
    if current in codes:
        return codes[current], module
    base = getattr(cls, "permission_code", None)
    if base is None:
        return None, module
    return (f"{base}.view" if method in SAFE_METHODS else f"{base}.manage"), module


def _system_data(method, path):
    """Criar/excluir em cadastro FIXO do sistema (formas de pagamento, cargos...): só o suporte."""
    from starrp.core.viewsets import SystemDataViewSet

    try:
        match = resolve(API_PREFIX + PARAM.sub(DUMMY, normalize(path)))
    except Resolver404:
        return False
    cls = getattr(match.func, "cls", None)
    action = (getattr(match.func, "actions", None) or {}).get(method.lower())
    return bool(cls and issubclass(cls, SystemDataViewSet) and action in ("create", "destroy"))


def allowed(actor, method, path):
    # Nem aparece para a Cosmos (ela não tenta): a view recusaria de qualquer jeito.
    if method != "GET" and not actor.user.is_superuser and _system_data(method, path):
        return False
    code, module = _view_rule(method, path)
    if module != MODULE_BASE and not (actor.user.is_superuser or actor.account.has_module(module)):
        return False
    return code is None or is_account_admin(actor.user) or has_permission_code(actor.user, code)


def _summary(op):
    text = (op.get("summary") or op.get("description") or "").strip().split("\n")[0]
    return text[:140]


def search(actor, query="", writes=True, limit=40):
    """Endpoints que o usuário pode usar e que casam com `query` (palavras, em qualquer ordem)."""
    words = [w for w in re.split(r"\s+", (query or "").lower()) if w]
    rows = []
    for method, path, op in operations():
        if not writes and method != "GET":
            continue
        text = f"{method} {path} {_summary(op)} {op.get('operationId', '')}".lower()
        if words and not all(w in text for w in words):
            continue
        if not allowed(actor, method, path):
            continue
        rows.append(f"{method} {path}" + (f" — {_summary(op)}" if _summary(op) else ""))
        if len(rows) >= limit:
            rows.append("… (refine a busca para ver mais)")
            break
    return rows


def _pattern(template):
    """`/catalog/products/{id}/` → casa com o modelo E com o endereço real (`/catalog/products/<uuid>/`)."""
    parts = [re.escape(part) for part in PARAM.split(template)]
    return re.compile("^" + "[^/]+".join(parts) + "$")


def find(method, path):
    """(modelo do endereço, operação) do OpenAPI, ou (None, None) se o método/endereço não existe."""
    wanted = "/" + normalize(path)
    for m, p, op in operations():
        if m == method and _pattern(p).match(wanted):
            return p, op
    return None, None


def _ref(node):
    return node["$ref"].rsplit("/", 1)[-1]


def _type_of(node, components, depth, indent):
    if "$ref" in node:
        name = _ref(node)
        target = components.get(name, {})
        if "enum" in target or depth >= MAX_DEPTH or target.get("type") not in (None, "object"):
            return _type_of(target, components, depth, indent) if "properties" not in target else name
        return "{\n" + _fields(target, components, depth + 1, indent + "  ") + indent + "}"
    for key in ("allOf", "oneOf", "anyOf"):
        if key in node:
            parts = [p for p in node[key] if p.get("type") != "null" and _ref_name(p) not in {"BlankEnum", "NullEnum"}]
            if parts:
                return _type_of(parts[0], components, depth, indent) + (" | null" if node.get("nullable") else "")
    if "enum" in node:
        values = [v for v in node["enum"] if v not in ("", None)]
        return "um de: " + ", ".join(map(str, values[:25]))
    kind = node.get("type", "any")
    if kind == "array":
        return "lista de " + _type_of(node.get("items", {}), components, depth, indent)
    if kind == "object" and "properties" in node:
        return "{\n" + _fields(node, components, depth + 1, indent + "  ") + indent + "}"
    if node.get("format") == "decimal":
        text = 'decimal em texto, ex.: "49.90"'
    else:
        extra = [node["format"]] if node.get("format") else []
        if node.get("maxLength"):
            extra.append(f"até {node['maxLength']}")
        text = kind + (f" ({', '.join(extra)})" if extra else "")
    return text + (" | null" if node.get("nullable") else "")


def _ref_name(node):
    return _ref(node) if "$ref" in node else ""


def _fields(node, components, depth, indent):
    required = set(node.get("required", []))
    lines = []
    for name, prop in node.get("properties", {}).items():
        if prop.get("readOnly"):
            continue
        desc = (prop.get("description") or "").strip().split("\n")[0][:120]
        mark = "*" if name in required else ""
        lines.append(f"{indent}{name}{mark}: {_type_of(prop, components, depth, indent)}" + (f" — {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


def _read_fields(node, components):
    if "$ref" in node:
        node = components.get(_ref(node), {})
    props = node.get("properties", {})
    if "results" in props:  # lista paginada: os campos de cada linha
        return _read_fields(props["results"].get("items", {}), components)
    return list(props)


def describe(actor, method, path):
    """Texto com o que o endpoint recebe (filtros e corpo) e devolve. `*` = obrigatório."""
    method = method.upper()
    found, op = find(method, path)
    if op is None:
        return f"Não existe {method} {path}. Use a busca de endpoints."
    if not allowed(actor, method, found):
        return f"Você não tem permissão para {method} {found}."
    components = schema()["components"]["schemas"]
    out = [f"{method} {found}", (op.get("description") or "").strip()[:600]]
    params = [p for p in op.get("parameters", []) if p.get("in") == "query"]
    if params:
        out.append("Filtros (query):")
        for p in params[:40]:
            kind = _type_of(p.get("schema", {}), components, MAX_DEPTH, "")
            out.append(f"  {p['name']}: {kind}" + (f" — {p['description'][:90]}" if p.get("description") else ""))
    body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
    if body and method in {"POST", "PUT", "PATCH"}:
        target = components.get(_ref(body), body) if "$ref" in body else body
        out.append("Corpo JSON (* = obrigatório" + ("; no PATCH mande só o que muda" if method == "PATCH" else "") + "):")
        out.append(_fields(target, components, 1, "  ").rstrip())
    response = (op.get("responses", {}).get("200") or op.get("responses", {}).get("201") or {})
    resp_schema = response.get("content", {}).get("application/json", {}).get("schema")
    if resp_schema:
        out.append("Resposta (campos): " + ", ".join(_read_fields(resp_schema, components)[:60]))
    return "\n".join(line for line in out if line)
