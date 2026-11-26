"""Emissão de NFC-e/NF-e no TERMINAL (PDV desktop e PDV web) pelo Comunicador Fiscal ACBr
(github.com/Matheus-Matta/app-fiscal-acbr). Quem monta o INI é o PDV, a partir do "kit fiscal"
que ele baixa daqui (sem segredo) — assim o desktop emite MESMO com o servidor fora do ar:

    PDV ──GET  /pdv/fiscal-kit/──────────► emitente, série do terminal, perfis fiscais
                                            e o fiscal de cada variação
    desktop ──INI──► Comunicador Fiscal desktop (modo local, no PC do caixa) ──► SEFAZ
                     (emitente guardado nele; sem SEFAZ: contingência offline, tpEmis 9)
    web ──INI──► POST /pdv/acbr/ ──► comunicador Docker (modo nuvem, `acbr_cloud`) ──► SEFAZ
                     (o backend manda certificado A1 + CSC cifrados em cada chamada)
    PDV ──POST /sales/{id}/invoices/register/──► grava a nota aqui (na hora ou ao voltar a rede)

Numeração: cada terminal tem a SUA série (uma por modelo). Offline, dois caixas nunca
repetem número, e o servidor só acompanha o maior número usado.

O fiscal (NFC-e/NF-e) é do módulo Base: todo PDV emite. Basta a filial ligar a emissão nos dados
fiscais (`FiscalConfig.local_fiscal_enabled`) e quem opera ter `cash.manage`.
"""
import base64
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import only_digits
from starrp.models import FiscalConfig, FiscalProfile, FiscalSeries, Invoice, InvoiceItem, ProductVariant
from starrp.models.fiscal import DocumentModel, Environment

#: O mínimo do grupo `emit` do XML, com o nome que o operador conhece.
ISSUER_REQUIRED = {"cnpj": "CNPJ", "state_registration": "Inscrição estadual", "legal_name": "Razão social",
                   "street": "Logradouro", "district": "Bairro", "city": "Município",
                   "city_ibge": "Código IBGE do município", "state": "UF", "zip_code": "CEP"}
ISSUER_FIELDS = (*ISSUER_REQUIRED, "trade_name", "number", "complement", "phone", "crt")
PROFILE_FIELDS = ("name", "ncm", "cest", "cfop", "csosn", "cst_icms", "icms_rate", "pis_cst", "pis_rate",
                  "cofins_cst", "cofins_rate", "approx_tax_rate")


def issuer_of(config, store):
    """Dados fiscais completados pela loja: o que está em branco num vem do outro."""
    data = {}
    for field in ISSUER_FIELDS:
        value = getattr(config, field, "") or ""
        if not value and field != "crt":
            value = getattr(store, field, "") or ""
        data[field] = str(value).strip()
    missing = [label for field, label in ISSUER_REQUIRED.items() if not data[field]]
    if missing:
        raise BusinessError(f"Faltam dados do emitente nos dados fiscais de {config.name}: {', '.join(missing)}.",
                            code="fiscal_issuer_incomplete")
    return data


def config_for(store):
    config = store.fiscal_config
    if config is None or config.deleted_at is not None:
        raise BusinessError(f"A filial {store.name} não tem dados fiscais vinculados.", code="fiscal_config_missing")
    if config.provider != FiscalConfig.Provider.ACBRLIB:
        raise BusinessError(f"Os dados fiscais de {config.name} não usam o provedor ACBrLib.", code="fiscal_not_acbrlib")
    if not config.local_fiscal_enabled:
        raise BusinessError(f"A emissão no terminal está desligada nos dados fiscais de {config.name}.",
                            code="fiscal_local_disabled")
    if not config.certificate_file:
        raise BusinessError(f"Envie o certificado A1 nos dados fiscais de {config.name}.", code="certificate_missing")
    return config


