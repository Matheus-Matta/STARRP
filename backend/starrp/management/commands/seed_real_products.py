"""Troca os produtos da demo por produtos reais, para a precificação achar preço de verdade no mercado.

    python manage.py seed_real_products                  # conta "loja-demo" (o `seed_demo` chama no fim)
    python manage.py seed_real_products --account outra

A busca começa sempre por título + marca. Parte fica com o EAN real (conferido na Open Food Facts), a segunda
tentativa quando falta oferta; o resto recebe código interno de loja (prefixo 2) e fica só no título. Os nomes da demo só mudam aqui, depois de tudo
criado, porque as outras seeds procuram os produtos pelo nome antigo. Rodar de novo não faz nada: quem já foi
trocado não é mais encontrado. Vendas e notas antigas continuam com o nome que tinham, como no mundo real.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from starrp.management.commands.seed_demo import ean13
from starrp.models import Account, Brand, Module, Product, ProductBarcode
from starrp.models.platform import default_price_sources

# (nome na demo, nome real, marca, preço, EAN real ou None para buscar só pelo título)
REAL_PRODUCTS = [
    ("Refrigerante Cola 2L", "Coca-Cola 2L", "Coca-Cola", "11.49", "7894900011517"),
    ("Refrigerante Guaraná 2L", "Guaraná Antarctica 2L", "Antarctica", "9.49", "7891991001342"),
    ("Água Mineral 500ml", "Água Mineral Crystal 500ml", "Crystal", "3.00", "7894900530001"),
    ("Chocolate ao Leite 90g", "Chocolate Lacta ao Leite 90g", "Lacta", "7.99", "7622300991456"),
    ("Requeijão Cremoso 200g", "Requeijão Cremoso Itambé 200g", "Itambé", "9.90", "7896051140016"),
    ("Cerveja Pilsen Lata 350ml", "Cerveja Heineken Lata 350ml", "Heineken", "5.49", None),
    ("Iogurte Natural 170g", "Iogurte Natural Nestlé 170g", "Nestlé", "4.99", None),
    ("Queijo Mussarela (kg)", "Queijo Mussarela Tirolez", "Tirolez", "54.90", None),
    ("Presunto Cozido (kg)", "Presunto Cozido Sadia", "Sadia", "42.90", None),
    ("Panela Antiaderente 24cm", "Panela Tramontina Turim 24cm", "Tramontina", "129.90", None),
    ("Jogo de Copos 6 peças", "Copo Americano Nadir 190ml", "Nadir", "5.90", None),
    ("Mesa de Centro Madeira", "Mesa de Centro Madesa", "Madesa", "449.00", None),
    ("Chinelo Praia", "Chinelo Havaianas Top", "Havaianas", "39.90", None),
    ("Bermuda Tactel", "Bermuda Tactel Mormaii", "Mormaii", "79.90", None),
    ("Camiseta Básica Algodão", "Camiseta Básica Hering", "Hering", "49.90", None),
    ("Calça Jeans Slim", "Calça Jeans Levi's 511 Slim", "Levi's", "299.90", None),
    ("Tênis Corrida Leve", "Tênis Olympikus Corre 3", "Olympikus", "299.90", None),
]


class Command(BaseCommand):
    help = "Troca os produtos da demo por produtos reais (uns com EAN, outros só pelo título)."

    def add_arguments(self, parser):
        parser.add_argument("--account", default="loja-demo", help="Slug da conta (padrão: loja-demo).")

    @transaction.atomic
    def handle(self, *args, **options):
        account = Account.objects.filter(slug=options["account"]).first()
        if account is None:
            raise CommandError(f"Conta {options['account']} não existe.")
        internal = 0
        changed = 0
        for old, new, brand_name, price, ean in REAL_PRODUCTS:
            product = Product.all_objects.filter(account=account, name=old, deleted_at__isnull=True).first()
            if product is None:
                continue
            brand, _ = Brand.all_objects.get_or_create(account=account, name=brand_name, deleted_at=None)
            product.name, product.brand = new, brand
            product.description = product.description.replace(old, new)
            product.save()
            for variant in product.variants.filter(deleted_at__isnull=True):
                self._reprice(variant, Decimal(price))
                internal += 0 if ean else 1
                self._set_code(account, variant, ean or ean13(f"2000000{internal:05d}"))
            changed += 1
        self._track(account)
        self.stdout.write(self.style.SUCCESS(f"{changed} produtos da demo trocados por produtos reais."))

    def _reprice(self, variant, price):
        """O custo acompanha o preço: a margem da demo continua a mesma."""
        if variant.price and variant.average_cost:
            variant.average_cost = variant.average_cost * price / variant.price
        variant.price = price
        variant.save(update_fields=["price", "average_cost", "updated_at"])

    def _set_code(self, account, variant, code):
        rows = ProductBarcode.all_objects.filter(variant=variant, deleted_at__isnull=True)
        primary = rows.filter(is_primary=True).first() or rows.first()
        if primary is None:
            ProductBarcode.all_objects.create(account=account, variant=variant, code=code, is_primary=True)
            return
        primary.code = code
        primary.save(update_fields=["code", "updated_at"])

    def _track(self, account):
        """A demo já nasce com a precificação ligada e as fontes de busca, sem tirar as que já estão.
        Fonte sem configuração fica de fora da leitura sozinha. Uma só roda se a anterior falhar (o padrão da conta)."""
        account.extra_modules = sorted({*(account.extra_modules or []), Module.PRICING.value, Module.SEO.value, Module.COSMOS.value})
        account.price_tracking_enabled = True
        chosen = account.price_sources or []
        account.price_sources = [*chosen, *(key for key in default_price_sources() if key not in chosen)]
        account.save(update_fields=["extra_modules", "price_tracking_enabled", "price_sources", "updated_at"])
