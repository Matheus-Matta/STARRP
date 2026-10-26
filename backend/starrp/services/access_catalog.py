"""Catálogo de permissões e cargos padrão. Fonte única: seed e documentação.

Convenção: `<área>.view` (leitura) e `<área>.manage` (escrita) — é o que o
`HasViewPermission` exige a partir do `permission_code` da view. Ações
sensíveis têm código próprio.
"""
from decimal import Decimal

AREAS = [
    ("catalog", "Produtos e catálogo", "base"),
    ("partners", "Clientes e fornecedores", "base"),
    ("promotions", "Promoções e cupons", "base"),
    ("sales", "Vendas", "base"),
    ("cash", "Caixa", "base"),
    ("reports", "Relatórios", "base"),
    ("commissions", "Comissões", "base"),
    ("users", "Usuários e cargos", "base"),
    ("settings", "Filiais, terminais e configurações", "base"),
    ("devices", "Impressoras e balanças", "base"),
    ("stock", "Estoque", "stock"),
    ("logistics", "Logística e entrega", "base"),
    ("finance", "Financeiro", "finance"),
    ("fiscal", "Fiscal", "fiscal"),
    ("inbound_nfe", "NF-e de entrada", "inbound_nfe"),
    ("assets", "Patrimônio", "assets"),
    ("sync", "Sincronização", "sync"),
]

SPECIAL = [
    ("sales.cancel", "Cancelar venda concluída", "sales"),
    ("sales.cancel_item", "Cancelar item da venda", "sales"),
    ("sales.discount", "Autorizar desconto acima do limite", "sales"),
    ("sales.price_override", "Alterar preço no PDV", "sales"),
    ("sales.return", "Fazer troca/devolução", "sales"),
    ("cash.approve", "Aprovar sangria e fechamento com diferença", "cash"),
]


def permission_rows():
    rows = []
    for order, (area, label, module) in enumerate(AREAS):
        rows.append((f"{area}.view", f"{label}: ver", area, module, order * 10))
        rows.append((f"{area}.manage", f"{label}: gerenciar", area, module, order * 10 + 1))
    modules = {area: module for area, _label, module in AREAS}
    for index, (code, label, area) in enumerate(SPECIAL):
        rows.append((code, label, area, modules[area], 500 + index))
    return rows


def _all(*areas):
    return [f"{area}.{kind}" for area in areas for kind in ("view", "manage")]


def _views(*areas):
    return [f"{area}.view" for area in areas]


ALL_AREAS = [area for area, _label, _module in AREAS]
SPECIAL_CODES = [code for code, _l, _a in SPECIAL]

