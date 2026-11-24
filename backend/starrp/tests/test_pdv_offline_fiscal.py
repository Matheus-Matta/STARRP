"""PDV desktop: kit fiscal do terminal, nota emitida no terminal e venda feita offline."""
import uuid

from django.core.files.base import ContentFile

from starrp.models import Role, FiscalConfig, FiscalSeries, Invoice, Sale


def valid_key(cnpj, model, series, number, uf="35", yymm="2611", tp_emis="1", cnf="12345678"):
    """Chave de acesso no formato real (com o dígito verificador): a nota "autorizada" precisa dela (S-07)."""
    from starrp.services.fiscal_emission import key_digit

    first = f"{uf}{yymm}{cnpj}{model}{int(series):03d}{int(number):09d}{tp_emis}{cnf}"
    return first + str(key_digit(first))


def nfe_proc(key, cnpj, total, cstat="100"):
    """XML de nota autorizada (nfeProc): a nota com a chave e o protocolo da SEFAZ (rodada 1, P-7)."""
    ns = "http://www.portalfiscal.inf.br/nfe"
    return (f'<nfeProc xmlns="{ns}" versao="4.00"><NFe><infNFe Id="NFe{key}" versao="4.00">'
            f"<emit><CNPJ>{cnpj}</CNPJ></emit><total><ICMSTot><vNF>{total}</vNF></ICMSTot></total></infNFe></NFe>"
            f"<protNFe versao=\"4.00\"><infProt><chNFe>{key}</chNFe><cStat>{cstat}</cStat>"
            f"<nProt>135000000000001</nProt></infProt></protNFe></nfeProc>")


def _fiscal(ctx):
    config = FiscalConfig.all_objects.create(
        account=ctx.account, name="Matriz", legal_name="Loja Teste LTDA", cnpj="11222333000181",
        state_registration="123456789", street="Rua A", number="10", district="Centro", city="São Paulo",
        city_ibge="3550308", state="SP", zip_code="01001000", provider=FiscalConfig.Provider.ACBRLIB,
        local_fiscal_enabled=True, csc_id="1", csc_token="ABC", certificate_password="senha",
    )
    config.certificate_file.save("cert.pfx", ContentFile(b"pfx"), save=True)
    ctx.store.fiscal_config = config
    ctx.store.save(update_fields=["fiscal_config"])
    return config


def test_kit_da_serie_propria_ao_terminal_e_a_nota_emitida_no_terminal_fica_gravada(ctx):
    config = _fiscal(ctx)
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False, ncm="69120000")
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-2"}, format="json")

    kit1 = api.get("/api/v1/pdv/fiscal-kit/?installation_id=pc-1")
    kit2 = api.get("/api/v1/pdv/fiscal-kit/?installation_id=pc-2").json()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"method": str(ctx.methods["cash"].pk), "amount": "30.00"}]}, format="json")
    number = kit1.json()["series"]["65"]
    key = valid_key("11222333000181", "65", number["series"], number["next_number"])
    note = {"document_model": "65", "series": number["series"], "number": number["next_number"],
            "environment": "2", "totals": {"products": "30.00", "total": "30.00"},
            "items": [{"n": 1, "variant": str(variant.pk), "description": "Caneca", "ncm": "69120000", "cfop": "5102",
                       "quantity": "1", "unit_price": "30.00", "total": "30.00"}],
            "result": {"situacao": "autorizada", "chave": key, "protocolo": "135000000000001", "qrcode": "http://qr",
                       "xml": nfe_proc(key, "11222333000181", "30.00")}}
    first = api.post(f"/api/v1/sales/{sale['id']}/invoices/register/", note, format="json")
    again = api.post(f"/api/v1/sales/{sale['id']}/invoices/register/", note, format="json")

    assert kit1.status_code == 200, kit1.json()
    # O kit não leva segredo: certificado e CSC ficam no comunicador (gravados por quem administra).
    assert "pfx_base64" not in kit1.json()["certificate"] and "csc" not in kit1.json()
    assert str(variant.pk) in kit1.json()["variants"]
    assert kit1.json()["series"]["65"]["series"] != kit2["series"]["65"]["series"]  # cada caixa a sua série
    assert first.status_code == 200, first.json()
    assert again.status_code == 200
    invoice = Invoice.all_objects.get(sale_id=sale["id"])
    assert invoice.status == "authorized" and invoice.access_key == key and invoice.items.count() == 1
    series = FiscalSeries.all_objects.get(config=config, document_model="65", series=number["series"])
    assert series.next_number == number["next_number"] + 1


