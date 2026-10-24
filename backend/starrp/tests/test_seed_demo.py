"""A demonstração roda numa conta nova (o caminho do `npm run setup -- --demo`) e enche cada cadastro."""
from django.core.management import call_command

from starrp.models import (
    Brand, CashSession, Category, Coupon, Customer, CustomerGroup, DiscountTable, FinancialTitle,
    FinancialTransaction, FiscalConfig, FiscalProfile, InboundNFe, Invoice, LabelTemplate, PaymentMethod, Product,
    Promotion, Role, Sale, StockDocument, StorageBin, Store, Supplier, UserProfile,
)


def test_demo_enche_cada_cadastro_com_pelo_menos_10(ctx, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    call_command("seed_demo", account=ctx.account.slug)
    call_command("seed_demo", account=ctx.account.slug)  # de novo: não duplica

    def count(model, **extra):
        return model.all_objects.filter(account=ctx.account, deleted_at__isnull=True, **extra).count()

    for model in (Store, FiscalConfig, UserProfile, Role, CustomerGroup, Customer, Supplier, Category, Brand, Product,
                  StorageBin, LabelTemplate, StockDocument, DiscountTable, Promotion, Coupon, CashSession, Sale,
                  FinancialTransaction, InboundNFe, Invoice, PaymentMethod, FiscalProfile):
        assert count(model) >= 10, model.__name__
    assert count(FinancialTitle, kind="payable") >= 10 and count(FinancialTitle, kind="receivable") >= 10
    assert count(Sale, status="completed") >= 30
    assert Brand.all_objects.filter(account=ctx.account, name="Aurora").count() == 1
