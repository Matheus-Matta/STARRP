"""Pedidos de antes dos endereços próprios: copia o endereço do cliente (o da entrega escolhida
ou o padrão) como entrega, e a cobrança igual à entrega (o padrão do cliente)."""
from django.db import migrations

FIELDS = ("street", "number", "complement", "district", "city", "city_ibge", "state", "zip_code", "reference")


def backfill(apps, schema_editor):
    Sale = apps.get_model("starrp", "Sale")
    SaleAddress = apps.get_model("starrp", "SaleAddress")
    CustomerAddress = apps.get_model("starrp", "CustomerAddress")
    done = set(SaleAddress._base_manager.values_list("sale_id", flat=True))
    for sale in Sale._base_manager.filter(customer__isnull=False).exclude(pk__in=done).iterator():
        address = None
        if sale.shipping_address_id:
            address = CustomerAddress._base_manager.filter(pk=sale.shipping_address_id).first()
        if address is None:
            address = (CustomerAddress._base_manager.filter(customer_id=sale.customer_id, deleted_at__isnull=True)
                       .order_by("-is_default", "label").first())
        if address is None:
            continue
        SaleAddress._base_manager.create(account_id=sale.account_id, sale=sale, kind="delivery", source=address,
                                   **{f: getattr(address, f) or "" for f in FIELDS})


class Migration(migrations.Migration):
    dependencies = [("starrp", "0019_sale_addresses")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
