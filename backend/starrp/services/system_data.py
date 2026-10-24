"""Dados FIXOS do sistema que toda conta recebe ao nascer (sinal `post_save` de Account):
formas de pagamento e perfis fiscais.

A conta vê e ajusta (liga/desliga, taxa da maquininha, prazo, conta de destino),
mas criar e excluir é só do superusuário — pelo admin do Django
(`/admin/starrp/paymentmethod/`) ou pela API como superusuário.

`ensure_system_data(conta)` é idempotente: rodar de novo só cria o que falta e
nunca desfaz um ajuste que a loja fez (taxa, ativo...).
"""
from decimal import Decimal

from django.db import transaction

from starrp.models import FiscalProfile, LabelTemplate, PaymentMethod

Kind = PaymentMethod.Kind

# (nome, tipo, ajustes) — um por tipo: o PDV e os relatórios agrupam por tipo.
PAYMENT_METHODS = [
    ("Dinheiro", Kind.CASH, {"opens_drawer": True}),
    ("PIX", Kind.PIX, {"requires_reference": True}),
    ("Cartão de débito", Kind.DEBIT_CARD, {"settlement_days": 1, "fee_percent": Decimal("1.49"),
                                           "requires_reference": True}),
    ("Cartão de crédito", Kind.CREDIT_CARD, {"settlement_days": 30, "max_installments": 12,
                                             "fee_percent": Decimal("3.19"), "requires_reference": True}),
    ("Vale-refeição / alimentação", Kind.VOUCHER, {"settlement_days": 30, "fee_percent": Decimal("4.50")}),
    ("Boleto", Kind.BANK_SLIP, {"settlement_days": 3}),
    ("Vale-troca", Kind.STORE_CREDIT, {}),
    ("Crediário", Kind.INSTALLMENT_PLAN, {"max_installments": 10}),
]
REFERENCE_KINDS = [Kind.PIX, Kind.DEBIT_CARD, Kind.CREDIT_CARD]

# Modelos de etiqueta pré-prontos (tamanhos comuns no varejo). A conta ajusta e cria os seus.
LABEL_TEMPLATES = [
    {"name": "Gôndola 60×40 mm", "subject": "product", "width_mm": "60", "height_mm": "40", "code_type": "ean13",
     "font_size_pt": "9", "fields": ["name", "price", "barcode", "sku"], "is_default": True},
    {"name": "Gôndola pequena 40×25 mm", "subject": "product", "width_mm": "40", "height_mm": "25", "code_type": "ean13",
     "font_size_pt": "7", "fields": ["name", "price", "barcode"]},
    {"name": "Oferta de/por 80×50 mm", "subject": "product", "width_mm": "80", "height_mm": "50", "code_type": "ean13",
     "font_size_pt": "11", "fields": ["custom", "name", "price", "barcode"], "custom_text": "OFERTA"},
    {"name": "Tag de roupa 35×50 mm", "subject": "product", "width_mm": "35", "height_mm": "50", "code_type": "code128",
     "font_size_pt": "7", "fields": ["name", "sku", "price", "barcode"]},
    {"name": "Folha A4 3 colunas (Pimaco 6180)", "subject": "product", "width_mm": "66.7", "height_mm": "25.4",
     "margin_mm": "1.5", "columns": 3, "code_type": "ean13", "font_size_pt": "7", "fields": ["name", "price", "barcode"]},
    {"name": "Lote e validade 50×30 mm", "subject": "lot", "width_mm": "50", "height_mm": "30", "code_type": "code128",
     "font_size_pt": "7", "fields": ["name", "lot_number", "expires_at", "barcode"], "is_default": True},
    {"name": "Endereço de estoque 100×50 mm (QR)", "subject": "bin", "width_mm": "100", "height_mm": "50", "code_type": "qr",
     "font_size_pt": "14", "fields": ["bin", "warehouse", "barcode"], "is_default": True},
    {"name": "Volume / caixa 100×60 mm", "subject": "volume", "width_mm": "100", "height_mm": "60", "code_type": "code128",
     "font_size_pt": "10", "fields": ["name", "volume", "contents", "barcode"], "is_default": True},
]