def test_kit_exige_emissao_no_terminal_ligada(ctx):
    config = _fiscal(ctx)
    FiscalConfig.all_objects.filter(pk=config.pk).update(local_fiscal_enabled=False)
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    refused = api.get("/api/v1/pdv/fiscal-kit/?installation_id=pc-1")
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "fiscal_local_disabled"


def test_venda_offline_entra_concluida_uma_vez_so_com_o_preco_praticado(ctx):
    variant = ctx.product(name="Copo", price="10.00", track_stock=False)
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    body = {"offline_id": str(uuid.uuid4()), "installation_id": "pc-1", "local_number": 1,
            "completed_at": "2026-11-13T10:00:00-03:00", "discount": "1.00",
            "items": [{"id": "a", "variant": str(variant.pk), "quantity": "2", "unit_price": "9.00", "discount": "0"}],
            "payments": [{"method": str(ctx.methods["cash"].pk), "amount": "17.00", "tendered": "20.00"}]}

    first = api.post("/api/v1/pdv/offline-sales/", body, format="json")
    again = api.post("/api/v1/pdv/offline-sales/", body, format="json")

    assert first.status_code == 201, first.json()
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    sale = Sale.all_objects.get(pk=first.json()["id"])
    assert sale.status == "completed" and str(sale.total) == "17.00" and str(sale.change_amount) == "3.00"
    assert Sale.all_objects.filter(store=ctx.store).count() == 1


def test_snapshot_traz_vitrines_categorias_e_clientes(ctx):
    variant = ctx.product(name="Caneca", price="30.00", barcode="7891234567895", track_stock=False)
    api = ctx.client()
    product = api.get(f"/api/v1/pdv/products/{variant.product_id}/")
    snap = api.get("/api/v1/pdv/catalog-snapshot/")
    assert product.status_code == 200 and product.json()["variants"][0]["id"] == str(variant.pk)
    assert snap.status_code == 200
    row = next(p for p in snap.json()["products"] if p["id"] == str(variant.product_id))
    assert row["variants"][0]["barcodes"] == ["7891234567895"] and row["variants"][0]["current_price"] == "30.00"
    assert "customers" in snap.json() and "categories" in snap.json()


def _body(ctx, variant, **extra):
    return {"offline_id": str(uuid.uuid4()), "installation_id": "pc-1", "local_number": 1,
            "items": [{"id": "a", "variant": str(variant.pk), "quantity": "1", "unit_price": "10.00", "discount": "0"}],
            "payments": [{"method": str(ctx.methods["cash"].pk), "amount": "10.00", "tendered": "10.00"}], **extra}


def test_dry_run_valida_sem_gravar_nada(ctx):
    variant = ctx.product(name="Prato", price="10.00", track_stock=False)
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    before = Sale.all_objects.count()

    ok = api.post("/api/v1/pdv/offline-sales/?dry_run=1", _body(ctx, variant, total="10.00"), format="json")
    preview = api.post("/api/v1/pdv/offline-sales/?dry_run=1", {**_body(ctx, variant), "payments": []}, format="json")
    wrong = api.post("/api/v1/pdv/offline-sales/?dry_run=1", _body(ctx, variant, total="12.00"), format="json")

    assert ok.status_code == 200 and ok.json()["status"] == "completed", ok.json()
    assert preview.status_code == 200 and preview.json()["total"] == "10.00" and preview.json()["status"] == "open"
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "offline_total_mismatch"
    assert Sale.all_objects.count() == before


def test_pedido_retomado_e_concluido_mantendo_o_numero(ctx):
    variant = ctx.product(name="Jarra", price="10.00", track_stock=False)
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    parked = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{parked['id']}/items/", {"variant": str(variant.pk), "quantity": "3"}, format="json")
    api.post(f"/api/v1/sales/{parked['id']}/park/", {}, format="json")

    done = api.post("/api/v1/pdv/offline-sales/", _body(ctx, variant, replaces=parked["id"]), format="json")

    assert done.status_code == 201, done.json()
    assert done.json()["id"] == parked["id"] and done.json()["number"] == parked["number"]
    sale = Sale.all_objects.get(pk=parked["id"])
    assert sale.status == "completed" and str(sale.total) == "10.00"
    assert sale.items.filter(status="active").count() == 1