@transaction.atomic
def terminal_series(config, terminal, model):
    """A série deste terminal para o modelo (criada na primeira vez, na próxima série livre)."""
    series = (FiscalSeries.all_objects.select_for_update()
              .filter(config=config, document_model=model, terminal=terminal, deleted_at__isnull=True).first())
    if series is None:
        used = (FiscalSeries.all_objects.filter(config=config, document_model=model, deleted_at__isnull=True)
                .aggregate(m=Max("series"))["m"]) or 1
        series = FiscalSeries.all_objects.create(account_id=config.account_id, config=config, document_model=model,
                                                 series=used + 1, terminal=terminal, origin=FiscalSeries.Origin.STORE)
    return series


def _variants(account_id):
    rows = (ProductVariant.all_objects.filter(account_id=account_id, deleted_at__isnull=True,
                                              product__deleted_at__isnull=True)
            .select_related("product").prefetch_related("barcodes"))
    out = {}
    for v in rows:
        p = v.product
        barcode = next((b.code for b in v.barcodes.all() if b.deleted_at is None and len(b.code) in (8, 12, 13, 14)
                        and b.code.isdigit()), "")
        out[str(v.pk)] = {"ncm": p.ncm, "cest": p.cest, "origin": p.origin or "0", "type": p.type,
                          "profile": str(p.fiscal_profile_id) if p.fiscal_profile_id else None, "barcode": barcode}
    return out


def emitter(store):
    """Os SEGREDOS do emitente para gravar no Comunicador Fiscal desktop (`/v1/config/emitente`, modo
    local): CNPJ + certificado A1 + CSC. UF, ambiente e modelo não se gravam lá: vão em cada emissão (kit).

    Só sai daqui para quem administra o fiscal (`fiscal.manage`), uma vez por comunicador. Depois
    disso o PDV desktop emite mandando só o documento: o A1 fica no comunicador, cifrado. O PDV web
    não usa isto: o backend manda o emitente ao comunicador em nuvem (`acbr_cloud`)."""
    config = config_for(store)
    issuer = issuer_of(config, store)
    pfx = base64.b64encode(config.certificate_bytes()).decode()
    return {
        "cnpj": "".join(ch for ch in issuer.get("cnpj", "") if ch.isdigit()),
        "certificado": {"pfx_base64": pfx, "senha": config.certificate_password},
        "csc": {"id": config.csc_id, "token": config.csc_token},
        "valid_until": config.certificate_valid_until,
    }


def kit(store, terminal):
    """Tudo que o PDV precisa para MONTAR a nota sozinho (inclusive offline): emitente, perfis,
    o fiscal de cada variação e a série do terminal. Sem segredo: certificado e CSC ficam no
    comunicador local (`emitter`) ou aqui, para o comunicador em nuvem (`acbr_cloud`)."""
    config = config_for(store)
    issuer = issuer_of(config, store)
    profiles = FiscalProfile.all_objects.filter(account_id=config.account_id, deleted_at__isnull=True, is_active=True)
    default = config.default_profile or profiles.filter(is_default=True).first()
    series = {}
    for model in DocumentModel.values:
        row = terminal_series(config, terminal, model)
        last = Invoice.all_objects.filter(store=store, document_model=model, series=row.series, deleted_at__isnull=True,
                                          number__lt=row.next_number + MAX_NUMBER_JUMP).aggregate(m=Max("number"))["m"] or 0
        # Terminal que perdeu a numeração (reinstalado) nunca recebe um número já gravado em outra venda.
        series[model] = {"series": row.series, "next_number": max(row.next_number, last + 1)}
    return {
        "config_id": str(config.pk), "environment": config.environment, "issuer": issuer,
        "simple": config.crt in {FiscalConfig.Crt.SIMPLES, FiscalConfig.Crt.SIMPLES_EXCESS},
        "offline_contingency": config.offline_contingency or config.local_fiscal_contingency,
        "certificate": {"valid_until": config.certificate_valid_until},
        "qr_base_url": config.qr_base_url, "portal_url": config.portal_url,
        "series": series,
        "default_profile": str(default.pk) if default else None,
        "profiles": {str(p.pk): {f: str(getattr(p, f)) for f in PROFILE_FIELDS} for p in profiles},
        "variants": _variants(config.account_id),
        "generated_at": timezone.now(),
    }


# Erros do comunicador que dizem com certeza que a nota NÃO saiu.
CERTAIN_FAILURES = {"documento_invalido", "configuracao"}


