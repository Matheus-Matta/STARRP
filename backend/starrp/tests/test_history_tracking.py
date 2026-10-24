"""Histórico em todas as models (django-simple-history) + feed sem duplicar a auditoria."""
from starrp.models import AuditLog, HISTORY_TRACKED, Product, Sale, StockBalance, StockMovement


def test_toda_model_de_negocio_tem_historico_e_os_logs_ficam_de_fora():
    for name in ("Product", "ProductVariant", "Customer", "CustomerAddress", "Sale", "SaleItem", "Payment",
                 "CashSession", "FinancialTitle", "FreightTable", "MetafieldDefinition", "Store", "UserProfile"):
        assert name in HISTORY_TRACKED
    assert not hasattr(AuditLog, "history") and not hasattr(StockMovement, "history")
    assert not hasattr(StockBalance, "history")


def test_acao_de_servico_entra_no_historico_com_quem_fez(ctx):
    """Guardar pedido não passa pelo CRUD (sem AuditLog): o histórico registra e o feed mostra."""
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    seller = ctx.user("vend", "seller", is_seller=True)
    api = ctx.client(seller)
    sale = api.post("/api/v1/sales/", {"seller": seller.pk}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/park/", {"note": "Cliente volta"}, format="json")

    record = Sale.all_objects.get(pk=sale["id"]).history.order_by("-history_date").first()
    feed = ctx.client().get(f"/api/v1/sales/{sale['id']}/history/").json()
    rows = feed["results"] if isinstance(feed, dict) else feed
    parked = [r for r in rows if any(c["key"] == "status" and c["to"] == "draft" for c in r["changes"])]

    assert record.status == "draft" and record.history_user_id == seller.pk
    assert len(parked) == 1 and parked[0]["by"] == "Vend"


def test_edicao_pela_api_aparece_uma_vez_e_o_shell_usa_o_updated_by(ctx):
    variant = ctx.product(name="Mesa", price="100.00", track_stock=False)
    api = ctx.client()
    url = f"/api/v1/catalog/products/{variant.product_id}/"
    api.patch(url, {"name": "Mesa de Centro"}, format="json")
    product = Product.all_objects.get(pk=variant.product_id)
    product.name, product.updated_by = "Mesa de Centro Madeira", ctx.admin  # fora da requisição (tarefa, shell)
    product.save()

    rows = api.get(f"{url}history/").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    renames = [c["to"] for r in rows for c in r["changes"] if c["key"] == "name"]
    last = product.history.order_by("-history_date").first()

    assert renames.count("Mesa de Centro") == 1  # auditoria e histórico da mesma edição: uma linha
    assert "Mesa de Centro Madeira" in renames and last.history_user_id == ctx.admin.pk
