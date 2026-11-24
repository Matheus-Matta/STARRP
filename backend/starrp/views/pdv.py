"""Bootstrap do PDV (desktop e móvel): uma chamada na abertura do app.

POST /pdv/bootstrap/ {"installation_id", "name", "device_type", "app_version"}

Registra/atualiza o terminal e devolve loja, formas de pagamento, caixas,
turno aberto do operador, vendedores, impressoras e balanças do terminal.
O catálogo NÃO vem aqui: o PDV o baixa paginado em /products/ e depois só o
que mudou (`?updated_after=`).
"""
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.errors import BusinessError
from starrp.core.permissions import has_permission_code
from starrp.models import CashRegister, CashSession, PaymentMethod, Printer, Sale, Scale, Terminal
from starrp.serializers import rules as rules_s
from starrp.serializers import company, operations
from starrp.serializers import misc as s
from starrp.serializers import sales as sales_s
from starrp.services import acbr_cloud, approvals, fiscal_emission, offline_cash, offline_sales
from starrp.services.cash import active_session_for_user, sees_drawer
from starrp.services.sales import cents
from starrp.services.store_access import sellers_of


class PdvBootstrapView(APIView):
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)
    def post(self, request):
        _require_pdv(request)  # S-09
        store = request.store
        if store is None:
            raise BusinessError("Informe a filial do PDV no header X-Store-ID.", code="store_required")
        installation_id = (request.data.get("installation_id") or "").strip()
        if not installation_id:
            raise BusinessError("installation_id é obrigatório.")
        terminal, _ = Terminal.all_objects.get_or_create(
            account=request.account, installation_id=installation_id,
            defaults={"store": store, "name": request.data.get("name", ""),
                      "device_type": request.data.get("device_type", Terminal.DeviceType.DESKTOP)},
        )
        if not terminal.is_active:
            raise BusinessError("Este terminal foi revogado.", code="terminal_revoked")
        if terminal.store_id != store.pk:
            raise BusinessError("Este terminal pertence a outra filial.", code="terminal_other_store")
        terminal.last_seen_at = timezone.now()
        terminal.app_version = request.data.get("app_version", terminal.app_version)
        terminal.save(update_fields=["last_seen_at", "app_version", "updated_at"])

        session = active_session_for_user(store, request.user)  # aberto ou abertura esperando o gerente
        sellers = sellers_of(store)
        registers = CashRegister.objects.filter(store=store, is_active=True).select_related("operator")
        # O caixa DO usuário (um por usuário): o PDV abre nele sem perguntar.
        mine = registers.filter(operator=request.user).first()
        if not sees_drawer(request.user):
            registers = registers.filter(operator=request.user)
        # Vendedor monta e guarda pedidos; caixa cobra, abre e fecha o turno. Modo caixa = tem
        # `cash.manage` E um caixa desta loja vinculado a ele (ou um turno dele ainda aberto).
        # Com acesso mas sem caixa vinculado: entra só para criar pedidos, sem nada do caixa.
        cashier = has_permission_code(request.user, "cash.manage") and (session is not None or registers.exists())
        mode = "cashier" if cashier else "seller"
        if not cashier:
            registers, session = CashRegister.objects.none(), None
        ctx = {"request": request}
        return Response({
            "mode": mode,
            "lock_minutes": store.rule.pdv_lock_minutes if store.rule.pdv_auto_lock else 0,  # 0 = não bloqueia sozinho
            # Regras da filial (PDV, caixa, venda): a regra que esta filial usa.
            "rules": rules_s.StoreRuleSerializer(store.rule, context={"request": request}).data,
            "has_cash_action_password": bool(store.cash_action_password),
            # Limites do operador: o PDV desktop decide sozinho (offline também) o que pede gerente.
            "operator": {"max_discount_percent": str(approvals.max_discount_percent(request.user))},
            "server_time": timezone.now(),
            "store": company.StoreSerializer(store).data,
            "terminal": company.TerminalSerializer(terminal).data,
            "payment_methods": operations.PaymentMethodSerializer(
                PaymentMethod.objects.filter(Q(store__isnull=True) | Q(store=store), is_active=True), many=True
            ).data,
            # Só os caixas em que ele está vinculado (quem aprova vê todos da loja).
            "cash_registers": operations.CashRegisterSerializer(registers, many=True, context=ctx).data,
            "my_register": str(mine.pk) if mine and cashier else None,
            "cash_session": operations.CashSessionSerializer(session, context=ctx).data if session else None,
            "sees_drawer": sees_drawer(request.user),
            "sellers": [{"user_id": p.user_id, "name": p.user.get_full_name() or p.user.username,
                         "code": p.seller_code} for p in sellers],
            "printers": s.PrinterSerializer(Printer.objects.filter(store=store, is_active=True), many=True).data,
            "scales": s.ScaleSerializer(Scale.objects.filter(terminal=terminal, is_active=True), many=True).data,
        })