def _status(result):
    """`situacao` do comunicador → (status da nota, mensagem)."""
    situation = str(result.get("situacao") or "")
    reason = " ".join(filter(None, [str(result.get("cstat") or ""),
                                    str(result.get("motivo") or result.get("mensagem") or "")])).strip()
    if situation == "autorizada":
        return Invoice.Status.AUTHORIZED, ""
    if situation in ("rejeitada", "denegada"):
        return Invoice.Status.REJECTED, f"SEFAZ recusou: {reason}"
    if situation in ("contingencia", "processando"):
        return Invoice.Status.PROCESSING, reason
    certain = result.get("erro") in CERTAIN_FAILURES
    return Invoice.Status.ERROR, (reason or "Sem resposta do comunicador ACBrLib.") + (
        "" if certain else " Pode ter chegado à SEFAZ: reenviar usa o mesmo número.")


def key_digit(first43):
    """Dígito verificador da chave de acesso (módulo 11, pesos 2..9 da direita)."""
    total = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(first43)))
    rest = 11 - total % 11
    return 0 if rest >= 10 else rest


def _proof_problem(sale, config, model, series, number, totals, result):
    """Por que a "autorização" que o PDV mandou não se sustenta (S-07); vazio = confere.

    Sem consultar a SEFAZ dá para provar: a chave de acesso é desta filial e desta nota (CNPJ, modelo, série,
    número e dígito), o total da nota é o da venda e, se veio o XML, o protocolo é desta chave e autorizou."""
    key = only_digits(result.get("chave") or "")
    if len(key) != 44 or key_digit(key[:43]) != int(key[43]):
        return "chave de acesso inválida"
    if key[6:20] != only_digits(config.cnpj or "")[:14]:
        return "a chave é de outro CNPJ"
    if key[20:22] != model or int(key[22:25]) != series or int(key[25:34]) != number:
        return "a chave não é desta nota (modelo, série ou número)"
    try:
        total = Decimal(str(totals.get("total") or "0"))
    except ArithmeticError:
        return "total da nota inválido"
    if abs(total - sale.total) > Decimal("0.01"):
        return f"o total da nota (R$ {total}) não é o da venda (R$ {sale.total})"
    # Rodada 1 (P-7): só a chave e o total qualquer um monta (o algoritmo é público). AUTORIZADA exige o XML com o
    # protocolo da SEFAZ, coerente com a nota (chave, CNPJ, total). Sem ele: fica "a conferir" (PROCESSING).
    return _xml_problem(str(result.get("xml") or ""), key, config, sale)


NFE_NS = "{http://www.portalfiscal.inf.br/nfe}"


def _xml_problem(xml, key, config, sale):
    import defusedxml.ElementTree as safe_xml

    if "<protNFe" not in xml:
        return "sem o XML com o protocolo da SEFAZ"
    try:
        root = safe_xml.fromstring(xml)
    except Exception:  # noqa: BLE001 — XML quebrado ou com entidade: não confere
        return "XML da nota inválido"
    prot = root.find(f".//{NFE_NS}protNFe/{NFE_NS}infProt")
    inf = root.find(f".//{NFE_NS}infNFe")
    if prot is None or inf is None:
        return "XML sem a nota ou sem o protocolo"
    if (prot.findtext(f"{NFE_NS}chNFe") or "") != key or (inf.get("Id") or "") != f"NFe{key}":
        return "o XML é de outra chave"
    if (prot.findtext(f"{NFE_NS}cStat") or "") not in ("100", "150"):
        return "o protocolo do XML não autoriza a nota"
    if only_digits(inf.findtext(f"{NFE_NS}emit/{NFE_NS}CNPJ") or "") != only_digits(config.cnpj or "")[:14]:
        return "o XML é de outro emitente"
    try:
        total = Decimal(inf.findtext(f"{NFE_NS}total/{NFE_NS}ICMSTot/{NFE_NS}vNF") or "x")
    except ArithmeticError:
        return "XML sem o total da nota"
    if abs(total - sale.total) > Decimal("0.01"):
        return f"o total do XML (R$ {total}) não é o da venda (R$ {sale.total})"
    return ""


