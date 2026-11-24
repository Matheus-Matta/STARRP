"""Configurações da conta numa página só (admin) e modelos de etiqueta pré-prontos."""
from decimal import Decimal
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile

from starrp.models import CosmosUsage, LabelTemplate, StockRule, Store, StoreRule
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

    assert set(before) == {"account", "pdv", "stock", "cosmos", "plan"} and before["plan"]["stores"] >= 1
    assert saved.status_code == 200 and saved.json()["pdv"]["pdv_lock_minutes"] == 10
    for store in Store.all_objects.filter(pk__in=[ctx.store.pk, second.pk]):  # as duas usam a regra padrão
        rule = StoreRule.all_objects.get(pk=store.rule_id)
        assert rule.is_default and rule.require_seller and rule.cash_closing_tolerance == Decimal("2.00")
        assert rule.pdv_lock_minutes == 10 and rule.pdv_auto_lock
    stock = StockRule.all_objects.get(account=ctx.account, is_default=True, deleted_at__isnull=True)
    assert stock.allow_negative_stock and stock.expiry_warning_days == 15
    assert bad.status_code == 400 and forbidden.status_code == 403


def test_conversa_por_voz_so_aparece_e_pode_ser_ativada_com_modulo_cosmos(ctx):
    api = ctx.client()
    ctx.account.extra_modules = ["cosmos"]
    ctx.account.save(update_fields=["extra_modules"])

    before = api.get("/api/v1/account/settings/").json()
    saved = api.patch("/api/v1/account/settings/", {"cosmos": {"cosmos_voice_enabled": True}}, format="json")
    ctx.account.refresh_from_db()

    assert before["cosmos"]["cosmos_voice_enabled"] is False
    assert saved.status_code == 200 and saved.json()["cosmos"]["cosmos_voice_enabled"] is True
    assert ctx.account.cosmos_voice_enabled is True
    assert api.get("/api/v1/cosmos/status/").json()["voice_enabled"] is True

    ctx.account.extra_modules = []
    ctx.account.save(update_fields=["extra_modules"])
    hidden = api.get("/api/v1/account/settings/").json()["cosmos"]
    api.patch("/api/v1/account/settings/", {"cosmos": {"cosmos_voice_enabled": False}}, format="json")
    ctx.account.refresh_from_db()

    assert "cosmos_voice_enabled" not in hidden
    assert ctx.account.cosmos_voice_enabled is True  # campo escondido também não aceita alteração forjada
    assert api.get("/api/v1/cosmos/status/").json()["voice_enabled"] is False


def test_audio_da_voz_e_transcrito_no_backend_com_permissao_e_limite(ctx, settings, monkeypatch):
    from starrp.services.cosmos import agent, voice

    ctx.account.extra_modules = ["cosmos"]
    ctx.account.cosmos_voice_enabled = True
    ctx.account.save(update_fields=["extra_modules", "cosmos_voice_enabled"])
    settings.OPENAI_API_KEY = "sk-test"
    settings.OPENAI_TRANSCRIBE_MODEL = "transcribe-test"
    calls = []
    result = SimpleNamespace(text="Mostre as vendas de hoje", usage=SimpleNamespace(
        input_tokens=12, output_tokens=4, total_tokens=16))
    fake = SimpleNamespace(audio=SimpleNamespace(
        transcriptions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs) or result)))
    monkeypatch.setattr(agent, "_client", lambda: fake)
    api = ctx.client()

    response = api.post("/api/v1/cosmos/voice/transcribe/", {
        "audio": SimpleUploadedFile("fala.webm", b"audio-opus", content_type="audio/webm;codecs=opus"),
    }, format="multipart")

    assert response.status_code == 200 and response.json()["text"] == "Mostre as vendas de hoje"
    assert calls[0]["model"] == "transcribe-test" and calls[0]["language"] == "pt"
    spent = CosmosUsage.objects.get(account=ctx.account)
    assert (spent.prompt_tokens, spent.completion_tokens, spent.total_tokens) == (12, 4, 16)

    monkeypatch.setattr(voice, "MAX_AUDIO_BYTES", 2)
    too_large = api.post("/api/v1/cosmos/voice/transcribe/", {
        "audio": SimpleUploadedFile("fala.webm", b"abc", content_type="audio/webm"),
    }, format="multipart")
    assert too_large.status_code == 400

    ctx.account.cosmos_voice_enabled = False
    ctx.account.save(update_fields=["cosmos_voice_enabled"])
    denied = api.post("/api/v1/cosmos/voice/transcribe/", {
        "audio": SimpleUploadedFile("fala.webm", b"audio", content_type="audio/webm"),
    }, format="multipart")
    assert denied.status_code == 403


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