class PdvUnlockView(APIView):
    """Desbloqueia a tela do PDV: {"password"} — a senha do próprio operador ou a senha de
    ações do caixa da loja (a do gerente que veio liberar). Errou: 403 e fica bloqueado."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def post(self, request):
        _require_pdv(request)  # S-09
        from starrp.services import approvals, attempts

        password = str(request.data.get("password", ""))
        store = request.store
        own = ("unlock", request.user.pk)
        attempts.check(request.user.pk, own)  # S-04: limite de tentativas
        if password and request.user.check_password(password):
            attempts.succeeded(own, request.user.pk)
            return Response({"ok": True})
        if password and approvals.check_cash_password(store, password, actor=request.user):
            return Response({"ok": True})
        attempts.failed(request.user.pk, own)
        raise PermissionDenied("Senha incorreta.")


class PdvProductView(APIView):
    """Vitrine do produto no PDV (estilo loja virtual), numa chamada só:

    GET /pdv/products/{id}/ → fotos (produto + variantes), eixos da grade, variantes
    com preço vigente, saldo e fotos, e os serviços que o produto oferece
    (`services/service_rules.py`).
    """
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def get(self, request, pk):
        _require_pdv(request)  # S-09
        from django.shortcuts import get_object_or_404

        from starrp.core.text import plain_text
        from starrp.services import metafields
        from starrp.services.service_rules import services_for

        product = get_object_or_404(_products(request.account, getattr(request.store, "pk", None)), pk=pk)
        data = _product_view(product, getattr(request.store, "pk", None))
        data["specs"] = metafields.specs(product)
        data["services"] = [{"variant": str(v.pk), "name": v.product.name, "sku": v.sku, "price": str(price),
                             "description": plain_text(v.product.description)[:240]}
                            for v, price, _rule in services_for(product)]
        return Response(data)


def _products(account, store_id=None):
    """`store_id`: o saldo (`stock`) é o dos depósitos DESTA filial; sem filial, o da conta."""
    from django.db.models import Prefetch

    from starrp.models import Product, ProductImage, ProductVariant, VariantValue
    from starrp.services.stock import scoped_stock

    alive = ProductVariant.all_objects.filter(deleted_at__isnull=True, is_active=True).annotate(
        stock=scoped_stock(store_ids=[store_id] if store_id else None)).prefetch_related(
        Prefetch("variant_values", VariantValue.all_objects.filter(deleted_at__isnull=True)
                 .select_related("value__attribute")), "barcodes")
    return (Product.all_objects.filter(account=account, deleted_at__isnull=True)
            .select_related("category", "brand")
            .prefetch_related(Prefetch("variants", alive, to_attr="live"),
                              Prefetch("images", ProductImage.all_objects.select_related("image"))))


def _product_view(product, store_id, offers=None):
    """A vitrine sem ficha e serviços (o que vale online e no catálogo offline).
    `offers`: ofertas já calculadas para a lista inteira (o snapshot calcula uma vez para todos)."""
    from starrp.services import media, pricing

    links = list(product.images.all())
    if offers is None:
        offers = pricing.offers_for(product.live, store_id)
    axes = {}
    for variant in product.live:
        for vv in variant.variant_values.all():
            attr = vv.value.attribute
            axis = axes.setdefault(attr.pk, {"name": attr.name, "position": attr.position, "values": {}})
            axis["values"][str(vv.value.pk)] = {"id": str(vv.value.pk), "value": vv.value.value,
                                                 "position": vv.value.position}

    def variant_row(v):
        offer = offers.get(v.pk)
        shelf = v.promotional_price if v.promotional_price and v.promotional_price < v.price else v.price
        codes = [b.code for b in v.barcodes.all() if b.deleted_at is None]
        return {
            "id": str(v.pk), "sku": v.sku, "name": v.name or product.name, "is_default": v.is_default,
            "price": str(v.price), "current_price": str(offer.price if offer else shelf),
            "stock": None if not product.keeps_stock else str(v.stock or 0),
            "barcode": codes[0] if codes else "", "barcodes": codes, "scale_code": v.scale_code,
            "options": {str(vv.value.attribute_id): str(vv.value.pk) for vv in v.variant_values.all()},
            "images": [i["url"] for i in media.gallery(links, v.pk)],
        }

    return {
        "id": str(product.pk), "name": product.name, "type": product.type, "unit": product.unit,
        "sale_method": product.sale_method, "reference": product.reference,
        "category": str(product.category_id) if product.category_id else None,
        "category_name": product.category.name if product.category else None,
        "brand_name": product.brand.name if product.brand else None,
        "description": product.description, "is_active": product.is_active,
        "images": [i["url"] for i in media.gallery(links)],
        "axes": [{"id": str(pk_), "name": a["name"],
                  "values": sorted(a["values"].values(), key=lambda x: (x["position"], x["value"]))}
                 for pk_, a in sorted(axes.items(), key=lambda kv: (kv[1]["position"], kv[1]["name"]))],
        "variants": [variant_row(v) for v in product.live],
        "services": [], "specs": [],
    }


class PdvCatalogSnapshotView(APIView):
    """GET /pdv/catalog-snapshot/: catálogo inteiro (vitrines), categorias e clientes, para o PDV
    desktop vender quando o servidor não responder. O desktop baixa de tempos em tempos."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    MAX_CUSTOMERS = 5000

    def get(self, request):
        from starrp.models import Category, Customer

        if request.store is None:
            raise BusinessError("Informe a filial do PDV no header X-Store-ID.", code="store_required")
        _require_pdv(request)
        from starrp.services import pricing

        store_id = request.store.pk
        rows = list(_products(request.account, store_id).filter(is_active=True).exclude(type="service").order_by("name"))
        # Ofertas de TODAS as variantes numa passada (regras e vínculos buscados uma vez, não por produto).
        offers = pricing.offers_for([v for p in rows for v in p.live], store_id)
        products = [_product_view(p, store_id, offers) for p in rows]
        categories = Category.all_objects.filter(account=request.account, deleted_at__isnull=True, is_active=True)
        # A carteira de clientes (CPF, telefone, e-mail) só para quem pode ver clientes (S-09, LGPD).
        customers = (Customer.all_objects.filter(account=request.account, deleted_at__isnull=True, is_active=True)
                     .annotate(credit_total=Sum("credits__amount", filter=Q(credits__deleted_at__isnull=True)))
                     .order_by("-updated_at")[: self.MAX_CUSTOMERS]
                     if has_permission_code(request.user, "partners.view") else [])
        return Response({
            "generated_at": timezone.now(),
            "products": [{**p, "description": ""} for p in products if p["variants"]],
            "categories": [{"id": str(c.pk), "name": c.name, "parent": str(c.parent_id) if c.parent_id else None}
                           for c in categories.order_by("name")],
            "customers": [{"id": str(c.pk), "name": c.name, "document": c.document, "phone": c.phone,
                           "email": c.email, "credit_balance": str(cents(c.credit_total or 0))} for c in customers],
        })