def test_authorize_pede_gerente_e_diz_quem_autorizou(ctx):
    cashier = ctx.user("caixa9", "cashier")
    ctx.user("gerente9", "manager")
    Role.all_objects.filter(account=ctx.account, code="manager").update(max_discount_percent=50)
    Role.all_objects.filter(account=ctx.account, code="cashier").update(max_discount_percent=5)
    api = ctx.client(cashier)

    refused = api.post("/api/v1/pdv/authorize/", {"code": "sales.discount", "percent": "30"}, format="json")
    wrong = api.post("/api/v1/pdv/authorize/", {"code": "sales.discount", "percent": "30",
                                                "approval": {"username": "gerente9", "password": "x"}}, format="json")
    ok = api.post("/api/v1/pdv/authorize/", {"code": "sales.discount", "percent": "30",
                                             "approval": {"username": "gerente9", "password": "senha123"}}, format="json")

    assert refused.status_code == 403 and refused.json()["error"]["code"] == "discount_approval_required", refused.json()
    assert wrong.json()["error"]["code"] == "approval_invalid"
    assert ok.status_code == 200 and ok.json()["approver"]["username"] == "gerente9"
    assert ok.json()["max_discount_percent"] in ("50", "50.00")


def test_venda_montada_no_pc_guardada_vira_pedido_da_loja(ctx):
    variant = ctx.product(name="Bule", price="10.00", track_stock=False)
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    body = {**_body(ctx, variant), "payments": [], "park": True, "park_note": "Cliente volta depois"}

    parked = api.post("/api/v1/pdv/offline-sales/", body, format="json")

    assert parked.status_code == 201, parked.json()
    assert parked.json()["status"] == "draft" and parked.json()["total"] == "10.00"


def test_turno_inteiro_feito_sem_servidor_chega_em_ordem(ctx):
    from starrp.models import CashSession

    variant = ctx.product(name="Pote", price="10.00", track_stock=False)
    ctx.require_cash()
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    events = [
        {"event": "open", "offline_id": "t1", "register": str(ctx.register.pk), "opening_amount": "100.00",
         "installation_id": "pc-1", "opened_at": "2026-11-14T08:00:00-03:00"},
        None,  # a venda
        {"event": "movement", "offline_id": "m1", "session": "off:t1", "kind": "withdrawal", "amount": "50.00",
         "reason": "Cofre"},
        {"event": "close", "offline_id": "c1", "session": "off:t1", "counted_amount": "60.00",
         "closed_at": "2026-11-14T18:00:00-03:00"},
    ]
    for event in events:
        if event is None:
            sale = api.post("/api/v1/pdv/offline-sales/", _body(ctx, variant, cash_session="off:t1"), format="json")
            assert sale.status_code == 201, sale.json()
            continue
        first = api.post("/api/v1/pdv/offline-cash/", event, format="json")
        again = api.post("/api/v1/pdv/offline-cash/", event, format="json")
        assert first.status_code == 201, first.json()
        assert again.status_code == 200

    session = CashSession.all_objects.get(offline_id="t1")
    assert session.status == "closed" and str(session.expected_amount) == "60.00" and str(session.difference) == "0.00"
    assert session.opened_at.hour == 11  # UTC da abertura feita no terminal


def test_pre_venda_do_vendedor_cobrada_pelo_ticket_nao_duplica(ctx):
    variant = ctx.product(name="Taça", price="10.00", track_stock=False)
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    presale = {**_body(ctx, variant), "payments": [], "park": True}

    # Caixa cobrou lendo o ticket ANTES da pré-venda do vendedor chegar...
    paid = api.post("/api/v1/pdv/offline-sales/", _body(ctx, variant, presale=presale["offline_id"]), format="json")
    late = api.post("/api/v1/pdv/offline-sales/", presale, format="json")
    assert paid.status_code == 201 and late.status_code == 200 and late.json()["id"] == paid.json()["id"]

    # ...e na ordem contrária: a pré-venda chegou, o caixa conclui ELA (mesmo número).
    other = {**_body(ctx, variant), "payments": [], "park": True}
    draft = api.post("/api/v1/pdv/offline-sales/", other, format="json").json()
    done = api.post("/api/v1/pdv/offline-sales/", _body(ctx, variant, presale=other["offline_id"]), format="json").json()
    assert done["id"] == draft["id"] and done["status"] == "completed"


