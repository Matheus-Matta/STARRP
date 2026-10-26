"""Avaliações e entregas de exemplo a partir das vendas que já existem na conta.

Para os relatórios de Avaliações e de Entregas terem o que mostrar na demo:
- uma parte das vendas concluídas com cliente vira ENTREGA (endereço do cliente, prazo da
  tabela, saída e entrega em datas variadas — algumas no prazo, outras com atraso, outras
  ainda a caminho);
- os clientes avaliam os produtos que compraram e a entrega (a maioria aprovada, algumas
  pendentes de moderação e uma ou outra rejeitada).

Só roda uma vez por conta (se já houver avaliação, não faz nada). O `seed_demo` chama no fim.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from starrp.models import Account, CustomerAddress, Review, Sale, SaleItem
from starrp.services.reviews import public_name
from starrp.services.sales import DELIVERY_KEY

COMMENTS = {
    5: ["Excelente, superou o que eu esperava!", "Produto ótimo, recomendo demais.", "Qualidade impecável, comprarei de novo.",
        "Chegou certinho e é lindo pessoalmente."],
    4: ["Muito bom, só a cor é um pouco diferente da foto.", "Gostei bastante, bom custo-benefício.",
        "Bom produto, atendeu bem."],
    3: ["É ok, nada demais.", "Atende, mas esperava um acabamento melhor."],
    2: ["Veio com um pequeno defeito, trocaram na loja.", "Tamanho menor do que eu imaginava."],
    1: ["Não gostei, a qualidade deixou a desejar.", "Quebrou na primeira semana."],
}
DELIVERY_COMMENTS = {5: "Entregador educado e chegou antes do prazo.", 4: "Chegou no prazo, tudo certo.",
                     3: "Chegou, mas demoraram para avisar.", 2: "Atrasou dois dias.", 1: "Atrasou muito e ninguém avisou."}
WEIGHTS = [(5, 45), (4, 30), (3, 12), (2, 8), (1, 5)]


def _rating(bias=0):
    value = random.choices([r for r, _ in WEIGHTS], weights=[w for _, w in WEIGHTS])[0]
    return max(1, min(5, value + bias))


class Command(BaseCommand):
    help = "Cria avaliações e entregas de exemplo a partir das vendas existentes (uma vez por conta)."

    def add_arguments(self, parser):
        parser.add_argument("--account", default="loja-demo", help="Slug da conta (padrão: loja-demo).")

    def handle(self, *args, **options):
        random.seed(7)
        account = Account.objects.filter(slug=options["account"]).first()
        if account is None:
            raise CommandError(f"Conta {options['account']} não existe.")
        if Review.all_objects.filter(account=account).exists():
            self.stdout.write(self.style.WARNING("A conta já tem avaliações. Nada a fazer."))
            return
        sales = list(Sale.all_objects.filter(account=account, status=Sale.Status.COMPLETED, customer__isnull=False,
                                             deleted_at__isnull=True).select_related("customer").order_by("completed_at"))
        now = timezone.now()
        with transaction.atomic():
            deliveries = self.deliveries(account, sales, now)
            count = self.reviews(account, sales, now)
        self.stdout.write(self.style.SUCCESS(f"{deliveries} entrega(s) e {count} avaliação(ões) de exemplo criadas."))

    def deliveries(self, account, sales, now):
        """Metade das vendas com cliente que tem endereço e ainda não é entrega vira entrega."""
        made = 0
        for sale in sales:
            if sale.shipping_address_id or random.random() > 0.5:
                continue
            address = CustomerAddress.all_objects.filter(customer=sale.customer, deleted_at__isnull=True).first()
            if address is None:
                continue
            lead = random.choice([1, 2, 3, 5])
            shipped = sale.completed_at + timedelta(days=random.choice([0, 1]), hours=3)
            taken = lead + random.choice([-1, 0, 0, 0, 1, 3])  # a maioria no prazo; algumas atrasam
            delivered = sale.completed_at + timedelta(days=max(taken, 1), hours=5)
            on_the_way = delivered > now
            meta = {**(sale.metafields or {}), DELIVERY_KEY: {
                "table": "", "table_name": random.choice(["Entrega própria", "Transportadora parceira"]), "lead_days": lead,
                "address_label": address.label, "value": "0.00"}}
            # save() (e não update()): a venda recalcula a situação geral junto com a da entrega.
            sale.shipping_address, sale.metafields, sale.shipped_at = address, meta, min(shipped, now)
            sale.delivered_at = None if on_the_way else delivered
            sale.fulfillment_status = "shipped" if on_the_way else "delivered"
            sale.save()
            made += 1
        return made

    def reviews(self, account, sales, now):
        made = 0
        for sale in sales:
            name = public_name(sale.customer.name)
            moment = min(sale.completed_at + timedelta(days=random.randint(1, 6), hours=random.randint(1, 10)), now)
            products = {i.variant.product for i in SaleItem.all_objects.filter(
                sale=sale, status=SaleItem.Status.ACTIVE).select_related("variant__product") if i.variant_id}
            for product in products:
                if product.type == "service" or random.random() > 0.7:
                    continue
                if Review.all_objects.filter(account=account, product=product, customer=sale.customer).exists():
                    continue
                rating = _rating()
                made += self._create(account, sale, name, moment, rating, random.choice(COMMENTS[rating]),
                                     kind=Review.Kind.PRODUCT, product=product)
            if sale.shipping_address_id and sale.delivered_at and random.random() < 0.8:
                late = (sale.delivered_at - sale.completed_at).days > 3
                rating = _rating(-2 if late else 0)
                made += self._create(account, sale, name, max(moment, sale.delivered_at), rating, DELIVERY_COMMENTS[rating],
                                     kind=Review.Kind.DELIVERY)
        return made

    def _create(self, account, sale, name, moment, rating, comment, **kind):
        status = random.choices(["approved", "pending", "rejected"], weights=[80, 15, 5])[0]
        review = Review.all_objects.create(
            account=account, store_id=sale.store_id, sale=sale, customer=sale.customer, public_name=name, rating=rating,
            comment=comment, verified_purchase=True, status=status, origin=Review.Origin.LINK,
            rejection_reason="Comentário com dados pessoais" if status == "rejected" else "",
            moderated_at=moment + timedelta(hours=4) if status != "pending" else None, **kind)
        Review.all_objects.filter(pk=review.pk).update(created_at=moment)
        return 1