def _require_pdv(request):
    """Quem opera o PDV (vende ou cobra): o resto da conta (estoque, logística...) não usa estas rotas (S-09)."""
    if not (has_permission_code(request.user, "sales.manage") or has_permission_code(request.user, "cash.manage")):
        raise PermissionDenied("Só quem vende ou opera o caixa usa o PDV.")


def _require_cashier(request):
    if request.store is None:
        raise BusinessError("Informe a filial do PDV no header X-Store-ID.", code="store_required")
    if not has_permission_code(request.user, "cash.manage"):
        raise PermissionDenied("Só quem opera o caixa usa esta rota.")


def _terminal(request, installation_id):
    terminal = Terminal.all_objects.filter(account=request.account, installation_id=installation_id or "",
                                           store=request.store, is_active=True).first()
    if terminal is None:
        raise BusinessError("Terminal não registrado nesta filial (abra o PDV online uma vez).", code="terminal_unknown")
    return terminal


class PdvFiscalKitView(APIView):
    """GET /pdv/fiscal-kit/?installation_id=: o kit para o PDV (desktop ou web) montar a NFC-e/NF-e
    que o Comunicador Fiscal emite, inclusive offline no desktop (`services/fiscal_emission.py`)."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def get(self, request):
        _require_cashier(request)
        terminal = _terminal(request, request.query_params.get("installation_id"))
        return Response(fiscal_emission.kit(request.store, terminal))


class PdvFiscalEmitterView(APIView):
    """GET /pdv/fiscal-emitter/: certificado A1 + CSC para gravar no Comunicador Fiscal desktop do caixa
    (`/v1/config/emitente`). Só `fiscal.manage`: o gerente/contador faz uma vez por comunicador."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def get(self, request):
        if request.store is None:
            raise BusinessError("Informe a filial do PDV no header X-Store-ID.", code="store_required")
        if not has_permission_code(request.user, "fiscal.manage"):
            raise PermissionDenied("Gravar o certificado no comunicador é de quem administra o fiscal.")
        return Response(fiscal_emission.emitter(request.store))