@transaction.atomic
def register(sale, user, data):
    """Grava (ou atualiza) a nota que o PDV emitiu: número, chave, protocolo, XML e itens.

    `data`: {document_model, series, number, environment, emission_type, issued_at, cNF,
    recipient: {document, name}, totals: {products, discount, other, approx, total},
    items: [...linhas do INI...], result: <resposta do comunicador>}.
    Chamada de novo para a mesma nota (reenvio, transmissão da contingência) só atualiza.
    """
    model = str(data.get("document_model") or "")
    if model not in DocumentModel.values:
        raise BusinessError("Modelo de nota inválido (65 = NFC-e, 55 = NF-e).", code="invoice_model")
    try:
        series, number = int(data["series"]), int(data["number"])
    except (KeyError, TypeError, ValueError):
        raise BusinessError("Informe a série e o número da nota.", code="invoice_number") from None
    if not 0 <= series <= 999 or not 1 <= number <= 999_999_999:
        raise BusinessError("Série ou número da nota fora do intervalo.", code="invoice_number")
    config = sale.store.fiscal_config
    if config is None:
        raise BusinessError("A filial não tem dados fiscais.", code="fiscal_config_missing")
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    totals = {k: _number(v) for k, v in data["totals"].items()} if isinstance(data.get("totals"), dict) else {}
    recipient = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
    rows = [row for row in data.get("items") or [] if isinstance(row, dict)] if isinstance(data.get("items"), list) else []
    status, message = _status(result)
    if status == Invoice.Status.AUTHORIZED:
        problem = _proof_problem(sale, config, model, series, number, totals, result)
        if problem:  # S-07: não vira AUTORIZADA só porque o PDV disse — fica para conferir
            status, message = Invoice.Status.PROCESSING, f"Autorização a conferir: {problem}."

    invoice = (Invoice.all_objects.select_for_update()
               .filter(store=sale.store, document_model=model, series=series, number=number, deleted_at__isnull=True)
               .first())
    if invoice is not None and invoice.sale_id != sale.pk:
        raise StateConflict(f"A nota {number} série {series} já pertence a outro pedido.", code="invoice_number_used")
    if invoice is not None and invoice.status in (Invoice.Status.AUTHORIZED, Invoice.Status.CANCELLED):
        # Final (R7-N1/N5): resposta atrasada não desfaz a autorização, o reenvio não reescreve emitente, destinatário
        # nem itens, e a nota cancelada não volta a valer.
        return invoice
    others = Invoice.all_objects.select_for_update().filter(sale=sale, document_model=model, deleted_at__isnull=True)
    if invoice is not None:
        others = others.exclude(pk=invoice.pk)
    if status in (Invoice.Status.AUTHORIZED, Invoice.Status.PROCESSING) and others.filter(
            status=Invoice.Status.AUTHORIZED).exists():
        raise StateConflict("Este pedido já tem nota autorizada deste modelo.", code="invoice_already_authorized")
    # A tentativa anterior com outro número deixa de "valer" (a constraint aceita uma nota viva por venda).
    if status in (Invoice.Status.AUTHORIZED, Invoice.Status.PROCESSING):  # rejeitada não derruba a contingência
        others.filter(status__in=[Invoice.Status.DRAFT, Invoice.Status.PROCESSING]).update(
            status=Invoice.Status.ERROR, error_message="Substituída por outra tentativa do terminal.")

    if invoice is None:
        invoice = Invoice(account_id=sale.account_id, store=sale.store, sale=sale, fiscal_config=config,
                          document_model=model, series=series, number=number, created_by=user)
        invoice.series_ref = FiscalSeries.all_objects.filter(config=config, document_model=model, series=series,
                                                             deleted_at__isnull=True).first()
    invoice.environment = str(data.get("environment") or config.environment)
    if invoice.environment not in Environment.values:
        invoice.environment = config.environment
    invoice.emission_type = Invoice.EmissionType.OFFLINE if str(data.get("emission_type")) == "9" else Invoice.EmissionType.NORMAL
    invoice.status, invoice.error_message = status, message
    invoice.provider = FiscalConfig.Provider.ACBRLIB
    invoice.provider_reference = str(data.get("reference") or "")[:120]
    invoice.recipient_document = only_digits(str(recipient.get("document") or ""))[:18]
    invoice.recipient_name = str(recipient.get("name", ""))[:180]
    invoice.products_total = totals.get("products") or 0
    invoice.discount_total = totals.get("discount") or 0
    invoice.freight_total = totals.get("other") or 0
    invoice.approx_tax_total = totals.get("approx") or 0
    invoice.total = totals.get("total") or 0
    if result.get("chave"):
        invoice.access_key = only_digits(result["chave"])
    for field, key in (("protocol", "protocolo"), ("xml", "xml"), ("qr_code_data", "qrcode"),
                       ("digest_value", "digest_value")):
        if result.get(key):
            setattr(invoice, field, str(result[key]))
    if status == Invoice.Status.AUTHORIZED and not invoice.authorized_at:
        invoice.authorized_at = parse_datetime(str(result.get("recebido_em") or "")) or timezone.now()
    invoice.payload = {**(invoice.payload or {}), "cNF": data.get("cNF"),
                       "issued_at": data.get("issued_at") or timezone.now().isoformat(),
                       "issuer": data.get("issuer") or (invoice.payload or {}).get("issuer"),
                       "operation_nature": "VENDA DE MERCADORIA", "other_expenses": str(totals.get("other") or "0.00"),
                       "acbrlib": {k: result.get(k) for k in ("situacao", "cstat", "motivo", "erro", "mensagem")}}
    invoice.updated_by = user
    invoice.save()

    if rows:
        InvoiceItem.all_objects.filter(invoice=invoice).delete()
        mine = {str(pk): variant for pk, variant in sale.items.values_list("pk", "variant_id")}
        InvoiceItem.all_objects.bulk_create([_item(invoice, sale, row, mine) for row in rows])
    if status == Invoice.Status.AUTHORIZED and sale.status == sale.Status.CANCELLED:
        _late_authorization(invoice)

    # O servidor acompanha o maior número que o terminal já usou nesta série.
    # Só a série de um terminal desta filial e sem salto absurdo (R4-09: um número 999999999 inventado acabava com
    # a série). Rejeitada também conta: o número já é desta venda (R5-04).
    FiscalSeries.all_objects.filter(
        config=config, document_model=model, series=series, terminal__store=sale.store,
        next_number__lte=number, next_number__gte=number - MAX_NUMBER_JUMP).update(next_number=number + 1)
    return invoice