def test_fechamento_offline_com_diferenca_nao_trava_o_caixa(ctx):
    from starrp.models import CashSession

    ctx.require_cash()
    api = ctx.client()
    api.post("/api/v1/pdv/bootstrap/", {"installation_id": "pc-1"}, format="json")
    for event in (
        {"event": "open", "offline_id": "a1", "register": str(ctx.register.pk), "opening_amount": "100.00"},
        {"event": "close", "offline_id": "a2", "session": "off:a1", "counted_amount": "90.00"},
        {"event": "open", "offline_id": "b1", "register": str(ctx.register.pk), "opening_amount": "90.00"},
    ):
        assert api.post("/api/v1/pdv/offline-cash/", event, format="json").status_code == 201

    first = CashSession.all_objects.get(offline_id="a1")
    assert first.status == "closed" and str(first.difference) == "-10.00" and "confira" in first.approval_reason
    assert CashSession.all_objects.get(offline_id="b1").status == "open"


def test_emitente_para_o_comunicador_so_para_quem_administra_o_fiscal(ctx):
    _fiscal(ctx)
    cashier = ctx.user("caixa-emit", "cashier")
    refused = ctx.client(cashier).get("/api/v1/pdv/fiscal-emitter/")
    ok = ctx.client().get("/api/v1/pdv/fiscal-emitter/")
    assert refused.status_code == 403
    assert ok.status_code == 200 and ok.json()["certificado"]["pfx_base64"] and ok.json()["csc"]["token"] == "ABC"
    # O comunicador local guarda só os segredos: UF, ambiente e modelo vão em cada emissão (kit).
    assert not {"uf", "ambiente", "modelo", "fuso"} & set(ok.json())


def test_nota_autorizada_sem_chave_valida_ou_com_outro_total_nao_vira_autorizada(ctx):
    """S-07: o servidor não grava AUTORIZADA só porque o PDV disse."""
    _fiscal(ctx)
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"method": str(ctx.methods["cash"].pk), "amount": "30.00"}]}, format="json")

    def register(number, key, total="30.00"):
        return api.post(f"/api/v1/sales/{sale['id']}/invoices/register/", {
            "document_model": "65", "series": 900, "number": number, "environment": "2",
            "totals": {"products": total, "total": total},
            "result": {"situacao": "autorizada", "chave": key, "protocolo": "135000000000001"}}, format="json")

    fake = register(1, "3" * 44)
    other_cnpj = register(2, valid_key("99888777000166", "65", 900, 2))
    other_total = register(3, valid_key("11222333000181", "65", 900, 3), total="1.00")

    for response in (fake, other_cnpj, other_total):
        assert response.status_code == 200, response.json()
    assert not Invoice.all_objects.filter(sale_id=sale["id"], series=900, status="authorized").exists()


def test_autorizada_sem_xml_do_protocolo_ou_com_xml_de_outra_nota_fica_a_conferir(ctx):
    """Rodada 1 (P-7): chave e total válidos não bastam: precisa do XML com o protocolo, coerente."""
    _fiscal(ctx)
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"method": str(ctx.methods["cash"].pk), "amount": "30.00"}]}, format="json")

    def register(number, xml):
        key = valid_key("11222333000181", "65", 901, number)
        result = {"situacao": "autorizada", "chave": key, "protocolo": "1", **({"xml": xml(key)} if xml else {})}
        return api.post(f"/api/v1/sales/{sale['id']}/invoices/register/", {
            "document_model": "65", "series": 901, "number": number, "environment": "2",
            "totals": {"products": "30.00", "total": "30.00"}, "result": result}, format="json").json()

    def status(number):
        return Invoice.all_objects.get(sale_id=sale["id"], series=901, number=number).status

    # Cada tentativa nova substitui a anterior (vira "erro"): confere logo depois de registrar.
    for number, xml in ((1, None), (2, lambda key: nfe_proc(key, "11222333000181", "30.00", cstat="301")),
                        (3, lambda key: nfe_proc(key, "11222333000181", "1.00"))):
        register(number, xml)
        assert status(number) == "processing", number
    register(4, lambda key: nfe_proc(key, "11222333000181", "30.00"))
    assert status(4) == "authorized"
