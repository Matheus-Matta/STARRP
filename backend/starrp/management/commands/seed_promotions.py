"""Vendas de exemplo com cupom, desconto manual e promoção (para os relatórios de Promoções).

Pelo fluxo real da API (preço, cupom, desconto e pagamento calculados pelo sistema), canal
retaguarda e Pix (não depende de caixa aberto):

1. com as tabelas de promoção DESLIGADAS por um momento: vendas nos últimos 70 dias, umas com
   cupom, outras com desconto manual e outras cheias; parte dos clientes volta a comprar dias
   depois (cupom de retorno fideliza mais que cupom de liquidação);
2. com as tabelas de volta como estavam: vendas nos dias em que a promoção está valendo.

As datas são recuadas depois de criadas. Roda uma vez por conta (se já houver uso de cupom, sai).
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from starrp.models import Account, CouponRedemption, DiscountTable, Payment, Sale, StockBalance, Store, UserProfile

from .seed_demo import Api

# Chance de o cliente voltar a comprar depois, por cupom (sem cupom = "").
COME_BACK = {"VOLTE15": 0.75, "CLUBE12": 0.65, "BEMVINDO10": 0.5, "PIX5": 0.4, "ANIVER20": 0.4, "VIP25": 0.3,
             "BLACK30": 0.1, "": 0.35, "manual": 0.25}
COUPONS = ["VOLTE15", "CLUBE12", "BEMVINDO10", "BLACK30", "PIX5", "VIP25", "ANIVER20"]


class Command(BaseCommand):
    help = "Cria vendas de exemplo com cupom, desconto manual e promoção (uma vez por conta)."

    def add_arguments(self, parser):
        parser.add_argument("--account", default="loja-demo", help="Slug da conta (padrão: loja-demo).")
        parser.add_argument("--prejuizo", action="store_true",
                            help="Só cria 3 vendas de exemplo NO PREJUÍZO (desconto acima da margem), uma vez por conta.")

    def handle(self, *args, **options):
        random.seed(11)
        account = Account.objects.filter(slug=options["account"]).first()
        if account is None:
            raise CommandError(f"Conta {options['account']} não existe.")
        if not options["prejuizo"] and CouponRedemption.all_objects.filter(account=account).exists():
            self.stdout.write(self.style.WARNING("A conta já tem uso de cupom. Nada a fazer."))
            return
        admin = UserProfile.all_objects.filter(account=account, role__code="admin").select_related("user").first().user
        store = Store.all_objects.filter(account=account, deleted_at__isnull=True).order_by("created_at").first()
        self.api = Api(admin, store)
        self.pix = next(m["id"] for m in self.api.get("/payment-methods/?page_size=50")["results"] if m["kind"] == "pix")
        self.customers = [c["id"] for c in self.api.get("/customers/?page_size=40")["results"]]
        # Só produtos com saldo de sobra na filial (cada venda leva até 3 itens, 2 de cada).
        self.variants = [str(v) for v, q in StockBalance.all_objects.filter(warehouse__store=store).values_list(
            "variant_id").annotate(q=Sum("quantity")) if q >= (6 if options["prejuizo"] else 30)]
        if len(self.variants) < 4:
            raise CommandError("Poucos produtos com estoque para gerar as vendas de exemplo.")
        now = timezone.now()
        if options["prejuizo"]:
            self.losses(account, now)
            return
        tables = {t.pk: t.is_enabled for t in DiscountTable.all_objects.filter(account=account)}
        made = {"cupom": 0, "desconto": 0, "cheia": 0, "volta": 0, "promoção": 0}
        with transaction.atomic():  # falhou no meio, nada fica (nem venda pela metade)
            self.build(now, tables, made)
        self.stdout.write(self.style.SUCCESS("Vendas de exemplo criadas: " + ", ".join(f"{v} {k}" for k, v in made.items())))

    def build(self, now, tables, made):
        try:
            DiscountTable.all_objects.filter(pk__in=tables).update(is_enabled=False)
            for _ in range(40):
                when = now - timedelta(days=random.randint(12, 70), hours=random.randint(0, 9))
                customer = random.choice(self.customers)
                style = random.choices(["coupon", "manual", "full"], weights=[45, 20, 35])[0]
                coupon = random.choice(COUPONS) if style == "coupon" else None
                done = self.sale(customer, when, coupon=coupon, percent=random.choice([5, 8, 10, 15]) if style == "manual" else None)
                key = (coupon if done.get("coupon_code") else "") if style != "manual" else "manual"
                made["cupom" if done.get("coupon_code") else "desconto" if style == "manual" else "cheia"] += 1
                if random.random() < COME_BACK.get(key, 0.3):
                    back = when + timedelta(days=random.randint(5, 25))
                    if back < now - timedelta(days=3):
                        self.sale(customer, back)
                        made["volta"] += 1
        finally:
            for pk, enabled in tables.items():
                DiscountTable.all_objects.filter(pk=pk).update(is_enabled=enabled)
        for n in range(10):  # dias da promoção (as tabelas valem agora)
            when = now - timedelta(hours=random.randint(1, 30))
            self.sale(random.choice(self.customers), when,
                      coupon=random.choice(["PIX5", "VOLTE15", None, None]) if n % 3 == 0 else None)
            made["promoção"] += 1

    LOSS_NOTE = "Exemplo de venda no prejuízo (gerador da demo)"

    def losses(self, account, now):
        """3 vendas em que o desconto passou da margem: as listas "deram prejuízo" têm o que mostrar."""
        if Sale.all_objects.filter(account=account, notes=self.LOSS_NOTE).exists():
            self.stdout.write(self.style.WARNING("Os exemplos de prejuízo já existem. Nada a fazer."))
            return
        with transaction.atomic():
            for days, coupon, percent in ((6, None, 55), (9, "VOLTE15", 45), (13, "CLUBE12", 50)):
                body = self.sale(random.choice(self.customers), now - timedelta(days=days, hours=3), coupon=coupon,
                                 percent=percent)
                Sale.all_objects.filter(pk=body["id"]).update(notes=self.LOSS_NOTE)
        self.stdout.write(self.style.SUCCESS("3 vendas de exemplo no prejuízo criadas."))

    def sale(self, customer, when, coupon=None, percent=None):
        api = self.api
        sale = api.post("/sales/", {"customer": customer, "channel": "backoffice"})
        for variant in random.sample(self.variants, k=random.randint(1, 3)):
            body = api.post(f"/sales/{sale['id']}/items/", {"variant": variant, "quantity": str(random.choice([1, 1, 2]))})
        if coupon:
            try:
                body = api.post(f"/sales/{sale['id']}/coupon/", {"code": coupon})
            except CommandError:
                pass  # mínimo não atingido etc.: segue sem cupom
        if percent:
            body = api.post(f"/sales/{sale['id']}/discount/", {"percent": str(percent)})
        total = Decimal(body["total"])
        api.post(f"/sales/{sale['id']}/checkout/", {"payments": [
            {"method": self.pix, "amount": f"{total:.2f}", "nsu": f"{random.randint(100000, 999999)}"}]})
        Sale.all_objects.filter(pk=sale["id"]).update(created_at=when, completed_at=when)
        Payment.all_objects.filter(sale_id=sale["id"]).update(created_at=when)
        CouponRedemption.all_objects.filter(sale_id=sale["id"]).update(created_at=when)
        return body
