"""Regras de preço, desconto, cupom, isolamento entre contas e etiqueta de balança."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from starrp.models import Category, Coupon, DiscountTable, ProductVariant, Promotion, Store
from starrp.services import pricing
from starrp.services.barcodes import ean_check_digit_ok


def test_promocao_mais_antiga_vence_e_desconta_sobre_a_prateleira(ctx):
    """Duas tabelas alcançam o produto: vale a mais antiga, e o % incide sobre o promocional manual."""
    category = Category.all_objects.create(account=ctx.account, name="Roupas")
    product = ctx.product(price="20.00", promotional_price=Decimal("15.00"), category=category)
    old = DiscountTable.all_objects.create(account=ctx.account, name="Antiga")
    new = DiscountTable.all_objects.create(account=ctx.account, name="Nova")
    DiscountTable.all_objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1))
    rule = Promotion.all_objects.create(account=ctx.account, table=old, name="10% roupas", target="categories",
                                        kind="percent", value=Decimal("10"))
    rule.categories.add(category)
    Promotion.all_objects.create(account=ctx.account, table=new, name="Tudo 50%", target="all", kind="percent",
                                 value=Decimal("50"))

    quote = pricing.quote(ProductVariant.all_objects.get(pk=product.pk))

    assert quote.unit_price == Decimal("13.50")
    assert quote.promotion == rule


def test_desconto_acima_do_limite_exige_gerente(ctx):
    """Caixa com limite de 5% pede autorização; com a senha do gerente, o desconto passa."""
    cashier = ctx.user("caixa", "cashier")
    ctx.user("gerente", "manager")
    product = ctx.product(price="100.00")
    api = ctx.client(cashier)
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")

    denied = api.post(f"/api/v1/sales/{sale['id']}/discount/", {"percent": "10"}, format="json")
    allowed = api.post(f"/api/v1/sales/{sale['id']}/discount/", {
        "percent": "10", "approval": {"username": "gerente", "password": "senha123"}}, format="json")

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "discount_approval_required"
    assert allowed.status_code == 200
    assert Decimal(allowed.json()["total"]) == Decimal("90.00")


def test_cupom_respeita_minimo_e_limite_por_cpf(ctx):
    """O mínimo é sobre produtos; o mesmo CPF não usa duas vezes um cupom de uso único."""
    Coupon.all_objects.create(account=ctx.account, code="bemvindo", kind="amount", value=Decimal("10"),
                              min_subtotal=Decimal("50"), usage_limit_per_customer=1)
    product = ctx.product(price="60.00", track_stock=False)
    api = ctx.client()

    def sale_with_coupon():
        sale = api.post("/api/v1/sales/", {"customer_document": "12345678909"}, format="json").json()
        api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
        return sale, api.post(f"/api/v1/sales/{sale['id']}/coupon/", {"code": "BEMVINDO"}, format="json")

    sale, first = sale_with_coupon()
    assert first.status_code == 200 and Decimal(first.json()["total"]) == Decimal("50.00")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "50.00"}]}, format="json")

    _sale, second = sale_with_coupon()
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "coupon_rejected"


def test_conta_nao_enxerga_nem_referencia_dado_de_outra(ctx, other):
    """Isolamento: a listagem não mostra, e um FK de outra conta é recusado na venda."""
    foreign = other.product(name="Produto Alheio", price="10.00")
    api = ctx.client()

    listing = api.get("/api/v1/catalog/products/").json()
    response = api.post("/api/v1/sales/", {}, format="json").json()
    add = api.post(f"/api/v1/sales/{response['id']}/items/", {"variant": str(foreign.pk)}, format="json")

    assert all(row["id"] != str(foreign.pk) for row in listing["results"])
    assert add.status_code == 400


def test_etiqueta_de_balanca_vira_quantidade(ctx):
    """EAN-13 "2 PLU(6) VALOR(5) DV": no modo preço, R$ 12,50 de um item de R$ 25,00/kg = 0,500 kg."""
    Store.all_objects.filter(pk=ctx.store.pk).update(scale_barcode_mode="price")
    product = ctx.product(name="Queijo", price="25.00", scale_code="123", sale_method="weight", unit="KG")
    api = ctx.client()

    body = "2" + "000123" + "01250"  # prefixo + PLU + R$ 12,50 em centavos
    check = next(d for d in "0123456789" if ean_check_digit_ok(body + d))
    lookup = api.get("/api/v1/catalog/variants/lookup/", {"code": body + check}).json()

    assert lookup["id"] == str(product.pk)
    assert Decimal(lookup["scale_quantity"]) == Decimal("0.500")