def _number(value):
    try:
        number = Decimal(str(value or 0))
    except ArithmeticError:
        number = Decimal("NaN")
    if not number.is_finite() or abs(number) >= Decimal("1e11"):
        raise BusinessError("Valor inválido na nota.", code="invoice_invalid")
    return number


def _late_authorization(invoice):
    """A SEFAZ autorizou uma nota de venda já cancelada: ela vale lá e o prazo para cancelar é curto."""
    from starrp.models import Notification
    from starrp.services import notifications

    notifications.send(
        account=invoice.account, store=invoice.store, category=Notification.Category.FISCAL,
        level=Notification.Level.WARNING, permission="fiscal.manage",
        title=f"Nota {invoice.number} autorizada numa venda cancelada",
        body=f"A nota {invoice.number} série {invoice.series} foi autorizada depois do cancelamento da venda "
             f"{invoice.sale.number}: cancele a nota agora (NFC-e: 30 minutos).",
        url=f"/cadastros/vendas/{invoice.sale_id}", entity="sale", object_id=invoice.sale_id)


NUMERIC = ("quantity", "unit_price", "discount", "total", "icms_base", "icms_rate", "icms_value", "pis_rate", "pis_value",
           "cofins_rate", "cofins_value", "approx")


def _item(invoice, sale, row, mine):
    """`mine`: {item da venda: variante}. Item e produto são os DESTA venda, nunca um id qualquer."""
    row = {**row, **{k: _number(row.get(k)) for k in NUMERIC}}
    sale_item = str(row.get("sale_item") or "")
    variant = str(row.get("variant") or "")
    variants = {str(v): v for v in mine.values()}
    line = str(row.get("n") or 1)
    return InvoiceItem(
        account_id=sale.account_id, invoice=invoice, line_number=int(line) if line.isascii() and line.isdigit() and len(line) < 5 else 1,
        sale_item_id=sale_item if sale_item in mine else None,
        variant_id=mine.get(sale_item) or variants.get(variant), code=str(row.get("code", ""))[:60],
        barcode=str(row.get("barcode", ""))[:32], description=str(row.get("description", ""))[:180],
        ncm=str(row.get("ncm", ""))[:8], cest=str(row.get("cest") or "")[:7], cfop=str(row.get("cfop", ""))[:4],
        csosn=str(row.get("csosn") or "")[:3], cst_icms=str(row.get("cst_icms") or "")[:2],
        origin=str(row.get("origin") or "0")[:1], unit=str(row.get("unit") or "UN")[:6],
        quantity=row.get("quantity") or 1, unit_price=row.get("unit_price") or 0, discount=row.get("discount") or 0,
        total=row.get("total") or 0, icms_base=row.get("icms_base") or 0, icms_rate=row.get("icms_rate") or 0,
        icms_value=row.get("icms_value") or 0, pis_cst=str(row.get("pis_cst") or "49")[:2],
        pis_rate=row.get("pis_rate") or 0, pis_value=row.get("pis_value") or 0,
        cofins_cst=str(row.get("cofins_cst") or "49")[:2], cofins_rate=row.get("cofins_rate") or 0,
        cofins_value=row.get("cofins_value") or 0, approx_tax_value=row.get("approx") or 0,
    )


