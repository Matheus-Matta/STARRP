"""Configurações da conta numa página só (admin) e modelos de etiqueta pré-prontos."""
from decimal import Decimal

from starrp.models import LabelTemplate, StockSettings, Store
from starrp.services.provisioning import create_store
from starrp.services.system_data import LABEL_TEMPLATES


def test_admin_ve_e_salva_tudo_numa_pagina_e_o_pdv_vale_para_todas_as_lojas(ctx):
    second = create_store(ctx.account, "Filial")
    api = ctx.client()
    url = "/api/v1/account/settings/"
    before = api.get(url).json()
    saved = api.patch(url, {"account": {"phone": "1133334444"},
                            "pdv": {"require_seller": True, "cash_closing_tolerance": "2.00", "pdv_lock_minutes": 10},
                            "stock": {"allow_negative_stock": True, "expiry_warning_days": 15}}, format="json")
    bad = api.patch(url, {"pdv": {"pdv_lock_minutes": 999}}, format="json")
    seller = ctx.user("vend", "seller")
    forbidden = ctx.client(seller).get(url)

    assert set(before) == {"account", "pdv", "stock", "plan"} and before["plan"]["stores"] >= 1
    assert saved.status_code == 200 and saved.json()["pdv"]["pdv_lock_minutes"] == 10
    for store in Store.all_objects.filter(pk__in=[ctx.store.pk, second.pk]):
        assert store.require_seller and store.cash_closing_tolerance == Decimal("2.00")
        assert store.settings["pdv_lock_minutes"] == 10
    stock = StockSettings.all_objects.get(account=ctx.account, deleted_at__isnull=True)
    assert stock.allow_negative_stock and stock.expiry_warning_days == 15
    assert bad.status_code == 400 and forbidden.status_code == 403


def test_modelos_de_etiqueta_pre_prontos_nascem_com_a_conta_e_nao_sao_excluidos(ctx):
    presets = LabelTemplate.all_objects.filter(account=ctx.account, is_system=True)
    api = ctx.client()
    gondola = presets.get(name="Gôndola 60×40 mm")
    deleted = api.delete(f"/api/v1/stock/label-templates/{gondola.pk}/")
    mine = api.post("/api/v1/stock/label-templates/", {"name": "Minha etiqueta", "subject": "product",
                                                       "fields": ["name", "price"]}, format="json")

    assert presets.count() == len(LABEL_TEMPLATES)
    assert {p.subject for p in presets} == {"product", "lot", "bin", "volume"}
    assert deleted.status_code == 409 and mine.status_code == 201


def test_logo_da_empresa_vira_quadrado_1080_e_vai_no_me(ctx, settings, tmp_path):
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image as Pillow

    settings.MEDIA_ROOT = tmp_path
    raw = BytesIO()
    Pillow.new("RGB", (1600, 900), "#1d4ed8").save(raw, format="JPEG")
    api = ctx.client()
    sent = api.post("/api/v1/account/logo/", {"file": SimpleUploadedFile("logo.jpg", raw.getvalue(), "image/jpeg")},
                    format="multipart")
    me = api.get("/api/v1/me/").json()
    page = api.get("/api/v1/account/settings/").json()
    removed = api.delete("/api/v1/account/logo/").json()
    seller = ctx.client(ctx.user("vend", "seller")).post("/api/v1/account/logo/", {}, format="multipart")

    assert sent.status_code == 200 and (sent.json()["width"], sent.json()["height"]) == (1080, 1080)
    assert me["account"]["logo_url"] == sent.json()["logo_url"] == page["account"]["logo_url"]
    assert removed["logo_url"] is None and seller.status_code == 403
