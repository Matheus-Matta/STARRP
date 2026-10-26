"""Dados de demonstração: pelo menos 10 registros em cada cadastro, coerentes entre si.

    python manage.py seed_demo                  # conta "loja-demo" (npm run setup -- --demo)
    python manage.py seed_demo --account outra  # outra conta

Tudo passa pela MESMA API das telas (com o admin da conta), então as regras valem:
estoque entra por documento confirmado, venda passa pelo caixa e pelo checkout,
conta a pagar nasce com parcelas, nota de entrada é importada do XML. No fim, as
vendas e os turnos são espalhados pelos últimos 30 dias para os painéis terem história.

Rodar de novo não duplica: se a demo já existe (marca "Aurora"), o comando avisa e sai.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from starrp.models import (
    Account, Brand, CashRegister, CashSession, Invoice, InvoiceItem, PaymentMethod, Sale, Store, UserProfile,
)
from starrp.models.platform import Module
from starrp.services import fiscal_data, provisioning
from starrp.services.barcodes import ean_check_digit_ok

random.seed(42)
TODAY = timezone.localdate()


# ── Documentos e códigos válidos (dígitos verificadores de verdade) ──────────
def ean13(body12):
    return next(body12 + d for d in "0123456789" if ean_check_digit_ok(body12 + d))


def _digit(numbers, weights):
    rest = sum(n * w for n, w in zip(numbers, weights, strict=False)) % 11
    return 0 if rest < 2 else 11 - rest


def cpf(seed):
    base = [int(c) for c in f"{(seed * 7919) % 10 ** 9:09d}"]
    base.append(_digit(base, range(10, 1, -1)))
    base.append(_digit(base, range(11, 1, -1)))
    return "".join(map(str, base))


def cnpj(seed):
    base = [int(c) for c in f"{(seed * 104729) % 10 ** 8:08d}0001"]
    base.append(_digit(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    base.append(_digit(base, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    return "".join(map(str, base))


def money(value):
    return f"{Decimal(value):.2f}"


class Api:
    """Cliente da API como o admin da conta, na loja `store`. Erro vira exceção com a mensagem."""

    def __init__(self, user, store):
        self.client = APIClient()
        self.user, self.store = user, store
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
                                HTTP_X_STORE_ID=str(store.pk))

    def at(self, store):
        return Api(self.user, store)

    def call(self, method, path, body=None, **kwargs):
        response = getattr(self.client, method)(f"/api/v1{path}", body, format=kwargs.pop("format", "json"),
                                                HTTP_HOST="localhost", **kwargs)
        if response.status_code >= 400:
            raise CommandError(f"{method.upper()} {path} → {response.status_code}: {response.content[:400]!r}")
        return response.json() if response.content else None

    def post(self, path, body=None, **kw):
        return self.call("post", path, body or {}, **kw)

    def get(self, path):
        return self.call("get", path)

    def patch(self, path, body):
        return self.call("patch", path, body)


ADDRESSES = [
    [{"label": "Casa", "zip_code": "01310100", "street": "Avenida Paulista", "number": "1578", "complement": "Apto 82",
      "district": "Bela Vista", "city": "São Paulo", "state": "SP", "reference": "Em frente ao MASP"}],
    [{"label": "Casa", "zip_code": "04538133", "street": "Avenida Brigadeiro Faria Lima", "number": "3477",
      "district": "Itaim Bibi", "city": "São Paulo", "state": "SP"}],
    [{"label": "Casa", "zip_code": "03310000", "street": "Rua Itapura", "number": "310", "district": "Tatuapé",
      "city": "São Paulo", "state": "SP", "reference": "Portão azul"}],
    [{"label": "Casa", "zip_code": "09015000", "street": "Rua das Figueiras", "number": "1200", "complement": "Casa 2",
      "district": "Jardim", "city": "Santo André", "state": "SP"}],
    [{"label": "Casa", "zip_code": "04094050", "street": "Avenida Pedro Álvares Cabral", "number": "s/n",
      "district": "Vila Mariana", "city": "São Paulo", "state": "SP", "reference": "Portão 10 do parque"}],
]
ADDRESSES_WORK = [{"label": "Trabalho", "zip_code": "01001000", "street": "Praça da Sé", "number": "108",
                   "complement": "Sala 4", "district": "Sé", "city": "São Paulo", "state": "SP"}]


class Command(BaseCommand):
    help = "Popula a conta de demonstração com pelo menos 10 registros por cadastro."

    def add_arguments(self, parser):
        parser.add_argument("--account", default="loja-demo", help="Slug da conta (padrão: loja-demo).")
        parser.add_argument("--dry-run", action="store_true", help="Cria tudo e desfaz no fim (para testar).")

    def handle(self, *args, **options):
        account = Account.objects.filter(slug=options["account"]).first()
        if account is None:
            raise CommandError(f"Conta {options['account']} não existe. Rode create_account antes.")
        if Brand.all_objects.filter(account=account, name="Aurora").exists():
            self.stdout.write(self.style.WARNING("Demo já populada nesta conta (marca Aurora existe). Nada a fazer."))
            return
        # A demo mostra tudo: liga todos os módulos opcionais (estoque, WMS, financeiro, fiscal...).
        account.extra_modules = [m.value for m in Module if m != Module.BASE]
        account.save(update_fields=["extra_modules", "updated_at"])
        profile = UserProfile.all_objects.filter(account=account, role__code="admin").select_related("user").first()
        self.main = Store.all_objects.filter(account=account, deleted_at__isnull=True).order_by("created_at").first()
        self.account, self.admin = account, profile.user
        with transaction.atomic():
            self.stores_and_fiscal()
            self.api = Api(self.admin, self.main)
            self.people()
            self.catalog()
            self.delivery_and_specs()
            self.stock()
            self.promotions()
            self.sales()
            self.finance()
            self.fiscal_documents()
            self.backdate()
            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("--dry-run: tudo certo, nada foi gravado."))
                return
        # Cupom, desconto e promoção (relatórios de Promoções) e depois avaliações e entregas.
        call_command("seed_promotions", account=options["account"], stdout=self.stdout)
        call_command("seed_reviews", account=options["account"], stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Demo pronta: lojas, catálogo, estoque, vendas, financeiro e fiscal."))

    def log(self, text):
        self.stdout.write(f"  · {text}")

    # ── Lojas (10) e dados fiscais ───────────────────────────────────────────
    def stores_and_fiscal(self):
        city = [("São Paulo", "SP", "3550308", "01001000"), ("Campinas", "SP", "3509502", "13010000"),
                ("Rio de Janeiro", "RJ", "3304557", "20010000"), ("Belo Horizonte", "MG", "3106200", "30110000"),
                ("Curitiba", "PR", "4106902", "80010000"), ("Porto Alegre", "RS", "4314902", "90010000"),
                ("Florianópolis", "SC", "4205407", "88010000"), ("Salvador", "BA", "2927408", "40010000"),
                ("Recife", "PE", "2611606", "50010000"), ("Goiânia", "GO", "5208707", "74003010")]
        names = ["Matriz Centro", "Campinas Shopping", "Rio Copacabana", "BH Savassi", "Curitiba Batel",
                 "Porto Alegre Moinhos", "Floripa Beira-Mar", "Salvador Barra", "Recife Boa Viagem", "Goiânia Setor Bueno"]
        if not self.main.cnpj:
            Store.all_objects.filter(pk=self.main.pk).update(
                cnpj=cnpj(1), legal_name="Loja Demo Comércio LTDA", state="SP", city="São Paulo", city_ibge="3550308",
                zip_code="01001000", street="Praça da Sé", number="100", district="Sé")
            self.main.refresh_from_db()
        fiscal_data.from_store(self.main)
        existing = Store.all_objects.filter(account=self.account, deleted_at__isnull=True).count()
        for index in range(existing, 10):
            town, uf, ibge, cep = city[index]
            store = provisioning.create_store(
                self.account, f"Loja Demo {names[index]}", cnpj=cnpj(index + 1), legal_name=f"Loja Demo {town} LTDA",
                state=uf, city=town, city_ibge=ibge, zip_code=cep, street="Avenida Principal", number=str(100 + index),
                district="Centro", phone=f"11{3000_0000 + index:08d}", email=f"loja{index + 1}@lojademo.com.br")
            fiscal_data.from_store(store)
        self.stores = list(Store.all_objects.filter(account=self.account, deleted_at__isnull=True).order_by("created_at"))
        # Formas de pagamento além das fixas (o que só o suporte cria): cheque e transferência.
        for name in ("Cheque", "Transferência (TED/DOC)"):
            PaymentMethod.all_objects.get_or_create(account=self.account, name=name, deleted_at=None,
                                                    defaults={"kind": PaymentMethod.Kind.OTHER, "position": 20})
        self.log(f"{len(self.stores)} lojas com dados fiscais")

    # ── Pessoas: cargos, usuários, grupos, clientes, fornecedores ──────────────
    def people(self):
        api = self.api
        # Cargos são fixos (nascem com a conta): aqui só se usa. Um usuário pode somar cargos.
        roles = {r["code"]: r["id"] for r in api.get("/roles/?page_size=100")["results"]}
        extra = {"elisa": ["logistics"], "gabi": ["fiscal"], "fabio": ["logistics_lead"]}
        people = [("ana", "Ana", "Souza", "manager"), ("bruno", "Bruno", "Lima", "cashier"),
                  ("carla", "Carla", "Mendes", "seller"), ("diego", "Diego", "Rocha", "seller"),
                  ("elisa", "Elisa", "Prado", "stockist"), ("fabio", "Fábio", "Nunes", "supervisor"),
                  ("gabi", "Gabriela", "Alves", "financeiro"), ("hugo", "Hugo", "Teixeira", "comprador"),
                  ("iris", "Íris", "Campos", "fiscal"), ("joao", "João", "Pereira", "auditor")]
        for i, (username, first, last, role) in enumerate(people):
            body = {"username": username, "first_name": first, "last_name": last, "password": "senha123",
                    "extra_roles": [roles[c] for c in extra.get(username, [])],
                    "email": f"{username}@lojademo.com.br", "role": roles[role], "stores": [str(self.main.pk)],
                    "default_store": str(self.main.pk), "is_seller": role == "seller",
                    "seller_code": f"V{i + 1:02d}" if role == "seller" else "",
                    "commission_percent": "3.00" if role == "seller" else "0.00"}
            api.post("/users/", body)
        self.sellers = [p.user_id for p in UserProfile.all_objects.filter(account=self.account, is_seller=True)]
        colors = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#64748b"]
        groups = ["Clientes VIP", "Atacado", "Revendedores", "Funcionários", "Aniversariantes", "Primeira compra",
                  "Clube de vantagens", "Empresas", "Influenciadores", "Inativos há 90 dias"]
        self.groups = [api.post("/customers/groups/", {"name": g, "color": colors[i],
                                                       "description": f"Grupo de demonstração: {g.lower()}"})["id"]
                       for i, g in enumerate(groups)]
        first_names = ["Maria", "José", "Ana", "Pedro", "Juliana", "Lucas", "Fernanda", "Rafael", "Patrícia", "Marcos",
                       "Camila", "Thiago"]
        surnames = ["Silva", "Santos", "Oliveira", "Costa", "Ferreira", "Rodrigues", "Martins", "Gomes", "Ribeiro",
                    "Carvalho", "Almeida", "Barbosa"]
        self.customers = []
        for i, (first, last) in enumerate(zip(first_names, surnames, strict=False)):
            self.customers.append(api.post("/customers/", {
                "person_type": "F", "document": cpf(i + 11), "name": f"{first} {last}", "phone": f"119{8765_4300 + i:08d}",
                "email": f"{first.lower()}.{last.lower()}@email.com".replace("é", "e").replace("í", "i"),
                "groups": [self.groups[i % len(self.groups)]], "credit_limit": "1500.00" if i % 3 == 0 else "0.00",
                "birth_date": f"19{70 + i}-0{1 + i % 9}-1{i % 9}",
                # Trabalhamos com entrega: todo cliente da demo tem endereço (alguns, dois).
                "addresses": ADDRESSES[i % len(ADDRESSES)] + (ADDRESSES_WORK if i % 4 == 0 else [])}))
        suppliers = ["Distribuidora Aurora", "Têxtil Vento Sul", "Calçados Pé Leve", "Bebidas Gela Já",
                     "Laticínios Fazenda Real", "Móveis Casa Viva", "Utilidades Lar Doce", "Atacadão Bom Sabor",
                     "Eletro Tech Plus", "Confecções Urbano"]
        self.suppliers = [api.post("/suppliers/", {
            "person_type": "J", "document": cnpj(50 + i), "name": name, "legal_name": f"{name} LTDA",
            "phone": f"113{2000_0000 + i:07d}", "email": f"vendas@{name.split()[-1].lower()}.com.br",
            "contact_name": first_names[i], "state": "SP", "city": "São Paulo", "zip_code": "01310100",
            "street": "Avenida Paulista", "number": str(1000 + i)})["id"] for i, name in enumerate(suppliers)]
        self.log("cargos, 10 usuários, 10 grupos, 12 clientes e 10 fornecedores")

    # ── Catálogo: categorias em árvore, marcas, produtos (simples, grade, kit, serviço, peso) ──
    def catalog(self):
        api = self.api
        tree = {"Vestuário": ["Camisetas", "Calças", "Moda praia"], "Calçados": ["Tênis", "Sandálias"],
                "Bebidas": ["Refrigerantes", "Cervejas", "Águas"], "Mercearia": ["Frios", "Laticínios", "Doces"],
                "Casa": ["Móveis", "Utilidades"], "Serviços": []}
        self.categories = {}
        for parent, children in tree.items():
            top = api.post("/catalog/categories/", {"name": parent, "description": f"<p>Tudo de {parent.lower()}.</p>"})
            self.categories[parent] = top["id"]
            for position, child in enumerate(children):
                self.categories[child] = api.post("/catalog/categories/", {
                    "name": child, "parent": top["id"], "position": position})["id"]
        brands = ["Aurora", "Vento Sul", "Serra Azul", "Bom Sabor", "Casa Viva", "Pé Leve", "Mar Aberto", "Gela Já",
                  "Fazenda Real", "Lar Doce", "Urbano", "Tech Plus"]
        self.brands = {b: api.post("/catalog/brands/", {"name": b})["id"] for b in brands}

        self.variants = []  # (id, preço, controla estoque, lote?)
        seq = iter(range(1, 999))

        def simple(name, category, brand, price, ncm, *, ref=None, extra=None, desc=""):
            code = ean13(f"7891000{next(seq):05d}")
            body = {"name": name, "type": "simple", "category": self.categories[category], "brand": self.brands.get(brand),
                    "ncm": ncm, "reference": ref or "", "description": desc or f"<p>{name}. Produto de demonstração.</p>",
                    "variants": [{"sku": ref or "", "price": money(price), "barcodes": [{"code": code}]}], **(extra or {})}
            product = api.post("/catalog/products/", body)
            variant = product["variants"][0]
            self.variants.append({"id": variant["id"], "price": Decimal(price), "track": product["track_stock"],
                                  "lots": product["track_lots"], "code": code, "name": name})
            return product

        for name, cat, brand, price, ncm in [
            ("Refrigerante Cola 2L", "Refrigerantes", "Gela Já", "9.99", "22021000"),
            ("Refrigerante Guaraná 2L", "Refrigerantes", "Gela Já", "8.49", "22021000"),
            ("Cerveja Pilsen Lata 350ml", "Cervejas", "Serra Azul", "4.29", "22030000"),
            ("Água Mineral 500ml", "Águas", "Serra Azul", "2.50", "22011000"),
            ("Chocolate ao Leite 90g", "Doces", "Bom Sabor", "6.90", "18063210"),
            ("Panela Antiaderente 24cm", "Utilidades", "Lar Doce", "129.90", "73239300"),
            ("Jogo de Copos 6 peças", "Utilidades", "Lar Doce", "59.90", "70133700"),
            ("Mesa de Centro Madeira", "Móveis", "Casa Viva", "449.00", "94036000"),
            ("Chinelo Praia", "Sandálias", "Mar Aberto", "29.90", "64022000"),
            ("Bermuda Tactel", "Moda praia", "Mar Aberto", "79.90", "62034200"),
        ]:
            simple(name, cat, brand, price, ncm)
        simple("Iogurte Natural 170g", "Laticínios", "Fazenda Real", "4.99", "04031000", extra={"track_lots": True})
        simple("Requeijão Cremoso 200g", "Laticínios", "Fazenda Real", "8.90", "04061090", extra={"track_lots": True})
        for name, price in [("Queijo Mussarela (kg)", "54.90"), ("Presunto Cozido (kg)", "42.90")]:
            simple(name, "Frios", "Fazenda Real", price, "04069090", extra={"sale_method": "weight", "unit": "KG"})
        services = {}
        for name, price, desc in [
            ("Montagem de móveis", "120.00", "Montador vai até a casa do cliente em até 3 dias úteis."),
            ("Entrega expressa", "25.00", "Entrega no mesmo dia para pedidos até as 14h."),
            ("Embalagem para presente", "8.00", "Papel, laço e cartão."),
            ("Garantia estendida 12 meses", "39.90", "Mais 12 meses depois da garantia do fabricante."),
        ]:
            services[name] = simple(name, "Serviços", None, price, "00000000", desc=f"<p>{desc}</p>",
                                    extra={"type": "service", "purpose": "09", "track_stock": False})["id"]
        self.service_ids = services

        # Com grade: as combinações nascem do eixo; cada uma ganha EAN.
        for name, ref, cat, brand, price, grid, ncm in [
            ("Camiseta Básica Algodão", "CAMB", "Camisetas", "Urbano", "49.90",
             {"Cor": ["Branca", "Preta", "Azul"], "Tamanho": ["P", "M", "G"]}, "61091000"),
            ("Calça Jeans Slim", "CJS", "Calças", "Urbano", "149.90", {"Tamanho": ["38", "40", "42", "44"]}, "62034200"),
            ("Tênis Corrida Leve", "TCL", "Tênis", "Pé Leve", "299.90",
             {"Numeração": ["37", "38", "39", "40", "41", "42"]}, "64041100"),
        ]:
            product = api.post("/catalog/products/", {
                "name": name, "reference": ref, "type": "variable", "category": self.categories[cat],
                "brand": self.brands[brand], "ncm": ncm, "grid": grid,
                "description": f"<p><strong>{name}</strong>: conforto para o dia a dia.</p><ul><li>Troca grátis em 30 dias</li></ul>"})
            rows = []
            for variant in product["variants"]:
                code = ean13(f"7891000{next(seq):05d}")
                rows.append({**variant, "price": money(price), "barcodes": [{"code": code}]})
                self.variants.append({"id": variant["id"], "price": Decimal(price), "track": True, "lots": False,
                                      "code": code, "name": f"{name} {variant['name']}"})
            api.patch(f"/catalog/products/{product['id']}/", {"variants": rows})
        # Kit: sai do estoque pelos componentes.
        kit = api.post("/catalog/products/", {"name": "Kit Churrasco", "type": "kit", "category": self.categories["Mercearia"],
                                              "ncm": "22030000", "variants": [{"sku": "KITCHURRAS", "price": "59.90"}]})
        beer = next(v for v in self.variants if v["name"].startswith("Cerveja"))
        cola = next(v for v in self.variants if v["name"].startswith("Refrigerante Cola"))
        api.post("/catalog/components/", {"kit": kit["id"], "component": beer["id"], "quantity": "6"})
        api.post("/catalog/components/", {"kit": kit["id"], "component": cola["id"], "quantity": "1"})
        # Serviços oferecidos junto (aparecem na vitrine do produto no PDV).
        for service, body in [
            ("Montagem de móveis", {"kind": "category", "categories": [self.categories["Móveis"]]}),
            ("Garantia estendida 12 meses", {"kind": "category", "price": "29.90", "price_min": "100.00",
                                             "categories": [self.categories[c] for c in ("Casa", "Tênis")]}),
            ("Embalagem para presente", {"kind": "category",
                                         "categories": [self.categories["Vestuário"], self.categories["Calçados"]]}),
        ]:
            api.post("/catalog/service-rules/", {"service": self.service_ids[service], **body})
        self.log(f"{len(self.categories)} categorias, {len(self.brands)} marcas e {len(self.variants)} variantes vendáveis")

    # ── Entrega e ficha técnica: tabelas de frete e campos personalizados ──────
    def delivery_and_specs(self):
        api = self.api
        cat = self.categories
        for spec in [
            {"name": "Tempo de montagem", "type": "number", "unit": "h", "position": 1, "categories": [cat["Casa"]],
             "help_text": "Quanto o montador leva, para agendar."},
            {"name": "Garantia", "type": "select", "position": 2, "options": ["3 meses", "6 meses", "12 meses", "24 meses"]},
            {"name": "Material", "type": "text", "position": 3, "categories": [cat["Casa"], cat["Vestuário"]]},
            {"name": "Voltagem", "type": "select", "position": 4, "options": ["110 V", "220 V", "Bivolt"],
             "categories": [cat["Utilidades"]]},
            {"name": "Vai para lava-louças", "type": "boolean", "position": 5, "categories": [cat["Utilidades"]]},
            {"name": "Código no fornecedor", "type": "text", "position": 9, "show_in_specs": False},
            {"name": "Aniversário de casamento", "owner": "customer", "type": "date"},
            {"name": "Como conheceu a loja", "owner": "customer", "type": "select",
             "options": ["Instagram", "Indicação", "Passou na frente", "Google"]},
            {"name": "Pedido no marketplace", "owner": "sale", "type": "text"},
        ]:
            api.post("/metafield-definitions/", {"owner": "product", **spec})
        by_name = {p["name"]: p["id"] for p in api.get("/catalog/products/?page_size=200")["results"]}
        for name, values in [
            ("Mesa de Centro Madeira", {"tempo_de_montagem": 1.5, "garantia": "12 meses", "material": "MDF e pinus maciço",
                                        "codigo_no_fornecedor": "CV-MC-118"}),
            ("Panela Antiaderente 24cm", {"garantia": "6 meses", "material": "Alumínio com antiaderente",
                                          "vai_para_lava_loucas": True}),
            ("Jogo de Copos 6 peças", {"garantia": "3 meses", "material": "Vidro", "vai_para_lava_loucas": True}),
            ("Camiseta Básica Algodão", {"material": "100% algodão", "garantia": "3 meses"}),
            ("Tênis Corrida Leve", {"garantia": "6 meses", "cor_da_caixa": "Azul"}),
        ]:
            if name in by_name:
                api.patch(f"/catalog/products/{by_name[name]}/", {"metafields": values})
        api.post("/logistics/freight-tables/", {
            "name": "Motoboy (capital)", "kind": "zip_range", "lead_days": 1, "position": 1, "ranges": [
                {"label": "Centro expandido", "zip_start": "01000000", "zip_end": "01599999", "value": "14.90", "lead_days": 0},
                {"label": "Capital", "zip_start": "01000000", "zip_end": "05999999", "value": "24.90"},
                {"label": "Zona Leste", "zip_start": "03000000", "zip_end": "03999999", "value": "29.90"},
                {"label": "Zona Sul", "zip_start": "04000000", "zip_end": "04999999", "value": "27.90"},
            ]})
        api.post("/logistics/freight-tables/", {
            "name": "Transportadora (Grande SP)", "kind": "zip_range", "lead_days": 3, "position": 2, "ranges": [
                {"label": "Capital", "zip_start": "01000000", "zip_end": "05999999", "value": "49.90"},
                {"label": "Grande SP", "zip_start": "06000000", "zip_end": "09999999", "value": "69.90", "lead_days": 4},
            ]})
        api.post("/logistics/freight-tables/", {
            "name": "Caminhão de móveis", "kind": "distance", "origin_zip": "01310100", "price_per_km": "3.50",
            "fixed_fee": "40.00", "min_value": "80.00", "max_distance_km": "120", "lead_days": 5, "position": 3})
        self.log("9 campos personalizados (ficha técnica), metacampos em 5 produtos e 3 tabelas de frete")

    # ── Estoque: depósitos, endereços, etiquetas e documentos confirmados ──────
    def stock(self):
        api = self.api
        main_wh = next(w for w in api.get("/stock/warehouses/?is_default=true")["results"])
        central = api.post("/stock/warehouses/", {"name": "Depósito Central", "kind": "storage", "uses_bins": True})
        api.post("/stock/warehouses/", {"name": "Avariados", "kind": "damaged"})
        api.post("/stock/warehouses/", {"name": "Showroom", "kind": "sales_floor", "parent": main_wh["id"]})
        for aisle in "AB":
            for rack in range(1, 4):
                for level in (1, 2):
                    api.post("/stock/bins/", {"warehouse": central["id"], "code": f"{aisle}-{rack:02d}-{level}",
                                              "aisle": aisle, "rack": f"{rack:02d}", "level": str(level),
                                              "sequence": (ord(aisle) - 65) * 10 + rack * 2 + level})
        # Os modelos comuns já nascem com a conta (pré-prontos); aqui, dois próprios da loja.
        for name, subject, w, h, fields in [
            ("Calçados (caixa)", "product", 70, 40, ["name", "sku", "barcode"]),
            ("Frios (balança)", "product", 58, 40, ["name", "price", "barcode"]),
        ]:
            api.post("/stock/label-templates/", {"name": name, "subject": subject, "width_mm": w, "height_mm": h,
                                                 "fields": fields})
        stocked = [v for v in self.variants if v["track"]]
        expires = (TODAY + timedelta(days=45)).isoformat()
        for i in range(0, len(stocked), 6):  # entradas de compra: 6 itens por nota
            items = [{"variant": v["id"], "quantity": str(random.choice([12, 24, 36, 48])),
                      "unit_cost": money(v["price"] * Decimal("0.55")),
                      **({"lot_number": f"L{i:03d}{n}", "expires_at": expires} if v["lots"] else {})}
                     for n, v in enumerate(stocked[i:i + 6])]
            doc = api.post("/stock/documents/", {
                "kind": "entry", "warehouse": main_wh["id"], "supplier": self.suppliers[(i // 6) % len(self.suppliers)],
                "external_number": str(4500 + i), "effective_date": TODAY.isoformat(), "items": items,
                "reason": "Compra de reposição"})
            api.post(f"/stock/documents/{doc['id']}/post/")
        moves = [
            ("exit", {"exit_reason": "loss", "reason": "Avaria no transporte"}, stocked[0], "2"),
            ("exit", {"exit_reason": "consumption", "reason": "Uso interno na loja"}, stocked[3], "1"),
            ("transfer", {"destination": central["id"], "reason": "Excesso para o depósito"}, stocked[1], "6"),
            ("adjustment", {"reason": "Acerto após contagem"}, stocked[2], "-1"),
        ]
        for kind, extra, variant, qty in moves:
            doc = api.post("/stock/documents/", {"kind": kind, "warehouse": main_wh["id"], "effective_date": TODAY.isoformat(),
                                                 "items": [{"variant": variant["id"], "quantity": qty}], **extra})
            api.post(f"/stock/documents/{doc['id']}/post/")
        api.post("/stock/documents/", {"kind": "entry", "warehouse": main_wh["id"], "effective_date": TODAY.isoformat(),
                                       "reason": "Rascunho: pedido ainda não chegou",
                                       "items": [{"variant": stocked[5]["id"], "quantity": "10", "unit_cost": "5.00"}]})
        self.main_warehouse = main_wh["id"]
        self.log("depósitos, 12 endereços, 10 modelos de etiqueta e ~12 documentos de estoque")

    # ── Promoções: tabelas, regras e cupons ─────────────────────────────────────
    def promotions(self):
        api = self.api
        start = timezone.now().isoformat()
        end = (timezone.now() + timedelta(days=30)).isoformat()
        rules = [("Semana da cerveja", "categories", "percent", "10", "Cervejas"),
                 ("Liquida verão", "categories", "percent", "20", "Moda praia"),
                 ("Calçados em oferta", "categories", "percent", "15", "Tênis"),
                 ("Mercearia econômica", "categories", "amount", "1", "Doces"),
                 ("Casa nova", "categories", "percent", "12", "Utilidades"),
                 ("Marca Urbano", "brands", "percent", "10", "Urbano"),
                 ("Marca Gela Já", "brands", "percent", "5", "Gela Já"),
                 ("Frios fatiados", "categories", "percent", "8", "Frios"),
                 ("Móveis à vista", "categories", "percent", "7", "Móveis"),
                 ("Aniversário da loja", "all", "percent", "5", None)]
        for i, (name, target, kind, value, ref) in enumerate(rules):
            table = api.post("/promotions/tables/", {"name": f"Tabela {name}", "description": f"Campanha: {name}",
                                                     "is_enabled": i < 8, "starts_at": start, "ends_at": end})
            body = {"table": table["id"], "name": name, "target": target, "kind": kind, "value": value}
            if target == "categories":
                body["categories"] = [self.categories[ref]]
            if target == "brands":
                body["brands"] = [self.brands[ref]]
            api.post("/promotions/rules/", body)
        for code, kind, value, minimum in [("BEMVINDO10", "percent", "10", "50"), ("FRETEGRATIS", "free_shipping", "0", "150"),
                                           ("VOLTE15", "percent", "15", "100"), ("ANIVER20", "amount", "20", "120"),
                                           ("VIP25", "percent", "25", "300"), ("PRIMEIRA5", "amount", "5", "30"),
                                           ("BLACK30", "percent", "30", "200"), ("CLUBE12", "percent", "12", "80"),
                                           ("EMPRESA50", "amount", "50", "500"), ("PIX5", "percent", "5", "0")]:
            api.post("/promotions/coupons/", {"code": code, "name": f"Cupom {code}", "kind": kind, "value": value,
                                              "min_subtotal": minimum, "usage_limit": 100})
        self.log("10 tabelas de desconto, 10 regras e 10 cupons")

    # ── Vendas: 10 turnos de caixa com vendas reais (checkout) ─────────────────
    def sales(self):
        api = self.api
        methods = {m["kind"]: m["id"] for m in api.get("/payment-methods/?page_size=50")["results"] if m["kind"] != "other"}
        register = api.get("/cash/registers/")["results"][0]["id"]
        # Um segundo caixa livre: o "turno de hoje" fica no Caixa 01, e o operador de caixa
        # da demo (bruno) abre o dele no Caixa 02.
        if not CashRegister.all_objects.filter(store=self.main, code="CX02", deleted_at__isnull=True).exists():
            CashRegister.all_objects.create(account=self.account, store=self.main, name="Caixa 02", code="CX02")
        # Caixa tem dono: o operador da demo (bruno) é vinculado aos dois caixas da loja.
        from django.contrib.auth import get_user_model

        bruno = get_user_model().objects.filter(username="bruno").first()
        for reg in CashRegister.all_objects.filter(store=self.main, deleted_at__isnull=True):
            if bruno:
                reg.operators.add(bruno)
        for open_one in api.get(f"/cash/sessions/?register={register}&status=open")["results"]:  # turno esquecido aberto
            current = api.get(f"/cash/sessions/{open_one['id']}/")
            api.post(f"/cash/sessions/{open_one['id']}/close/", {"counted_amount": current["expected_now"], "notes": ""})
        sellable = [v for v in self.variants if not v["name"].endswith("(kg)")]
        self.sale_ids, self.session_ids = [], []
        for turn in range(10):
            session = api.post("/cash/sessions/", {"register": register, "opening_amount": "200.00"})
            self.session_ids.append(session["id"])
            for n in range(3):
                customer = self.customers[(turn * 3 + n) % len(self.customers)] if n != 1 else None
                sale = api.post("/sales/", {"customer": customer["id"] if customer else None,
                                            "seller": self.sellers[(turn + n) % len(self.sellers)] if self.sellers else None})
                for variant in random.sample(sellable, k=random.randint(1, 4)):
                    body = api.post(f"/sales/{sale['id']}/items/", {"variant": variant["id"],
                                                                    "quantity": str(random.choice([1, 1, 2, 3]))})
                total = Decimal(body["total"])
                kind = ["cash", "pix", "credit_card", "debit_card", "voucher"][(turn + n) % 5]
                payment = {"method": methods[kind], "amount": money(total)}
                if kind == "cash":
                    payment["tendered"] = money((total / 50).to_integral_value(rounding="ROUND_UP") * 50)
                if kind == "credit_card":
                    payment["installments"] = 3 if total > 150 else 1
                if kind in ("pix", "credit_card", "debit_card"):  # o comprovante (NSU) é obrigatório
                    payment["nsu"] = f"{random.randint(100000, 999999)}"
                api.post(f"/sales/{sale['id']}/checkout/", {"payments": [payment]})
                self.sale_ids.append(sale["id"])
            # Fim do dia como numa loja: sangria do excedente para o cofre, fica o troco de R$ 200 na gaveta,
            # e o fechamento conta os R$ 200. A próxima abertura confere os mesmos R$ 200 (conferência cega).
            current = api.get(f"/cash/sessions/{session['id']}/")
            extra = Decimal(current.get("expected_now") or "200.00") - Decimal("200.00")
            if extra > 0:
                api.post(f"/cash/sessions/{session['id']}/movements/", {"kind": "withdrawal", "amount": money(extra),
                                                                       "reason": "Sangria de fechamento",
                                                                       "destination": "Cofre"})
            api.post(f"/cash/sessions/{session['id']}/close/", {"counted_amount": "200.00", "notes": f"Turno {turn + 1}"})
        # Uma venda no crediário (vira conta a receber), num turno que fica aberto: o "turno de hoje".
        api.post("/cash/sessions/", {"register": register, "opening_amount": "200.00"})  # fica aberto: o turno de hoje
        sale = api.post("/sales/", {"customer": self.customers[0]["id"]})
        body = api.post(f"/sales/{sale['id']}/items/", {"variant": sellable[5]["id"], "quantity": "1"})
        api.post(f"/sales/{sale['id']}/checkout/", {"payments": [{"method": methods["installment_plan"],
                                                                  "amount": body["total"], "installments": 3}]})
        self.sale_ids.append(sale["id"])
        self.log(f"10 turnos de caixa e {len(self.sale_ids)} vendas (dinheiro, PIX, cartões, vale e crediário)")

    # ── Financeiro: contas, categorias, títulos com parcelas, lançamentos ─────
    def finance(self):
        api = self.api
        for name, bank in [("Banco do Brasil", "001"), ("Itaú", "341"), ("Caixa Econômica", "104")]:
            api.post("/finance/accounts/", {"name": name, "kind": "bank", "bank_code": bank, "agency": "1234",
                                            "account_number": f"{random.randint(10000, 99999)}-0", "opening_balance": "15000.00"})
        bank = next(a for a in api.get("/finance/accounts/?page_size=50")["results"] if a["kind"] == "bank")
        for name, kind in [("Marketing digital", "expense"), ("Fretes de entrega", "expense"),
                           ("Manutenção da loja", "expense"), ("Receita de serviços", "income")]:
            api.post("/finance/categories/", {"name": name, "kind": kind})
        due = (TODAY + timedelta(days=5)).isoformat()
        for i, (desc, total, parts) in enumerate([
            ("Aluguel da matriz", "4500.00", 3), ("Energia elétrica", "890.40", 1), ("Internet e telefone", "289.90", 1),
            ("Compra de mercadorias - Aurora", "6200.00", 4), ("Compra Têxtil Vento Sul", "3800.00", 2),
            ("Contabilidade", "950.00", 1), ("Seguro da loja", "1440.00", 6), ("Sistema de câmeras", "720.00", 3),
            ("Limpeza terceirizada", "1100.00", 1), ("Uniformes", "640.00", 2)]):
            title = api.post("/finance/titles/", {"kind": "payable", "description": desc, "total": total,
                                                  "installment_count": parts, "first_due": due,
                                                  "supplier": self.suppliers[i % len(self.suppliers)],
                                                  "document_number": f"NF{7000 + i}"})
            if i % 3 == 0:  # algumas já pagas (1ª parcela)
                first = api.get(f"/finance/installments/?title={title['id']}&ordering=number")["results"][0]
                api.post(f"/finance/installments/{first['id']}/settle/", {"financial_account": bank["id"],
                                                                         "amount": first["amount"]})
        for i in range(10):
            title = api.post("/finance/titles/", {"kind": "receivable", "description": f"Venda a prazo — pedido {9100 + i}",
                                                  "total": money(300 + i * 75), "installment_count": 1 + i % 3,
                                                  "first_due": due, "customer": self.customers[i]["id"]})
            if i % 4 == 0:
                first = api.get(f"/finance/installments/?title={title['id']}&ordering=number")["results"][0]
                api.post(f"/finance/installments/{first['id']}/settle/", {"financial_account": bank["id"],
                                                                         "amount": first["amount"]})
        for i, (desc, kind, amount) in enumerate([
            ("Tarifa bancária", "out", "39.90"), ("Rendimento da aplicação", "in", "182.33"), ("Anúncios em redes sociais", "out", "350.00"),
            ("Frete de entrega", "out", "120.00"), ("Venda de sucata/papelão", "in", "45.00"), ("Material de escritório", "out", "87.60"),
            ("Café e copa", "out", "64.30"), ("Serviço de montagem", "in", "240.00"), ("Manutenção do ar-condicionado", "out", "280.00"),
            ("Estorno de tarifa", "in", "39.90")]):
            api.post("/finance/transactions/", {"financial_account": bank["id"], "kind": kind, "amount": amount,
                                                "date": (TODAY - timedelta(days=i * 2)).isoformat(), "description": desc})
        self.log("contas financeiras, 10 contas a pagar, 10 a receber e 10 lançamentos")

    # ── Fiscal: notas de entrada (XML) e notas emitidas ─────────────────────────
    def fiscal_documents(self):
        from starrp.core.nfe_sample import nfe_xml

        main_cnpj = "".join(c for c in self.main.cnpj if c.isdigit())
        for i in range(10):
            supplier = cnpj(80 + i)
            number = str(2000 + i)
            key = f"35{TODAY:%y%m}{supplier}55001{int(number):09d}1{i:08d}"
            key += str(i % 10)
            self.api.post("/inbound-nfe/import/", {"xml": nfe_xml(key=key[:44], recipient=main_cnpj, supplier=supplier,
                                                                   number=number, lot_code=f"LT-{i:03d}").decode()})
        config = self.main.fiscal_config
        sales = Sale.all_objects.filter(pk__in=self.sale_ids[:10]).prefetch_related("items")
        for n, sale in enumerate(sales, start=1):
            status = "authorized" if n < 9 else ("rejected" if n == 9 else "cancelled")
            invoice = Invoice.all_objects.create(
                account=self.account, store=self.main, sale=sale, fiscal_config=config, document_model="65", series=1,
                number=n, environment="2", status=status, provider="manual",
                access_key=f"35{TODAY:%y%m}{main_cnpj}65001{n:09d}1{n:08d}{n % 10}",
                recipient_document=sale.customer_document, recipient_name=sale.customer_name or "Consumidor",
                products_total=sale.subtotal, discount_total=sale.discount, total=sale.total,
                protocol=f"135{n:012d}" if status != "rejected" else "",
                authorized_at=timezone.now() if status != "rejected" else None,
                error_message="Rejeição 778: NCM inexistente (demonstração)" if status == "rejected" else "",
                cancel_reason="Cliente desistiu da compra" if status == "cancelled" else "")
            for line, item in enumerate(sale.items.all(), start=1):
                InvoiceItem.all_objects.create(
                    account=self.account, invoice=invoice, sale_item=item, variant=item.variant, line_number=line,
                    code=item.sku, description=item.description[:180], ncm="61091000", cfop="5102", csosn="102",
                    quantity=item.quantity, unit_price=item.unit_price, discount=item.discount, total=item.total)
        self.log("10 notas de entrada (XML) e 10 notas emitidas")

    # ── Datas: vendas e turnos nos últimos 30 dias (painel e relatórios com história) ──
    def backdate(self):
        # Só os turnos que a demo criou (os de antes ficam como estão).
        sessions = list(CashSession.all_objects.filter(pk__in=self.session_ids).order_by("opened_at"))
        for index, session in enumerate(sessions):
            day = timezone.now() - timedelta(days=(len(sessions) - index) * 3)
            CashSession.all_objects.filter(pk=session.pk).update(
                opened_at=day.replace(hour=8, minute=0), closed_at=day.replace(hour=18, minute=0) if session.closed_at else None)
            for offset, sale in enumerate(Sale.all_objects.filter(cash_session=session).order_by("created_at")):
                moment = day.replace(hour=9 + (offset * 3) % 9, minute=random.randint(0, 59))
                Sale.all_objects.filter(pk=sale.pk).update(created_at=moment, completed_at=moment)
        self.log("vendas e turnos espalhados pelos últimos 30 dias")