# --- Cadastro da filial: o que a emissão precisa e onde cada coisa vai ---------------------------------

#: Notas que um terminal pode ter emitido sem o servidor saber (dias offline) antes de o salto ser suspeito.
MAX_NUMBER_JUMP = 5000

#: O que a filial ajusta na aba "Nota fiscal" (vai para os dados fiscais vinculados a ela).
STORE_SETTINGS = ("environment", "crt", "local_fiscal_enabled", "local_fiscal_contingency", "csc_id", "csc_token",
                  "default_profile")


def _check(key, label, ok, message="", *, scope="all"):
    """Um item da lista de conferência. `scope`: all (os dois PDVs), cloud (PDV web) ou desktop."""
    return {"key": key, "label": label, "ok": bool(ok), "message": "" if ok else message, "scope": scope}


def readiness(store):
    """A conferência da emissão desta filial, para o cadastro dela: os dados fiscais vinculados, o que
    falta e o que cada PDV recebe.

    - PDV web: o backend manda tudo (emitente + A1 + CSC, cifrados) ao comunicador Docker em cada nota;
    - PDV desktop: baixa o kit (emitente, ambiente, séries, perfis — sem segredo) e, uma vez por
      comunicador, grava nele SÓ o CNPJ + A1 + CSC ("Gravar certificado no comunicador")."""
    from starrp.services import acbr_cloud

    config = store.fiscal_config if store.fiscal_config and store.fiscal_config.deleted_at is None else None
    if config is None:
        return {"config": None, "ready": False, "checks": [
            _check("config", "Dados fiscais vinculados", False,
                   "Crie os dados fiscais com o CNPJ da filial (botão abaixo) ou vincule um emitente existente.")]}

    checks = [
        _check("config", "Dados fiscais vinculados", True),
        _check("provider", "Provedor ACBrLib (Comunicador Fiscal)", config.provider == FiscalConfig.Provider.ACBRLIB,
               "Ligue a emissão no PDV: o provedor passa a ser o Comunicador Fiscal (ACBrLib)."),
        _check("enabled", "Emissão no PDV ligada", config.local_fiscal_enabled, "Ligue \"Emitir nota no PDV\"."),
    ]
    try:
        issuer_of(config, store)
        checks.append(_check("issuer", "Emitente completo (razão social, IE, endereço, IBGE, UF)", True))
    except BusinessError as error:
        checks.append(_check("issuer", "Emitente completo (razão social, IE, endereço, IBGE, UF)", False, str(error)))

    now = timezone.now()
    cert_cnpj = only_digits(config.certificate_cnpj)
    checks += [
        _check("certificate", "Certificado A1 enviado", config.certificate_file, "Envie o .pfx e a senha."),
        _check("certificate_valid", "Certificado dentro da validade",
               config.certificate_file and (not config.certificate_valid_until or config.certificate_valid_until > now),
               "O certificado venceu: envie o novo." if config.certificate_file else "Sem certificado."),
        _check("certificate_cnpj", "Certificado da mesma empresa",
               not cert_cnpj or cert_cnpj[:8] == only_digits(config.cnpj)[:8],
               f"O certificado é do CNPJ {cert_cnpj}."),
        _check("csc", "CSC da NFC-e (ID e código)", config.csc_id and config.csc_token,
               "Pegue o ID e o código do CSC no portal da SEFAZ do estado e informe aqui."),
        _check("cloud", "Comunicador em nuvem no servidor (PDV web)", acbr_cloud.configured(),
               "O servidor está sem ACBRLIB_URL, ACBRLIB_TOKEN e ACBR_E2E_KEY (deploy/acbr).", scope="cloud"),
    ]
    days = (config.certificate_valid_until - now).days if config.certificate_valid_until else None
    return {
        "config": {
            "id": str(config.pk), "name": config.name, "cnpj": config.cnpj, "legal_name": config.legal_name,
            "state": config.state or store.state, "environment": config.environment, "crt": config.crt,
            "provider": config.provider, "local_fiscal_enabled": config.local_fiscal_enabled,
            "local_fiscal_contingency": config.local_fiscal_contingency, "csc_id": config.csc_id,
            "has_csc_token": bool(config.csc_token), "has_certificate": bool(config.certificate_file),
            "certificate_name": config.certificate_name, "certificate_cnpj": config.certificate_cnpj,
            "certificate_valid_until": config.certificate_valid_until, "certificate_days": days,
            "default_profile": str(config.default_profile_id) if config.default_profile_id else None,
            "stores": [s.name for s in config.stores.all() if s.deleted_at is None],
        },
        "ready": all(c["ok"] for c in checks if c["scope"] != "cloud"),
        "cloud_ready": all(c["ok"] for c in checks),
        "checks": checks,
    }


