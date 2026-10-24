"""Bootstrap do PDV (desktop e móvel): uma chamada na abertura do app.

POST /pdv/bootstrap/ {"installation_id", "name", "device_type", "app_version"}

Registra/atualiza o terminal e devolve loja, formas de pagamento, caixas,
turno aberto do operador, vendedores, impressoras e balanças do terminal.
O catálogo NÃO vem aqui: o PDV o baixa paginado em /products/ e depois só o
que mudou (`?updated_after=`).
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.errors import BusinessError
from starrp.core.permissions import has_permission_code
from starrp.models import CashRegister, PaymentMethod, Printer, Scale, Terminal
from starrp.serializers import company, operations
from starrp.serializers import misc as s
from starrp.services.cash import sees_drawer, session_for_user
from starrp.services.store_access import sellers_of


class PdvBootstrapView(APIView):
    def post(self, request):
        store = request.store
        if store is None:
            raise BusinessError("Informe a loja do PDV no header X-Store-ID.", code="store_required")
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
            raise BusinessError("Este terminal pertence a outra loja.", code="terminal_other_store")
        terminal.last_seen_at = timezone.now()
        terminal.app_version = request.data.get("app_version", terminal.app_version)
        terminal.save(update_fields=["last_seen_at", "app_version", "updated_at"])

        session = session_for_user(store, request.user)
        sellers = sellers_of(store)
        # Vendedor monta e guarda pedidos; caixa (quem tem `cash.manage`) cobra, abre e fecha o turno.
        mode = "cashier" if has_permission_code(request.user, "cash.manage") else "seller"
        registers = CashRegister.objects.filter(store=store, is_active=True).prefetch_related("operators")
        if not sees_drawer(request.user):
            registers = registers.filter(operators=request.user)
        ctx = {"request": request}
        return Response({
            "mode": mode,
            "lock_minutes": int((store.settings or {}).get("pdv_lock_minutes", 5)),
            "has_cash_action_password": bool(store.cash_action_password),
            "server_time": timezone.now(),
            "store": company.StoreSerializer(store).data,
            "terminal": company.TerminalSerializer(terminal).data,
            "payment_methods": operations.PaymentMethodSerializer(
                PaymentMethod.objects.filter(Q(store__isnull=True) | Q(store=store), is_active=True), many=True
            ).data,
            # Só os caixas em que ele está vinculado (quem aprova vê todos da loja).
            "cash_registers": operations.CashRegisterSerializer(registers, many=True, context=ctx).data,
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

    def post(self, request):
        password = str(request.data.get("password", ""))
        store = request.store
        if password and (request.user.check_password(password)
                         or (store is not None and store.check_cash_action_password(password))):
            return Response({"ok": True})
        raise PermissionDenied("Senha incorreta.")


class PdvProductView(APIView):
    """Vitrine do produto no PDV (estilo loja virtual), numa chamada só:

    GET /pdv/products/{id}/ → fotos (produto + variantes), eixos da grade, variantes
    com preço vigente, saldo e fotos, e os serviços que o produto oferece
    (`services/service_rules.py`).
    """

    def get(self, request, pk):
        from django.db.models import Prefetch, Sum
        from django.shortcuts import get_object_or_404

        from starrp.core.text import plain_text
        from starrp.models import Product, ProductImage, ProductVariant, VariantValue
        from starrp.services import media, metafields, pricing
        from starrp.services.service_rules import services_for

        alive = ProductVariant.all_objects.filter(deleted_at__isnull=True, is_active=True).annotate(
            stock=Sum("balances__quantity")).prefetch_related(
            Prefetch("variant_values", VariantValue.all_objects.filter(deleted_at__isnull=True)
                     .select_related("value__attribute")), "barcodes")
        product = get_object_or_404(
            Product.all_objects.filter(account=request.account, deleted_at__isnull=True)
            .select_related("category", "brand")
            .prefetch_related(Prefetch("variants", alive, to_attr="live"),
                              Prefetch("images", ProductImage.all_objects.select_related("image"))),
            pk=pk)
        links = list(product.images.all())
        offers = pricing.offers_for(product.live, getattr(request.store, "pk", None))

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
            return {
                "id": str(v.pk), "sku": v.sku, "name": v.name or product.name, "is_default": v.is_default,
                "price": str(v.price), "current_price": str(offer.price if offer else shelf),
                "stock": None if not product.keeps_stock else str(v.stock or 0),
                "barcode": next((b.code for b in v.barcodes.all() if b.deleted_at is None), ""),
                "options": {str(vv.value.attribute_id): str(vv.value.pk) for vv in v.variant_values.all()},
                "images": [i["url"] for i in media.gallery(links, v.pk)],
            }

        return Response({
            "id": str(product.pk), "name": product.name, "type": product.type, "unit": product.unit,
            "sale_method": product.sale_method, "reference": product.reference,
            "category_name": product.category.name if product.category else None,
            "brand_name": product.brand.name if product.brand else None,
            "description": product.description,
            "specs": metafields.specs(product),
            "images": [i["url"] for i in media.gallery(links)],
            "axes": [{"id": str(pk_), "name": a["name"],
                      "values": sorted(a["values"].values(), key=lambda x: (x["position"], x["value"]))}
                     for pk_, a in sorted(axes.items(), key=lambda kv: (kv[1]["position"], kv[1]["name"]))],
            "variants": [variant_row(v) for v in product.live],
            "services": [{"variant": str(v.pk), "name": v.product.name, "sku": v.sku, "price": str(price),
                          "description": plain_text(v.product.description)[:240]}
                         for v, price, _rule in services_for(product)],
        })