def _ini_sections(text):
    """INI do ACBr → {seção: {chave: valor}} (sem diferenciar maiúsculas). Chave repetida na mesma seção ou
    seção repetida é recusada: com duas, o comunicador e esta conferência poderiam ler valores diferentes."""
    sections, current = {}, None
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            if current in sections:
                raise BusinessError("INI da nota com seção repetida.", code="acbr_ini_invalid")
            sections[current] = {}
            continue
        if "=" in line and current is not None:
            key, value = (part.strip() for part in line.split("=", 1))
            if key.lower() in sections[current]:
                raise BusinessError("INI da nota com campo repetido.", code="acbr_ini_invalid")
            sections[current][key.lower()] = value
    return sections


def _store_invoice_key(request, chave):
    from starrp.models import Invoice

    key = "".join(ch for ch in str(chave or "") if ch.isdigit())
    if len(key) != 44 or not Invoice.objects.filter(store=request.store, access_key=key, deleted_at__isnull=True).exists():
        raise BusinessError("A nota não é desta filial.", code="acbr_invoice_unknown")
    return key


def _check_document(request, path, body):
    """O que o caixa pode assinar com o A1 da filial pela ponte (S-07 e rodada 1, P-8): só a nota da venda DESTA
    filial, com o total e o modelo dela; transmitir/consultar só nota que já existe na filial (o XML que vai é o
    que o servidor guardou, não um qualquer). NF-e (modelo 55) só para quem administra o fiscal."""
    from decimal import Decimal, InvalidOperation

    model = str(body.get("modelo") or "65")
    if model == "55" and not has_permission_code(request.user, "fiscal.manage"):
        raise PermissionDenied("NF-e (modelo 55) pela ponte do PDV é de quem administra o fiscal.")
    if path in ("/v1/nfe/transmitir", "/v1/nfe/consultar"):
        from starrp.models import Invoice

        key = _store_invoice_key(request, body.get("chave") or _key_in_xml(body.get("xml")))
        if path == "/v1/nfe/transmitir":
            stored = Invoice.objects.filter(store=request.store, access_key=key).values_list("xml", flat=True).first()
            if stored:
                body["xml"] = stored  # o guardado no servidor, nunca o que o navegador mandou
            elif _key_in_xml(body.get("xml")) != key:
                raise BusinessError("O XML não é desta nota.", code="acbr_invoice_unknown")
        return
    if path != "/v1/nfe/emitir":
        return
    reference = str(body.get("referencia") or "")
    sale_id = reference.split(":", 1)[0]
    sale = Sale.objects.filter(pk=sale_id, store=request.store).first() if sale_id else None
    if sale is None:
        raise BusinessError("A nota precisa ser de uma venda desta filial.", code="acbr_sale_unknown")
    ini = _ini_sections(body.get("ini"))
    if (ini.get("identificacao") or {}).get("mod", model) != model:
        raise BusinessError("O modelo do documento não é o pedido.", code="acbr_ini_invalid")
    try:
        total = Decimal((ini.get("total") or {}).get("vnf", ""))
    except InvalidOperation:
        total = None
    if total is None or abs(total - sale.total) > Decimal("0.01"):
        raise BusinessError("O total da nota não é o da venda.", code="acbr_total_mismatch")