# Cargos FIXOS do sistema (criados e sincronizados em toda conta: `provisioning.ensure_system_roles`).
# Um usuário tem o cargo principal e pode somar outros (`UserProfile.extra_roles`): as permissões
# se somam e valem o maior nível e o maior desconto. `area` agrupa na tela; `rank` = quem aprova quem.
SYSTEM_ROLES = [
    # ── Direção ───────────────────────────────────────────────────────────
    {"code": "admin", "name": "Administrador", "area": "Direção", "rank": 100, "is_account_admin": True,
     "max_discount_percent": Decimal("100"), "permissions": [],
     "description": "Tudo, em todas as filiais, inclusive usuários, cargos e configurações da conta."},
    {"code": "director", "name": "Diretor", "area": "Direção", "rank": 95, "max_discount_percent": Decimal("50"),
     "permissions": _all(*[a for a in ALL_AREAS if a != "sync"]) + SPECIAL_CODES,
     "description": "Toda a operação de todas as áreas e todas as aprovações; sem a sincronização técnica."},
    {"code": "manager", "name": "Gerente de filial", "area": "Direção", "rank": 80, "max_discount_percent": Decimal("30"),
     # `users`: o gerente cadastra a equipe das lojas DELE (o serializer barra escalada).
     "permissions": _all("catalog", "partners", "promotions", "sales", "cash", "reports", "commissions", "stock",
                         "logistics", "devices", "finance", "fiscal", "inbound_nfe", "assets", "users") + SPECIAL_CODES,
     "description": "A filial inteira: vendas, caixa, estoque, entrega, financeiro e a equipe; aprova tudo."},
    {"code": "supervisor", "name": "Supervisor de filial", "area": "Direção", "rank": 70,
     "max_discount_percent": Decimal("15"),
     "permissions": _all("sales", "cash", "partners", "logistics") + _views("catalog", "promotions", "reports",
                                                                          "commissions", "stock")
     + ["sales.cancel_item", "sales.discount", "sales.return", "cash.approve"],
     "description": "Toca o salão e os caixas: aprova desconto, retirada de item, troca e sangria."},
    # ── Vendas ────────────────────────────────────────────────────────────
    {"code": "sales_lead", "name": "Líder de vendas", "area": "Vendas", "rank": 60, "max_discount_percent": Decimal("10"),
     "permissions": _all("sales", "partners") + _views("catalog", "promotions", "reports", "commissions", "logistics")
     + ["sales.discount", "sales.cancel_item", "sales.return"],
     "description": "Equipe de vendas: pedidos, clientes, comissões e descontos maiores."},
    {"code": "cashier", "name": "Operador de caixa", "area": "Vendas", "rank": 50, "max_discount_percent": Decimal("5"),
     "permissions": ["catalog.view", "devices.view", "promotions.view", "logistics.view", *_all("partners", "sales", "cash")],
     "description": "PDV no modo caixa: cobra, guarda e retoma pedidos, abre e fecha o caixa."},
    {"code": "seller", "name": "Vendedor", "area": "Vendas", "rank": 30, "max_discount_percent": Decimal("5"),
     "permissions": ["catalog.view", "promotions.view", "partners.view", "partners.manage", "sales.view",
                     "sales.manage", "commissions.view"],
     "description": "PDV no modo vendedor: monta o pedido e envia ao caixa; não cobra."},
    # ── Estoque e compras ─────────────────────────────────────────────────
    {"code": "stock_lead", "name": "Coordenador de estoque", "area": "Estoque e compras", "rank": 60,
     "max_discount_percent": Decimal("0"),
     "permissions": _all("stock", "inbound_nfe", "catalog") + _views("partners", "reports", "logistics", "devices"),
     "description": "Estoque, inventário, notas de entrada e o cadastro de produtos."},
    {"code": "comprador", "name": "Comprador", "area": "Estoque e compras", "rank": 50, "max_discount_percent": Decimal("0"),
     "permissions": _all("inbound_nfe", "partners", "catalog") + _views("stock", "reports", "finance"),
     "description": "Fornecedores, notas de entrada (compra) e cadastro de produtos e preços."},
    {"code": "stockist", "name": "Estoquista", "area": "Estoque e compras", "rank": 40, "max_discount_percent": Decimal("0"),
     "permissions": ["catalog.view", "catalog.manage", "partners.view", "devices.view", *_all("stock", "inbound_nfe")],
     "description": "Recebe mercadoria, confere notas, movimenta e etiqueta o estoque."},
    # ── Logística ─────────────────────────────────────────────────────────
    {"code": "logistics_lead", "name": "Coordenador de logística", "area": "Logística", "rank": 60,
     "max_discount_percent": Decimal("0"),
     "permissions": _all("logistics", "stock") + _views("sales", "partners", "reports", "catalog"),
     "description": "Tabelas de frete, depósitos, endereços e todo o andamento das entregas."},
    {"code": "logistics", "name": "Auxiliar de logística", "area": "Logística", "rank": 35, "max_discount_percent": Decimal("0"),
     "permissions": _all("logistics") + _views("sales", "partners", "stock", "catalog"),
     "description": "Separa, despacha e dá baixa nas entregas (separado, saiu, entregue)."},
    # ── Financeiro ────────────────────────────────────────────────────────
    {"code": "financeiro", "name": "Coordenador financeiro", "area": "Financeiro", "rank": 70,
     "max_discount_percent": Decimal("0"),
     "permissions": _all("finance", "cash", "commissions", "reports", "partners") + _views("sales", "fiscal")
     + ["cash.approve"],
     "description": "Contas a pagar e receber, turnos de caixa, comissões e aprovação de fechamento."},
    {"code": "finance_assistant", "name": "Assistente financeiro", "area": "Financeiro", "rank": 40,
     "max_discount_percent": Decimal("0"),
     "permissions": _all("finance") + _views("cash", "partners", "sales", "reports"),
     "description": "Lança e baixa títulos, concilia lançamentos."},
    # ── Fiscal ────────────────────────────────────────────────────────────
    {"code": "fiscal", "name": "Analista fiscal", "area": "Fiscal", "rank": 50, "max_discount_percent": Decimal("0"),
     "permissions": _all("fiscal", "inbound_nfe") + ["catalog.view", "catalog.manage"] + _views("partners", "sales", "reports"),
     "description": "Notas emitidas e de entrada, dados e perfis fiscais, NCM/CEST dos produtos."},
    # ── Marketing, patrimônio, TI e auditoria ─────────────────────────────
    {"code": "marketing", "name": "Marketing", "area": "Marketing", "rank": 40, "max_discount_percent": Decimal("0"),
     "permissions": _all("promotions", "catalog") + _views("partners", "reports", "sales"),
     "description": "Promoções, cupons, descrições, fotos e SEO dos produtos."},
    {"code": "assets", "name": "Patrimônio", "area": "Patrimônio", "rank": 40, "max_discount_percent": Decimal("0"),
     "permissions": _all("assets") + _views("stock", "finance"),
     "description": "Bens da empresa: cadastro, movimentação e baixa."},
    {"code": "it", "name": "Suporte de TI", "area": "TI", "rank": 45, "max_discount_percent": Decimal("0"),
     "permissions": _all("users", "settings", "devices", "sync"),
     "description": "Usuários, filiais, terminais, impressoras, balanças e a sincronização."},
    {"code": "auditor", "name": "Auditor (só consulta)", "area": "Auditoria", "rank": 20, "max_discount_percent": Decimal("0"),
     "permissions": _views(*ALL_AREAS),
     "description": "Vê tudo e não altera nada."},
]
