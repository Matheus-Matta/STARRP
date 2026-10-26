"""Avaliações (padrão do StarHub): o cliente dá nota de 1 a 5, comenta e manda até 3 fotos.

Duas coisas se avaliam:
- o PRODUTO (uma avaliação por cliente e produto, garantida no banco);
- a ENTREGA de uma venda (uma por venda).

Toda avaliação nasce PENDENTE e só conta como pública depois de APROVADA na moderação; a
rejeitada fica de histórico (com o motivo) e não impede o cliente de avaliar de novo.
"Compra verificada" = a avaliação veio de uma venda concluída daquele cliente.
"""
from django.db import models
from django.db.models import Q

from starrp.models.base import StoreModel, user_fk

PHOTOS_MAX = 3
COMMENT_MAX = 1500


class Review(StoreModel):
    class Kind(models.TextChoices):
        PRODUCT = "product", "Produto"
        DELIVERY = "delivery", "Entrega"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"

    class Origin(models.TextChoices):
        LINK = "link", "Link enviado ao cliente"
        BACKOFFICE = "backoffice", "Registrada na retaguarda"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PRODUCT, db_index=True)
    product = models.ForeignKey("starrp.Product", null=True, blank=True, related_name="reviews",
                                on_delete=models.PROTECT)
    sale = models.ForeignKey("starrp.Sale", null=True, blank=True, related_name="reviews", on_delete=models.SET_NULL)
    customer = models.ForeignKey("starrp.Customer", null=True, blank=True, related_name="reviews",
                                 on_delete=models.SET_NULL)
    # Foto do nome na hora do envio ("Matheus S."): se o cadastro mudar, o publicado não muda.
    public_name = models.CharField(max_length=80)
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(max_length=COMMENT_MAX, blank=True)
    photos = models.ManyToManyField("starrp.Image", related_name="+", blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = user_fk("+")
    verified_purchase = models.BooleanField(default=False)
    origin = models.CharField(max_length=12, choices=Origin.choices, default=Origin.LINK)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="review_rating_1_to_5"),
            # 1 cliente = 1 avaliação por produto (a rejeitada não conta); no banco, não num if:
            # dois envios ao mesmo tempo (duplo toque no celular) não passam os dois.
            models.UniqueConstraint(fields=["account", "product", "customer"],
                                    condition=Q(kind="product", deleted_at__isnull=True, customer__isnull=False)
                                    & ~Q(status="rejected"), name="uniq_review_product_customer"),
            models.UniqueConstraint(fields=["account", "sale"],
                                    condition=Q(kind="delivery", deleted_at__isnull=True) & ~Q(status="rejected"),
                                    name="uniq_review_delivery_sale"),
        ]
        indexes = [models.Index(fields=["account", "kind", "status", "created_at"])]

    def __str__(self):
        return f"{self.public_name} - {self.rating}/5"