# Regras de tributação mais usadas no varejo. O NCM fica no produto; aqui, CFOP/CST/alíquotas.
FISCAL_PROFILES = [
    {"name": "Simples Nacional — revenda", "cfop": "5102", "cfop_interstate": "6102", "csosn": "102",
     "approx_tax_rate": Decimal("13.45"), "is_default": True},
    {"name": "Simples Nacional — com substituição tributária", "cfop": "5405", "cfop_interstate": "6404",
     "csosn": "500", "approx_tax_rate": Decimal("13.45")},
    {"name": "Simples Nacional — produção própria", "cfop": "5101", "cfop_interstate": "6101", "csosn": "101",
     "approx_tax_rate": Decimal("13.45")},
    {"name": "Simples Nacional — não tributado", "cfop": "5102", "cfop_interstate": "6102", "csosn": "400"},
    {"name": "Regime normal — tributado (ICMS 18%)", "cfop": "5102", "cfop_interstate": "6102", "cst_icms": "00",
     "icms_rate": Decimal("18"), "pis_cst": "01", "pis_rate": Decimal("1.65"), "cofins_cst": "01",
     "cofins_rate": Decimal("7.60"), "approx_tax_rate": Decimal("31.45")},
    {"name": "Regime normal — ICMS cobrado por substituição", "cfop": "5405", "cfop_interstate": "6404",
     "cst_icms": "60", "pis_cst": "01", "pis_rate": Decimal("1.65"), "cofins_cst": "01", "cofins_rate": Decimal("7.60")},
    {"name": "Regime normal — isento de ICMS", "cfop": "5102", "cfop_interstate": "6102", "cst_icms": "40",
     "pis_cst": "07", "cofins_cst": "07"},
    {"name": "Prestação de serviço (ISS)", "cfop": "5933", "cfop_interstate": "6933", "csosn": "102",
     "approx_tax_rate": Decimal("16.33")},
    {"name": "Devolução de compra ao fornecedor", "cfop": "5202", "cfop_interstate": "6202", "csosn": "900"},
    {"name": "Venda de ativo imobilizado", "cfop": "5551", "cfop_interstate": "6551", "csosn": "400"},
]


@transaction.atomic
def ensure_system_data(account):
    """Dados fixos da conta: cargos, formas de pagamento e perfis fiscais pré-prontos."""
    from starrp.services.provisioning import ensure_system_roles, sync_permissions

    sync_permissions()
    ensure_system_roles(account)
    for position, (name, kind, extra) in enumerate(PAYMENT_METHODS):
        if not PaymentMethod.all_objects.filter(account=account, kind=kind, deleted_at__isnull=True).exists():
            PaymentMethod.all_objects.create(account=account, name=name, kind=kind, position=position, **extra)
    # Cartão e PIX sempre pedem o comprovante (NSU/autorização) — vale também para contas antigas.
    PaymentMethod.all_objects.filter(account=account, kind__in=REFERENCE_KINDS, requires_reference=False).update(
        requires_reference=True)
    for spec in FISCAL_PROFILES:
        profile, _ = FiscalProfile.all_objects.get_or_create(account=account, name=spec["name"], deleted_at=None,
                                                             defaults={**spec, "account": account, "is_system": True})
        if not profile.is_system:  # contas de antes da marcação
            FiscalProfile.all_objects.filter(pk=profile.pk).update(is_system=True)
    for spec in LABEL_TEMPLATES:
        # Padrão só onde a conta ainda não escolheu um padrão para aquele tipo de etiqueta.
        has_default = LabelTemplate.all_objects.filter(account=account, subject=spec["subject"], is_default=True,
                                                       deleted_at__isnull=True).exists()
        defaults = {**spec, "is_system": True, "is_default": spec.get("is_default", False) and not has_default}
        template, created = LabelTemplate.all_objects.get_or_create(
            account=account, name=spec["name"], deleted_at=None, defaults=defaults)
        if not created and not template.is_system:
            LabelTemplate.all_objects.filter(pk=template.pk).update(is_system=True)
