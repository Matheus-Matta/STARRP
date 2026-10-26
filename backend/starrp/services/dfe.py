"""Notas de entrada pela SEFAZ (DF-e), por CNPJ dos dados fiscais.

O caminho de uma nota que um fornecedor emitiu contra a loja:

  1. `sync(config)` pede os lotes novos (por NSU). Chega um RESUMO (`resNFe`):
     vira `InboundNFe` "só resumo" (fornecedor, valor, data), sem itens.
  2. `science(nfe)` manifesta "Ciência da operação" (210210) — sem ela a SEFAZ
     não entrega o XML — e já baixa a nota completa (`download`).
     Com `dfe_auto_science` ligado isso acontece sozinho na sincronização.
  3. A nota completa (`procNFe`) passa por `inbound_nfe.import_xml`: itens,
     casamento pelo EAN e, tudo vinculado, a entrada em rascunho.
  4. Eventos (`resEvento`/`procEventoNFe`) de cancelamento marcam a nota; se
     ela já entrou no estoque, abre uma pendência (`NFeIssue`).

Regras da SEFAZ respeitadas: cStat 137 (nada novo) e 656 (consumo indevido)
mandam esperar 1 hora antes de perguntar de novo (`next_allowed_at`).
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import only_digits
from starrp.models import DFeDocument, DFeSyncState, FiscalConfig, InboundNFe, NFeEvent, NFeIssue, StockDocument
from starrp.services import inbound_nfe, sefaz

logger = logging.getLogger(__name__)

NS = {"n": sefaz.NFE_NS}
WAIT = timedelta(hours=1)
MAX_PAGES = 20  # 50 documentos por lote: até 1.000 por sincronização
CANCEL_EVENT = "110111"
MANIFESTATION = {
    "210210": InboundNFe.Manifestation.SCIENCE,
    "210200": InboundNFe.Manifestation.CONFIRMED,
    "210220": InboundNFe.Manifestation.UNKNOWN,
    "210240": InboundNFe.Manifestation.NOT_PERFORMED,
}


def _text(node, path):
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def _when(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _money(value):
    try:
        return Decimal(value or "0")
    except InvalidOperation:
        return Decimal("0")


def target_store(config):
    """A loja que recebe as notas deste CNPJ: a de mesmo CNPJ, senão a primeira vinculada."""
    stores = list(config.stores.filter(deleted_at__isnull=True).order_by("created_at"))
    same = [store for store in stores if only_digits(store.cnpj) == only_digits(config.cnpj)]
    if not stores:
        raise BusinessError(f"Vincule uma filial aos dados fiscais {config.name} para receber as notas.",
                            code="fiscal_no_store")
    return (same or stores)[0]


def _state(config):
    state, _ = DFeSyncState.all_objects.get_or_create(
        account_id=config.account_id, config=config, environment=config.environment, deleted_at=None)
    return state


def sync(config, user=None):
    """Busca o que há de novo na SEFAZ para o CNPJ e processa. Devolve um resumo
    para a tela: {"received", "notes", "cstat", "reason", "next_allowed_at"}."""
    if not config.dfe_enabled:
        raise BusinessError(f"A busca de notas está desligada nos dados fiscais {config.name}.", code="dfe_disabled")
    target_store(config)
    with transaction.atomic():
        state = DFeSyncState.all_objects.select_for_update().get(pk=_state(config).pk)
        if state.next_allowed_at and state.next_allowed_at > timezone.now():
            hour = timezone.localtime(state.next_allowed_at).strftime("%H:%M")
            raise StateConflict(f"A SEFAZ pede um intervalo: busque de novo depois das {hour}.", code="dfe_wait")
        if state.is_syncing and state.last_sync_at and timezone.now() - state.last_sync_at < timedelta(minutes=10):
            raise StateConflict("Já existe uma busca em andamento para este CNPJ.", code="dfe_running")
        state.is_syncing, state.last_sync_at = True, timezone.now()
        state.save(update_fields=["is_syncing", "last_sync_at", "updated_at"])
    received = 0
    try:
        for _ in range(MAX_PAGES):
            page = sefaz.distribution(config, last_nsu=state.last_nsu)
            state.last_cstat, state.last_reason = page.cstat, page.reason
            if page.last_nsu:
                state.last_nsu = page.last_nsu
            if page.max_nsu:
                state.max_nsu = page.max_nsu
            received += _save(config, page.documents)
            if page.cstat in ("137", "656"):
                state.next_allowed_at = timezone.now() + WAIT
                break
            if page.cstat != "138" or not page.last_nsu or int(state.last_nsu) >= int(state.max_nsu or 0):
                break
        state.error_count = 0
    except BusinessError:
        state.error_count += 1
        raise
    finally:
        state.is_syncing = False
        state.save()
    notes = process_pending(config, user)
    return {"received": received, "notes": notes, "cstat": state.last_cstat, "reason": state.last_reason,
            "next_allowed_at": state.next_allowed_at}


def _save(config, documents):
    saved = 0
    for raw in documents:
        _, created = DFeDocument.all_objects.get_or_create(
            config=config, nsu=raw.nsu,
            defaults={"account_id": config.account_id, "schema": raw.schema, "xml": raw.xml,
                      "doc_type": _doc_type(raw.schema)},
        )
        saved += created
    return saved


def _doc_type(schema):
    for kind in DFeDocument.DocType.values:
        if schema.startswith(kind):
            return kind
    return DFeDocument.DocType.UNKNOWN


def process_pending(config, user=None):
    """Processa os documentos brutos ainda pendentes, em ordem de NSU. Devolve
    quantas notas novas apareceram."""
    before = InboundNFe.all_objects.filter(fiscal_config=config).count()
    for doc in DFeDocument.all_objects.filter(config=config, processing=DFeDocument.Processing.PENDING).order_by("nsu"):
        try:
            with transaction.atomic():
                doc.processing = _process(config, doc, user)
            doc.processing_error = ""
        except (BusinessError, StateConflict, ET.ParseError) as error:
            doc.processing, doc.processing_error = DFeDocument.Processing.ERROR, str(error)[:2000]
        doc.processed_at = timezone.now()
        doc.save(update_fields=["processing", "processing_error", "processed_at", "updated_at"])
    if config.dfe_auto_science:
        for nfe in InboundNFe.all_objects.filter(
            fiscal_config=config, xml_status=InboundNFe.XmlStatus.SUMMARY_ONLY,
            manifestation=InboundNFe.Manifestation.NONE, fiscal_status=InboundNFe.FiscalStatus.AUTHORIZED,
            ignored_at__isnull=True,
        ):
            try:
                science(nfe, user)
            except (BusinessError, StateConflict) as error:
                logger.info("Ciência automática da NF-e %s falhou: %s", nfe.access_key, error)
    return InboundNFe.all_objects.filter(fiscal_config=config).count() - before


def _process(config, doc, user):
    root = ET.fromstring(doc.xml)
    if doc.doc_type == DFeDocument.DocType.RES_NFE:
        _summary(config, root, doc)
    elif doc.doc_type == DFeDocument.DocType.PROC_NFE:
        store = target_store(config)
        key = (root.find(".//n:infNFe", NS).get("Id") or "").removeprefix("NFe")
        existing = InboundNFe.all_objects.filter(account_id=config.account_id, access_key=key,
                                                 deleted_at__isnull=True).first()
        if existing is None or existing.xml_status != InboundNFe.XmlStatus.AVAILABLE:
            inbound_nfe.import_xml(existing.store if existing else store, doc.xml.encode("utf-8"), user,
                                   config=config, nsu=doc.nsu)
        doc.access_key = key
    elif doc.doc_type in (DFeDocument.DocType.RES_EVENT, DFeDocument.DocType.PROC_EVENT):
        doc.access_key = _event(config, root, doc)
    else:
        return DFeDocument.Processing.SKIPPED
    doc.save(update_fields=["access_key", "updated_at"])
    return DFeDocument.Processing.OK


def _summary(config, root, doc):
    """Resumo da NF-e: cabeçalho sem itens. cSitNFe 1 autorizada, 2 denegada, 3 cancelada."""
    key = _text(root, "n:chNFe")
    doc.access_key = key
    if InboundNFe.all_objects.filter(account_id=config.account_id, access_key=key, deleted_at__isnull=True).exists():
        return
    situation = {"1": InboundNFe.FiscalStatus.AUTHORIZED, "2": InboundNFe.FiscalStatus.DENIED,
                 "3": InboundNFe.FiscalStatus.CANCELLED}.get(_text(root, "n:cSitNFe"), InboundNFe.FiscalStatus.UNKNOWN)
    InboundNFe.all_objects.create(
        account_id=config.account_id, store=target_store(config), fiscal_config=config, access_key=key, nsu=doc.nsu,
        number=str(int(key[25:34])) if len(key) == 44 else "", series=str(int(key[22:25])) if len(key) == 44 else "",
        issued_at=_when(_text(root, "n:dhEmi")), supplier_document=_text(root, "n:CNPJ") or _text(root, "n:CPF"),
        supplier_name=_text(root, "n:xNome")[:180], recipient_document=only_digits(config.cnpj),
        total=_money(_text(root, "n:vNF")), fiscal_status=situation, summary_xml=doc.xml,
    )


def _event(config, root, doc):
    """Evento de terceiro sobre a nota. Cancelamento (110111) é o que importa."""
    key, code = _text(root, ".//n:chNFe"), _text(root, ".//n:tpEvento")
    nfe = InboundNFe.all_objects.filter(account_id=config.account_id, access_key=key, deleted_at__isnull=True).first()
    NFeEvent.all_objects.get_or_create(
        account_id=config.account_id, access_key=key, event_code=code,
        sequence=int(_text(root, ".//n:nSeqEvento") or 1), direction=NFeEvent.Direction.RECEIVED, deleted_at=None,
        defaults={"nfe": nfe, "description": (_text(root, ".//n:xEvento") or _text(root, ".//n:descEvento"))[:120],
                  "event_at": _when(_text(root, ".//n:dhEvento")), "protocol": _text(root, ".//n:nProt"),
                  "status": NFeEvent.Status.ACCEPTED, "nsu": doc.nsu, "xml": doc.xml},
    )
    if nfe is not None and code == CANCEL_EVENT:
        cancel_nfe(nfe, protocol=_text(root, ".//n:nProt"), reason=_text(root, ".//n:xJust"))
    return key


def cancel_nfe(nfe, *, protocol="", reason=""):
    """O fornecedor cancelou a nota: rascunho de entrada cai; se já entrou no
    estoque, vira pendência para alguém decidir (devolver, estornar...)."""
    if nfe.fiscal_status == InboundNFe.FiscalStatus.CANCELLED:
        return
    nfe.fiscal_status, nfe.cancelled_at = InboundNFe.FiscalStatus.CANCELLED, timezone.now()
    nfe.cancellation_protocol, nfe.cancellation_reason = protocol[:60], reason
    nfe.save(update_fields=["fiscal_status", "cancelled_at", "cancellation_protocol", "cancellation_reason",
                            "updated_at"])
    from starrp.services import stock_documents

    for doc in StockDocument.all_objects.filter(inbound_nfe=nfe, deleted_at__isnull=True):
        if doc.status == StockDocument.Status.DRAFT:
            stock_documents.cancel(doc, None, "NF-e cancelada pelo fornecedor")
        elif doc.status == StockDocument.Status.POSTED:
            NFeIssue.all_objects.get_or_create(
                account_id=nfe.account_id, nfe=nfe, kind=NFeIssue.Kind.CANCELLED_AFTER_RECEIPT,
                status=NFeIssue.Status.OPEN, deleted_at=None,
                defaults={"description": f"A NF-e {nfe.number} de {nfe.supplier_name} foi cancelada depois da "
                                         f"entrada nº {doc.number} no estoque. Confira com o fornecedor."},
            )


def _config(nfe):
    config = nfe.fiscal_config or nfe.store.fiscal_config
    if config is None:
        raise BusinessError("A filial da nota não tem dados fiscais (CNPJ e certificado).", code="fiscal_missing")
    return config


def manifest(nfe, code, user=None, reason=""):
    """Manifestação do destinatário. Fica registrada como evento enviado."""
    config = _config(nfe)
    result = sefaz.send_event(config, nfe.access_key, code, reason)
    event, _ = NFeEvent.all_objects.update_or_create(
        account_id=nfe.account_id, access_key=nfe.access_key, event_code=code, sequence=1,
        direction=NFeEvent.Direction.SENT, deleted_at=None,
        defaults={"nfe": nfe, "description": sefaz.EVENTS[code], "event_at": timezone.now(),
                  "status": NFeEvent.Status.ACCEPTED if result.accepted else NFeEvent.Status.REJECTED,
                  "protocol": result.protocol, "cstat": result.cstat, "reason": result.reason,
                  "request_xml": result.request_xml, "xml": result.response_xml, "created_by": user},
    )
    if not result.accepted:
        nfe.manifestation = InboundNFe.Manifestation.ERROR
        nfe.save(update_fields=["manifestation", "updated_at"])
        raise BusinessError(f"SEFAZ recusou a manifestação: {result.cstat} - {result.reason}", code="sefaz_rejected")
    nfe.manifestation = MANIFESTATION[code]
    nfe.save(update_fields=["manifestation", "updated_at"])
    return event


def science(nfe, user=None):
    """Ciência da operação + download do XML completo (com os itens)."""
    if nfe.manifestation in (InboundNFe.Manifestation.NONE, InboundNFe.Manifestation.ERROR):
        manifest(nfe, "210210", user)
    return download(nfe, user)


def download(nfe, user=None):
    """Pede a nota completa pela chave. Logo depois da ciência a SEFAZ pode
    ainda não ter liberado: aí a nota fica "XML pendente" e a próxima busca traz."""
    if nfe.xml_status == InboundNFe.XmlStatus.AVAILABLE:
        return nfe
    config = _config(nfe)
    page = sefaz.distribution(config, access_key=nfe.access_key)
    full = next((d for d in page.documents if d.schema.startswith("procNFe")), None)
    if full is None:
        nfe.xml_status = InboundNFe.XmlStatus.PENDING
        nfe.save(update_fields=["xml_status", "updated_at"])
        return nfe
    inbound_nfe.import_xml(nfe.store, full.xml.encode("utf-8"), user, config=config, nsu=full.nsu)
    return InboundNFe.all_objects.get(pk=nfe.pk)


def sync_all():
    """Tarefa periódica: todos os CNPJs com a busca ligada e certificado enviado."""
    results = {}
    for config in FiscalConfig.all_objects.filter(dfe_enabled=True, is_active=True, deleted_at__isnull=True).exclude(
        certificate_file=""
    ):
        try:
            results[str(config.pk)] = sync(config)
        except (BusinessError, StateConflict) as error:
            results[str(config.pk)] = {"error": str(error)}
    return results