def _key_in_xml(xml):
    import re

    match = re.search(r'Id="NFe(\d{44})"', str(xml or ""))
    return match.group(1) if match else ""


class PdvAcbrView(APIView):
    """POST /pdv/acbr/ {"path": "/v1/nfe/emitir", "body": {"ini", "tp_emis", "modelo"...}}: a ponte do
    PDV web para o Comunicador Fiscal em NUVEM (`services/acbr_cloud.py`). O backend troca o contexto
    pelo da filial (CNPJ, UF, ambiente, certificado A1, CSC), cifra, chama e devolve
    {"status", "data", "trusted"} — sempre 200 quando o pedido era válido, para o PDV decidir."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def post(self, request):
        _require_cashier(request)
        config = fiscal_emission.config_for(request.store)
        issuer = fiscal_emission.issuer_of(config, request.store)
        body = request.data.get("body")
        _check_document(request, str(request.data.get("path") or ""), body if isinstance(body, dict) else {})
        answer = acbr_cloud.pdv_call(config, issuer, str(request.data.get("path") or ""), body,
                                     fuso=(body or {}).get("fuso", "") if isinstance(body, dict) else "")
        return Response(answer.as_dict())


class PdvAcbrHealthView(APIView):
    """GET /pdv/acbr/health/: o comunicador em nuvem está no ar? (sem segredo)."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def get(self, request):
        _require_cashier(request)
        return Response(acbr_cloud.health())


