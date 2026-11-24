"""Catálogo de permissões e cargos padrão. Fonte única: seed e documentação.

Convenção CRUD: `<área>.view/create/update/delete`. O código legado
`<área>.manage` representa criar + editar + excluir e protege ações de domínio.
Ações sensíveis têm código próprio.
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
    ("fiscal", "Fiscal", "base"),
    ("inbound_nfe", "NF-e de entrada", "inbound_nfe"),
    ("assets", "Patrimônio", "assets"),
    ("sync", "Sincronização", "sync"),
]

SPECIAL = [
    # Recursos com dois níveis: o acesso total sempre inclui o acesso normal.
    ("cosmos.access", "Conversa com IA — acesso normal", "cosmos", "cosmos"),
    ("cosmos.full", "Conversa com IA — acesso total", "cosmos", "cosmos"),
    ("pricing.access", "Precificação — acesso normal", "pricing", "pricing"),
    ("pricing.full", "Precificação — acesso total", "pricing", "pricing"),
    ("seo.access", "Análise SEO — acesso normal", "seo", "seo"),
    ("seo.full", "Análise SEO — acesso total", "seo", "seo"),
    # Sem ela, quem vê vendas vê só as PRÓPRIAS (vendeu, registrou ou guardou): lista, consultas e relatórios.
    ("sales.view_all", "Ver as vendas de toda a equipe (sem ela, só as próprias)", "sales", "base"),
    ("sales.cancel", "Cancelar venda concluída", "sales", "base"),
    ("sales.cancel_item", "Cancelar item da venda", "sales", "base"),
    ("sales.discount", "Autorizar desconto acima do limite", "sales", "base"),
    ("sales.price_override", "Alterar preço no PDV", "sales", "base"),
    ("sales.return", "Fazer troca/devolução", "sales", "base"),
    ("partners.credit", "Conceder crédito manual na carteira do cliente", "partners", "base"),
    ("sales.edit_delivery", "Alterar a entrega de venda concluída", "sales", "base"),
    ("sales.edit_payment", "Trocar a forma de pagamento de venda concluída", "sales", "base"),
    ("cash.approve", "Aprovar sangria e fechamento com diferença", "cash", "base"),
    # Sem ela, custo e margem somem de produto, venda, precificação, relatórios e da Cosmos (core/costs.py).
    ("catalog.view_costs", "Ver custo e margem dos produtos e das vendas", "catalog", "base"),
    ("cosmos.supervise", "Receber da Cosmos os alertas sobre a equipe", "cosmos", "cosmos"),
]


def permission_rows():
    rows = []
    for order, (area, label, module) in enumerate(AREAS):
        rows.append((f"{area}.view", f"{label}: ver", area, module, order * 10))
        rows.append((f"{area}.create", f"{label}: criar", area, module, order * 10 + 1))
        rows.append((f"{area}.update", f"{label}: editar", area, module, order * 10 + 2))
        rows.append((f"{area}.delete", f"{label}: excluir", area, module, order * 10 + 3))
        # Compatibilidade para ações que não são CRUD (aprovar, sincronizar, processar...).
        rows.append((f"{area}.manage", f"{label}: executar ações", area, module, order * 10 + 4))
    for index, (code, label, area, module) in enumerate(SPECIAL):
        rows.append((code, label, area, module, 500 + index))
    return rows


def _all(*areas):
    return [f"{area}.{kind}" for area in areas for kind in ("view", "create", "update", "delete", "manage")]


def _views(*areas):
    return [f"{area}.view" for area in areas]


ALL_AREAS = [area for area, _label, _module in AREAS]
SPECIAL_CODES = [code for code, _label, _area, _module in SPECIAL]
DIRECTOR_ONLY_CODES = {"partners.credit"}

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
                         "logistics", "devices", "finance", "fiscal", "inbound_nfe", "assets", "users")
     + [code for code in SPECIAL_CODES if code not in DIRECTOR_ONLY_CODES],
     "description": "A filial inteira: vendas, caixa, estoque, entrega, financeiro e a equipe; aprova tudo."},
    {"code": "supervisor", "name": "Supervisor de filial", "area": "Direção", "rank": 70,
     "max_discount_percent": Decimal("15"),
     "permissions": _all("sales", "cash", "partners", "logistics") + _views("catalog", "promotions", "reports",
                                                                          "commissions", "stock")
     + ["sales.cancel_item", "sales.discount", "sales.return", "cash.approve", "cosmos.access", "cosmos.supervise"],
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
     "permissions": ["catalog.view", "promotions.view", *_all("partners", "sales"), "commissions.view"],
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
     "permissions": [*_all("catalog"), "partners.view", "devices.view", *_all("stock", "inbound_nfe")],
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
     "permissions": _all("fiscal", "inbound_nfe", "catalog") + _views("partners", "sales", "reports"),
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
     "permissions": _views(*ALL_AREAS) + ["cosmos.access"],
     "description": "Vê tudo e não altera nada."},
]

# Os coordenadores de área também conversam com a Cosmos (consulta, relatório e cadastro com
# confirmação); os demais ganham pelo perfil (`extra_permissions`), se o administrador quiser.
COSMOS_ROLES = {"sales_lead", "stock_lead", "logistics_lead", "financeiro"}
for _role in SYSTEM_ROLES:
    if _role["code"] in COSMOS_ROLES:
        _role["permissions"] = [*_role["permissions"], "cosmos.access", "cosmos.full"]


# Mantém o acesso que os cargos já tinham quando Precificação e SEO acompanhavam as permissões do catálogo,
# mas daqui em diante cada recurso pode ser ajustado separadamente na matriz.
for _role in SYSTEM_ROLES:
    if "catalog.view" in _role["permissions"]:
        _role["permissions"] = [*_role["permissions"], "pricing.access", "seo.access"]
    if "catalog.manage" in _role["permissions"]:
        _role["permissions"] = [*_role["permissions"], "pricing.full", "seo.full"]


# Quem vê vendas vê as da equipe toda — menos o Vendedor, que vê só as próprias (`sales.view_all`).
OWN_SALES_ONLY_ROLES = {"seller"}
for _role in SYSTEM_ROLES:
    if (_role["code"] not in OWN_SALES_ONLY_ROLES and "sales.view" in _role["permissions"]
            and "sales.view_all" not in _role["permissions"]):
        _role["permissions"] = [*_role["permissions"], "sales.view_all"]


# Custo e margem (`catalog.view_costs`): diretor e gerente já têm (SPECIAL_CODES); estes também.
# Caixa, vendedor e líder de vendas, logística, patrimônio e TI não veem quanto a loja paga nem ganha.
COST_ROLES = {"supervisor", "stock_lead", "comprador", "stockist", "financeiro", "finance_assistant", "fiscal",
              "marketing", "auditor"}
for _role in SYSTEM_ROLES:
    if _role["code"] in COST_ROLES and "catalog.view_costs" not in _role["permissions"]:
        _role["permissions"] = [*_role["permissions"], "catalog.view_costs"]
