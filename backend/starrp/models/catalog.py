"""Catálogo: categorias, marcas e o PRODUTO (cabeçalho), no modelo do StarHub.

Produto = o que o item É: nome, tipo, finalidade, fiscal, categoria.
Variante (`variants.py`) = o que se VENDE e se ESTOCA: SKU, código de barras,
preço, custo, saldo. Todo produto tem ao menos uma variante — o simples tem
uma só (a "padrão"); o com grade tem uma por combinação (P/Azul, M/Azul...).

Assim venda, estoque, lote, NF-e e etiqueta apontam sempre para a variante,
sem o "pai que não pode ser vendido" do modelo antigo (pai/filho na mesma tabela).

Três perguntas diferentes, três campos (antes era tudo `kind`):
- `type`: COMO o produto se monta — simples, com grade, kit ou serviço;
- `purpose`: PARA QUE a loja tem o item — revenda, insumo, uso e consumo...
  (é o "tipo do item" do SPED);
- `sale_method`: COMO se mede na venda — unidade, balança ou fracionado.
"""
from django.db import models

from starrp.models.base import MoneyField, PercentField, QuantityField, TenantModel, UnitCostField, alive


class Unit(models.TextChoices):
    UN = "UN", "Unidade"
    KG = "KG", "Quilo"
    G = "G", "Grama"
    L = "L", "Litro"
    ML = "ML", "Mililitro"
    M = "M", "Metro"
    M2 = "M2", "Metro quadrado"
    CX = "CX", "Caixa"
    PCT = "PCT", "Pacote"
    PAR = "PAR", "Par"


class Category(TenantModel):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.PROTECT)
    position = models.PositiveIntegerField(default=0)
    image = models.ForeignKey("starrp.Image", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    description = models.TextField(blank=True, help_text="Texto rico (HTML limpo).")
    # Loja virtual / SEO: endereço amigável e o que aparece no Google.
    slug = models.SlugField(max_length=180, blank=True, help_text="Endereço na loja virtual (gerado pelo nome).")
    seo_title = models.CharField(max_length=70, blank=True, help_text="Título no Google (até 70 caracteres).")
    seo_description = models.CharField(max_length=160, blank=True, help_text="Resumo no Google (até 160 caracteres).")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(fields=["account", "parent", "name"], condition=alive(), name="uniq_category"),
        ]

    def __str__(self):
        return self.name


class Brand(TenantModel):
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_brand")]

    def __str__(self):
        return self.name


class Product(TenantModel):
    class Type(models.TextChoices):
        SIMPLE = "simple", "Simples"
        VARIABLE = "variable", "Com variação (grade)"
        KIT = "kit", "Kit / combo"
        SERVICE = "service", "Serviço"

    class Purpose(models.TextChoices):
        # Código = "tipo do item" do SPED Fiscal (registro 0200).
        RESALE = "00", "Mercadoria para revenda"
        RAW_MATERIAL = "01", "Matéria-prima / insumo"
        PACKAGING = "02", "Embalagem"
        FINISHED = "04", "Produção própria"
        CONSUMABLE = "07", "Uso e consumo"
        ASSET = "08", "Ativo imobilizado"
        SERVICE = "09", "Serviço"
        OTHER = "99", "Outros"

    class SaleMethod(models.TextChoices):
        UNIT = "unit", "Por unidade"
        WEIGHT = "weight", "Por peso (balança)"
        FRACTION = "fraction", "Fracionado (metro, litro...)"

    type = models.CharField(max_length=10, choices=Type.choices, default=Type.SIMPLE, db_index=True)
    purpose = models.CharField(max_length=2, choices=Purpose.choices, default=Purpose.RESALE)
    sale_method = models.CharField(max_length=10, choices=SaleMethod.choices, default=SaleMethod.UNIT)
    name = models.CharField(max_length=180, db_index=True)
    reference = models.CharField(max_length=60, blank=True, help_text="Referência do modelo; base do SKU das variantes.")
    description = models.TextField(blank=True, help_text="Texto rico (HTML limpo).")
    # Loja virtual / SEO: endereço amigável e o que aparece no Google.
    slug = models.SlugField(max_length=180, blank=True, help_text="Endereço na loja virtual (gerado pelo nome).")
    seo_title = models.CharField(max_length=70, blank=True, help_text="Título no Google (até 70 caracteres).")
    seo_description = models.CharField(max_length=160, blank=True, help_text="Resumo no Google (até 160 caracteres).")
    category = models.ForeignKey(Category, null=True, blank=True, related_name="products", on_delete=models.SET_NULL)
    brand = models.ForeignKey(Brand, null=True, blank=True, related_name="products", on_delete=models.SET_NULL)
    unit = models.CharField(max_length=6, choices=Unit.choices, default=Unit.UN)
    commission_percent = PercentField(null=True, blank=True, default=None, help_text="Vazio = comissão do vendedor.")
    tags = models.ManyToManyField("starrp.Tag", related_name="products", blank=True)

    # Fiscal: NCM/CEST/origem são do produto; o perfil guarda só a regra (CFOP, CST, alíquotas).
    fiscal_profile = models.ForeignKey(
        "starrp.FiscalProfile", null=True, blank=True, related_name="products", on_delete=models.SET_NULL
    )
    ncm = models.CharField(max_length=8, blank=True)
    cest = models.CharField(max_length=7, blank=True)
    origin = models.CharField(max_length=1, default="0", help_text="Origem da mercadoria (0 = nacional).")

    # Estoque (vale para todas as variantes). Kit e serviço nunca têm saldo próprio.
    track_stock = models.BooleanField(default=True)
    track_lots = models.BooleanField(default=False, help_text="Exige lote e validade na entrada.")
    track_serial = models.BooleanField(default=False, help_text="Exige número de série por unidade.")

    is_active = models.BooleanField(default=True, db_index=True)
    # Metacampos {chave: valor}: ficha técnica personalizável (tempo de montagem, garantia...)
    # e chaves livres de integração. Ver `models/metafields.py`.
    metafields = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "reference"], condition=alive() & ~models.Q(reference=""), name="uniq_product_ref"
            ),
        ]
        indexes = [models.Index(fields=["account", "is_active", "type"])]

    def __str__(self):
        return self.name

    @property
    def keeps_stock(self):
        """Se as variantes têm saldo próprio. Kit baixa os componentes; serviço não estoca."""
        return self.track_stock and self.type not in (self.Type.KIT, self.Type.SERVICE)

    @property
    def default_variant(self):
        variants = list(self.variants.all())  # usa o prefetch da listagem
        alive_ones = [v for v in variants if v.deleted_at is None]
        return next((v for v in alive_ones if v.is_default), alive_ones[0] if alive_ones else None)