class PdvOfflineSaleView(APIView):
    """POST /pdv/offline-sales/: a venda que o PDV desktop montou PRONTA (online na hora ou
    da fila offline) — `services/offline_sales.py`. Com `invoice`, grava também a nota que o
    PDV emitiu. 201 = importada; 200 = já estava. `?dry_run=1`: só valida/prévia (nada grava)."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def post(self, request):
        if request.data.get("park") and has_permission_code(request.user, "sales.manage"):
            if request.store is None:
                raise BusinessError("Informe a filial do PDV no header X-Store-ID.", code="store_required")
        else:
            _require_cashier(request)  # pedido guardado pelo vendedor não precisa ser caixa
        ctx = {"request": request}
        if request.query_params.get("dry_run") in ("1", "true"):
            def render(sale):
                sale = Sale.all_objects.prefetch_related("items", "payments__method").get(pk=sale.pk)
                return sales_s.SaleSerializer(sale, context=ctx).data
            return Response(offline_sales.preview(request.store, request.user, request.data, render))
        sale, created = offline_sales.import_sale(request.store, request.user, request.data)
        invoice = request.data.get("invoice")
        if isinstance(invoice, dict):
            fiscal_emission.register(sale, request.user, invoice)
        sale = Sale.all_objects.prefetch_related("items", "payments__method", "invoices").get(pk=sale.pk)
        return Response(sales_s.SaleSerializer(sale, context=ctx).data, status=201 if created else 200)


class PdvOfflineCashView(APIView):
    """POST /pdv/offline-cash/ {"event": "open"|"movement"|"close", "offline_id", ...}: o turno
    de caixa que o PDV desktop operou sem o servidor (`services/offline_cash.py`). 201 = gravado;
    200 = já estava."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def post(self, request):
        _require_cashier(request)
        _kind, session_or_movement, created = offline_cash.apply(request.store, request.user, request.data)
        ctx = {"request": request}
        if isinstance(session_or_movement, CashSession):
            data = operations.CashSessionSerializer(session_or_movement, context=ctx).data
        else:
            data = {"id": str(session_or_movement.pk), "status": session_or_movement.status,
                    "session": str(session_or_movement.session_id)}
        return Response(data, status=201 if created else 200)


AUTHORIZABLE = ("sales.discount", "sales.price_override", "sales.cancel_item", "sales.cancel", "cash.approve")


class PdvAuthorizeView(APIView):
    """POST /pdv/authorize/ {"code", "percent"?, "approval"?}: o PDV desktop monta a venda no
    PC e só pergunta aqui se a ação passa (e quem autorizou). Mesmos erros da venda no servidor
    (`*approval_required`, `approval_invalid`): o diálogo do gerente funciona igual.

    Devolve quem autorizou e o que ele pode, para o PDV aprender e aceitar a mesma senha
    quando o servidor estiver fora."""
    open_to_account = True  # confere por dentro (core/permissions.HasViewPermission)

    def post(self, request):
        _require_pdv(request)  # S-09
        from decimal import Decimal, InvalidOperation

        from starrp.core.permissions import has_permission_code

        code = str(request.data.get("code") or "")
        if code not in AUTHORIZABLE:
            raise BusinessError("Ação que não pede autorização.", code="authorize_unknown")
        approval = request.data.get("approval") or None
        percent = None
        if code == "sales.discount":
            try:
                percent = Decimal(str(request.data.get("percent") or 0))
            except InvalidOperation as error:
                raise BusinessError("Percentual inválido.") from error
            approver = approvals.authorize_discount(request.user, request.account, request.store, percent, approval)
        else:
            approver = approvals.authorize(request.user, request.account, request.store, code, approval)
        from starrp.services import approval_proof

        if approver is None:  # senha de ações do caixa da loja (o comprovante vale para a mesma operação)
            return Response({"approver": None, "by": "cash_password", "codes": list(AUTHORIZABLE),
                             "max_discount_percent": "0",
                             "proof": approval_proof.issue(account=request.account, store=request.store,
                                                           operator=request.user, approver=None, code=code,
                                                           max_percent=percent or 0)})

        limit = approvals.max_discount_percent(approver)
        return Response({
            "approver": {"id": approver.pk, "username": approver.username,
                         "name": approver.get_full_name() or approver.username},
            "by": "self" if approver.pk == request.user.pk else "approver",
            "codes": [c for c in AUTHORIZABLE if has_permission_code(approver, c)],
            "max_discount_percent": str(limit),
            # A venda montada no PC leva isto: prova que o servidor conferiu a senha (S-06).
            # No desconto, o comprovante vale ATÉ o percentual autorizado agora (não o limite do gerente): uma
            # autorização de 5% não cobre um desconto de 30% em outra venda.
            "proof": approval_proof.issue(account=request.account, store=request.store, operator=request.user,
                                          approver=approver, code=code,
                                          max_percent=percent if code == "sales.discount" else limit),
        })