def apply_store_settings(store, data, user=None):
    """Grava o que a aba "Nota fiscal" da filial ajustou nos dados fiscais dela (cria pelo CNPJ se faltar).
    Ligar a emissão no PDV já escolhe o provedor ACBrLib; CSC em branco mantém o atual."""
    from django.core.exceptions import ValidationError

    from starrp.services import fiscal_data

    config = store.fiscal_config if store.fiscal_config and store.fiscal_config.deleted_at is None else None
    config = config or fiscal_data.from_store(store, user)
    changed = {k: data[k] for k in STORE_SETTINGS if k in data}
    if not changed.get("csc_token"):
        changed.pop("csc_token", None)
    if "environment" in changed and changed["environment"] not in Environment.values:
        raise BusinessError("Ambiente inválido.", code="fiscal_environment")
    if "crt" in changed and changed["crt"] not in FiscalConfig.Crt.values:
        raise BusinessError("Regime tributário inválido.", code="fiscal_crt")
    if "csc_id" in changed:
        changed["csc_id"] = only_digits(str(changed["csc_id"] or ""))[:6]
    if "default_profile" in changed:
        profile = changed.pop("default_profile")
        config.default_profile = (FiscalProfile.all_objects.filter(account_id=config.account_id, pk=profile,
                                                                   deleted_at__isnull=True).first() if profile else None)
    for key in ("local_fiscal_enabled", "local_fiscal_contingency"):
        if key in changed:
            changed[key] = bool(changed[key])
    for key, value in changed.items():
        setattr(config, key, value)
    if config.local_fiscal_enabled:
        config.provider = FiscalConfig.Provider.ACBRLIB
    else:
        config.local_fiscal_contingency = False
    try:
        config.full_clean(exclude=["account", "default_profile", "certificate_file"])
    except ValidationError as error:
        raise BusinessError("; ".join(m for msgs in error.message_dict.values() for m in msgs), code="fiscal_invalid") from error
    if user is not None:
        config.updated_by = user
    config.save()
    return config