class ServiceRule(TenantModel):
    """Serviço oferecido JUNTO com o produto (montagem, garantia estendida, embalagem).

    Mesmo padrão do StarHub: o serviço é um produto do tipo "Serviço" (tem SKU, preço
    padrão e fiscal próprios) e a regra diz a QUAIS produtos ele vale e por QUANTO.
    A regra é de um tipo só — por categoria (com faixa de preço opcional, as
    subcategorias entram) ou por produto. Para cada produto vale a primeira regra
    ativa que casa, pela ordem; o preço dela, ou o padrão do serviço.
    Regras em `services/service_rules.py`.
    """

    class Kind(models.TextChoices):
        CATEGORY = "category", "Por categoria"
        PRODUCT = "product", "Por produto"

    service = models.ForeignKey(Product, related_name="service_rules", on_delete=models.CASCADE,
                                limit_choices_to={"type": "service"})
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CATEGORY)
    position = models.PositiveIntegerField(default=10, help_text="Menor primeiro: o produto que cai em duas regras "
                                                                 "fica com a de menor ordem.")
    categories = models.ManyToManyField(Category, related_name="service_rules", blank=True)
    products = models.ManyToManyField(Product, related_name="offered_services", blank=True)
    price_min = MoneyField(null=True, blank=True, default=None, help_text="Preço do produto a partir de (por categoria).")
    price_max = MoneyField(null=True, blank=True, default=None, help_text="Preço do produto até (por categoria).")
    price = MoneyField(null=True, blank=True, default=None, help_text="Preço do serviço. Vazio = o padrão do serviço.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["service__name", "position", "created_at"]

    def __str__(self):
        return f"{self.service} #{self.position}"


class KitComponent(TenantModel):
    """Composição do kit: o kit é um produto; o componente é uma VARIANTE
    (o kit leva a camiseta M Azul, não "a camiseta")."""

    kit = models.ForeignKey(Product, related_name="components", on_delete=models.CASCADE)
    component = models.ForeignKey("starrp.ProductVariant", related_name="used_in_kits", on_delete=models.PROTECT)
    quantity = QuantityField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kit", "component"], condition=alive(), name="uniq_kit_component"),
        ]


class SupplierProduct(TenantModel):
    """Como o fornecedor chama esta variante, e a conversão da unidade dele.

    É o que a NF-e de entrada usa para casar o item sozinha na próxima nota:
    "CX com 12" do fornecedor = 12 UN no estoque.
    """

    supplier = models.ForeignKey("starrp.Supplier", related_name="products", on_delete=models.CASCADE)
    variant = models.ForeignKey("starrp.ProductVariant", related_name="supplier_links", on_delete=models.CASCADE)
    supplier_code = models.CharField(max_length=60, blank=True)
    supplier_barcode = models.CharField(max_length=32, blank=True)
    supplier_description = models.CharField(max_length=255, blank=True)
    purchase_unit = models.CharField(max_length=6, blank=True)
    conversion_factor = QuantityField(max_digits=14, decimal_places=6, default=1, help_text="1 unid. compra = N estoque.")
    last_cost = UnitCostField()
    last_purchase_at = models.DateTimeField(null=True, blank=True)
    confirmed = models.BooleanField(default=True, help_text="Falso = sugestão automática ainda não conferida.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "supplier_code"],
                condition=alive() & ~models.Q(supplier_code=""),
                name="uniq_supplier_product_code",
            ),
        ]
