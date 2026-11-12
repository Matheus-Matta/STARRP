"""Dados de demonstração para os cadastros que o `seed_demo` não cobre.

    python manage.py seed_extras                  # conta "loja-demo"
    python manage.py seed_extras --account outra

Roda sobre uma demo já populada (precisa das vendas, produtos e lojas do `seed_demo`).
Cada parte só cria se aquele cadastro ainda estiver vazio na conta, então rodar de novo
não duplica. Cobre: regras extras entre filiais, tags, fotos, volumes, produto do
fornecedor, preço "de/por", devoluções e vale-troca, diferença de caixa, DF-e, eventos e
pendências de NF-e, divergência de recebimento, estoque endereçado com lotes, patrimônio,
impressoras, balanças, fila de impressão, notificações, links de avaliação e plano.

Fica de fora o que é só técnico (sincronização, idempotência, recuperação de senha).
"""
import random
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from starrp.management.commands.seed_demo import Api, ean13
from starrp.models import (
    Account, Asset, AssetDisposal, AssetMovement, CashDiscrepancy, CashSession, Customer, CustomerCredit, DFeDocument,
    DiscountTable, InboundNFe, LogisticsRule, NFeEvent, NFeIssue, Notification, Printer, PrintJob, Product,
    ProductImage, ProductVariant, ProductVolume, Promotion, PromotionProduct, ReceivingDivergence, ReviewLink, Sale,
    SaleReturn, Scale, ScaleReading, StockDocument, StockRule, Store, StoreRule, Supplier, SupplierProduct, Tag,
    Terminal, UserProfile, Warehouse,
)
from starrp.models.platform import Module, Plan, Subscription
from starrp.services import cash, media, returns, reviews, tags

TODAY = timezone.localdate()
COLORS = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#64748b"]


class Command(BaseCommand):
    help = "Completa a demo com os cadastros que ainda estão vazios (só cria o que falta)."

    def add_arguments(self, parser):
        parser.add_argument("--account", default="loja-demo", help="Slug da conta (padrão: loja-demo).")

    def handle(self, *args, **options):
        random.seed(11)
        account = Account.objects.filter(slug=options["account"]).first()
        if account is None:
            raise CommandError(f"Conta {options['account']} não existe.")
        profile = UserProfile.all_objects.filter(account=account, role__code="admin").select_related("user").first()
        self.account, self.admin = account, profile.user
        self.stores = list(Store.all_objects.filter(account=account, deleted_at__isnull=True).order_by("created_at"))
        self.main = self.stores[0]
        if not Product.all_objects.filter(account=account, deleted_at__isnull=True).exists():
            raise CommandError("A conta não tem produtos: rode o seed_demo antes.")
        self.api = Api(self.admin, self.main)
        self.now = timezone.now()
        for step in (self.plans, self.rules, self.tags, self.images, self.volumes, self.supplier_products,
                     self.promotion_products, self.sale_returns, self.cash_discrepancies, self.fiscal_events,
                     self.divergences, self.addressed_stock, self.assets, self.devices, self.notifications,
                     self.review_links):
            with transaction.atomic():
                done = step()
            self.stdout.write(f"  · {done}")
        self.stdout.write(self.style.SUCCESS("Cadastros que faltavam preenchidos."))

    def has(self, model, **filters):
        return model.all_objects.filter(account=self.account, **filters).exists()

    def variants(self, **filters):
        return ProductVariant.all_objects.filter(account=self.account, deleted_at__isnull=True, **filters) \
            .select_related("product").order_by("product__name", "name")

    def product(self, name):
        return Product.all_objects.get(account=self.account, name=name, deleted_at__isnull=True)

    def completed_sales(self, **filters):
        return Sale.all_objects.filter(account=self.account, status=Sale.Status.COMPLETED, deleted_at__isnull=True,
                                       **filters).order_by("completed_at")

    # ── Plano da plataforma (o que a conta contratou) ────────────────────────
    def plans(self):
        if Subscription.objects.filter(account=self.account).exists():
            return "plano: já existe, nada a fazer"
        optional = [m.value for m in Module if m != Module.BASE]
        for code, name, price, stores, users, terminals, modules in [
            ("basico", "Básico", "149.90", 1, 5, 2, []),
            ("profissional", "Profissional", "349.90", 3, 15, 6, ["stock", "finance", "fiscal"]),
            ("completo", "Completo", "799.90", 0, 0, 0, optional),
        ]:
            Plan.objects.get_or_create(code=code, defaults={
                "name": name, "monthly_price": Decimal(price), "max_stores": stores, "max_users": users,
                "max_terminals": terminals, "modules": modules})
        start = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        Subscription.objects.create(account=self.account, plan=Plan.objects.get(code="completo"),
                                    status=Subscription.Status.ACTIVE, current_period_start=start,
                                    current_period_end=start + timedelta(days=31))
        return "3 planos e a assinatura da conta no Completo"

    # ── Regras: além da padrão, uma de cada tipo para parte das filiais ───────
    def rules(self):
        if StoreRule.all_objects.filter(account=self.account, deleted_at__isnull=True).count() > 1:
            return "regras: já há mais de uma, nada a fazer"
        kiosk = StoreRule.all_objects.create(
            account=self.account, name="Lojas de shopping", description="Movimento alto: exige vendedor e bloqueia rápido.",
            require_seller=True, pdv_lock_minutes=2, cash_closing_tolerance=Decimal("0.00"))
        manual = LogisticsRule.all_objects.create(
            account=self.account, name="Conferência manual", allow_manual_conference=True,
            description="Lojas pequenas, sem leitor no recebimento: confere item a item.")
        fresh = StockRule.all_objects.create(
            account=self.account, name="Perecíveis (validade curta)", picking_strategy=StockRule.Picking.FEFO,
            expiry_warning_days=15, block_expired=True, description="Avisa 15 dias antes de vencer.")
        for store in self.stores[1:4]:
            Store.all_objects.filter(pk=store.pk).update(rule=kiosk)
        for store in self.stores[4:6]:
            Store.all_objects.filter(pk=store.pk).update(logistics_rule=manual)
        for store in self.stores[6:8]:
            Store.all_objects.filter(pk=store.pk).update(stock_rule=fresh)
        return "3 regras extras (shopping, conferência manual, perecíveis) em 7 filiais"

    # ── Tags de produto e cliente ────────────────────────────────────────────
    def tags(self):
        if self.has(Tag):
            return "tags: já existem, nada a fazer"
        for name, names in [
            ("Camiseta Básica Algodão", ["Mais vendido", "Básicos"]), ("Calça Jeans Slim", ["Básicos"]),
            ("Tênis Corrida Leve", ["Lançamento", "Esporte"]), ("Bermuda Tactel", ["Verão", "Liquidação"]),
            ("Chinelo Praia", ["Verão"]), ("Mesa de Centro Madeira", ["Entrega agendada", "Frágil"]),
            ("Jogo de Copos 6 peças", ["Frágil", "Presente"]), ("Panela Antiaderente 24cm", ["Presente"]),
            ("Cerveja Pilsen Lata 350ml", ["Gelada", "Mais vendido"]), ("Iogurte Natural 170g", ["Refrigerado"]),
            ("Requeijão Cremoso 200g", ["Refrigerado"]), ("Kit Churrasco", ["Combo", "Fim de semana"]),
        ]:
            tags.set_tags(self.product(name), names, Tag.Scope.PRODUCT, self.admin)
        customers = list(Customer.all_objects.filter(account=self.account, deleted_at__isnull=True).order_by("name"))
        options = [["VIP"], ["Atacado"], ["Compra pelo WhatsApp"], ["VIP", "Aniversário em breve"], ["Inadimplente"],
                   ["Indicação"], ["Primeira compra"], ["Compra pelo WhatsApp", "Atacado"]]
        for index, customer in enumerate(customers):
            tags.set_tags(customer, options[index % len(options)], Tag.Scope.CUSTOMER, self.admin)
        return f"{Tag.all_objects.filter(account=self.account).count()} tags em 12 produtos e {len(customers)} clientes"

    # ── Fotos: uma imagem gerada por produto (cor + nome), galeria e capa ──────
    def images(self):
        if self.has(ProductImage):
            return "fotos: já existem, nada a fazer"
        from PIL import Image as Pillow
        from PIL import ImageDraw

        products = list(Product.all_objects.filter(account=self.account, deleted_at__isnull=True).order_by("name"))
        for index, product in enumerate(products):
            picture = Pillow.new("RGB", (800, 800), COLORS[index % len(COLORS)])
            draw = ImageDraw.Draw(picture)
            draw.rectangle((60, 60, 740, 740), outline="white", width=8)
            words, lines = product.name.split(), [""]
            for word in words:  # quebra o nome em linhas de até 16 letras
                lines[-1:] = [f"{lines[-1]} {word}".strip()] if len(lines[-1]) + len(word) < 16 else [lines[-1], word]
            draw.multiline_text((400, 400), "\n".join(lines), fill="white", anchor="mm", align="center",
                                font_size=64, spacing=12)
            out = BytesIO()
            picture.save(out, format="PNG")
            image = media.store_upload(self.account, self.admin, ContentFile(out.getvalue(), name=f"{product.name}.png"),
                                       alt=product.name)
            media.sync_gallery(product, None, [{"image": image}], self.admin)
        return f"{len(products)} fotos (uma por produto)"

    # ── Volumes: móvel que vem em caixas ──────────────────────────────────────
    def volumes(self):
        if self.has(ProductVolume):
            return "volumes: já existem, nada a fazer"
        boxes = {
            "Mesa de Centro Madeira": [("Tampo", "18.5", 8, 110, 70), ("Pés e ferragens", "6.2", 15, 50, 30)],
            "Panela Antiaderente 24cm": [("Panela e tampa", "1.9", 14, 28, 28)],
            "Jogo de Copos 6 peças": [("Copos (frágil)", "2.4", 16, 30, 20)],
        }
        made = 0
        for name, rows in boxes.items():
            variant = self.variants(product__name=name).first()
            for number, (desc, weight, height, width, length) in enumerate(rows, start=1):
                ProductVolume.all_objects.create(
                    account=self.account, variant=variant, number=number, description=desc,
                    barcode=ean13(f"78920000{made + 1:04d}"), gross_weight=Decimal(weight),
                    height_cm=height, width_cm=width, length_cm=length)
                made += 1
        return f"{made} volumes em 3 produtos (mesa em 2 caixas)"

    # ── Produto do fornecedor: código e embalagem de compra ──────────────────
    def supplier_products(self):
        if self.has(SupplierProduct):
            return "produto do fornecedor: já existe, nada a fazer"
        suppliers = {s.name: s for s in Supplier.all_objects.filter(account=self.account, deleted_at__isnull=True)}
        links = [
            ("Bebidas Gela Já", "Refrigerante Cola 2L", "CX", "6", "GJ-COLA2L"),
            ("Bebidas Gela Já", "Refrigerante Guaraná 2L", "CX", "6", "GJ-GUAR2L"),
            ("Bebidas Gela Já", "Cerveja Pilsen Lata 350ml", "FD", "12", "GJ-PIL350"),
            ("Bebidas Gela Já", "Água Mineral 500ml", "FD", "12", "GJ-AGUA500"),
            ("Laticínios Fazenda Real", "Iogurte Natural 170g", "CX", "24", "FR-IOG170"),
            ("Laticínios Fazenda Real", "Requeijão Cremoso 200g", "CX", "12", "FR-REQ200"),
            ("Atacadão Bom Sabor", "Chocolate ao Leite 90g", "DP", "20", "BS-CHOC90"),
            ("Utilidades Lar Doce", "Panela Antiaderente 24cm", "UN", "1", "LD-PAN24"),
            ("Utilidades Lar Doce", "Jogo de Copos 6 peças", "UN", "1", "LD-COP6"),
            ("Móveis Casa Viva", "Mesa de Centro Madeira", "UN", "1", "CV-MC-118"),
            ("Calçados Pé Leve", "Chinelo Praia", "PR", "1", "PL-CHIN"),
        ]
        made = 0
        for supplier, name, unit, factor, code in links:
            variant = self.variants(product__name=name).first()
            if supplier not in suppliers or variant is None:
                continue
            SupplierProduct.all_objects.create(
                account=self.account, supplier=suppliers[supplier], variant=variant, supplier_code=code,
                supplier_description=f"{name.upper()} {unit} {factor}", purchase_unit=unit,
                conversion_factor=Decimal(factor), last_cost=(variant.price * Decimal("0.55")).quantize(Decimal("0.01")),
                last_purchase_at=self.now - timedelta(days=random.randint(3, 40)), confirmed=made % 5 != 4)
            made += 1
        return f"{made} códigos de fornecedor (um ainda como sugestão a conferir)"

    # ── Encarte: regra por produto com o preço "de/por" ──────────────────────
    def promotion_products(self):
        if self.has(PromotionProduct):
            return "de/por: já existe, nada a fazer"
        table = DiscountTable.all_objects.create(
            account=self.account, name="Encarte da semana", description="Ofertas com preço de/por no PDV e na etiqueta.",
            is_enabled=True, starts_at=self.now, ends_at=self.now + timedelta(days=7))
        rule = Promotion.all_objects.create(account=self.account, table=table, name="Ofertas do encarte",
                                            target=Promotion.Target.PRODUCTS, kind=Promotion.Kind.FIXED, value=0)
        offers = [("Refrigerante Cola 2L", "8.49"), ("Chocolate ao Leite 90g", "5.49"), ("Água Mineral 500ml", "1.99"),
                  ("Panela Antiaderente 24cm", "99.90"), ("Chinelo Praia", "24.90"), ("Calça Jeans Slim", "129.90")]
        for name, price in offers:
            product = self.product(name)
            PromotionProduct.all_objects.create(account=self.account, promotion=rule, product=product,
                                                promotional_price=Decimal(price),
                                                compare_at_price=product.variants.first().price)
        return f"encarte com {len(offers)} produtos de/por"

    # ── Troca e devolução: vale-troca, dinheiro, estorno e um rascunho ───────
    def sale_returns(self):
        if self.has(SaleReturn):
            return "devoluções: já existem, nada a fazer"
        with_customer = [s for s in self.completed_sales(customer__isnull=False, store=self.main).prefetch_related("items")
                         if s.items.exists()]
        plans = [(SaleReturn.Refund.STORE_CREDIT, "Tamanho não serviu", True),
                 (SaleReturn.Refund.STORE_CREDIT, "Presente repetido", True),
                 (SaleReturn.Refund.CASH, "Produto com defeito", True),
                 (SaleReturn.Refund.ORIGINAL_PAYMENT, "Arrependimento (7 dias)", True),
                 (SaleReturn.Refund.STORE_CREDIT, "Cliente vai trazer a nota amanhã", False)]
        has_cash_session = CashSession.all_objects.filter(store=self.main, opened_by=self.admin,
                                                          status=CashSession.Status.OPEN).exists()
        made = 0
        for sale, (refund, reason, finish) in zip(with_customer[::3], plans, strict=False):
            if refund == SaleReturn.Refund.CASH and not has_cash_session:
                refund = SaleReturn.Refund.STORE_CREDIT
            item = sale.items.filter(status="active").first()
            sale_return = returns.create(sale, self.admin, [{"sale_item": item, "quantity": Decimal("1"),
                                                             "restock": "defeito" not in reason}],
                                         refund_method=refund, reason=reason)
            if refund == SaleReturn.Refund.CASH:  # as vendas da demo variam: a gaveta pode não ter o bastante
                drawer = cash.session_for_user(self.main, self.admin)
                if cash.expected_cash(drawer) < sale_return.total:
                    sale_return.refund_method = SaleReturn.Refund.STORE_CREDIT
                    sale_return.save(update_fields=["refund_method", "updated_at"])
            if finish:
                returns.complete(sale_return, self.admin)
            made += 1
        # Um uso do vale-troca e um ajuste manual no extrato.
        credit = CustomerCredit.all_objects.filter(account=self.account, kind=CustomerCredit.Kind.RETURN).first()
        if credit is not None:
            CustomerCredit.all_objects.create(account=self.account, customer=credit.customer,
                                              kind=CustomerCredit.Kind.USAGE, amount=-min(credit.amount, Decimal("20")),
                                              notes="Usado numa compra no balcão")
            CustomerCredit.all_objects.create(account=self.account, customer=credit.customer,
                                              kind=CustomerCredit.Kind.ADJUSTMENT, amount=Decimal("10.00"),
                                              notes="Cortesia do gerente pelo transtorno")
        return f"{made} devoluções (vale-troca, dinheiro, estorno e um rascunho) e o extrato do vale-troca"

    # ── Diferença de caixa: dinheiro que entrou sem venda ────────────────────
    def cash_discrepancies(self):
        if self.has(CashDiscrepancy):
            return "diferenças de caixa: já existem, nada a fazer"
        sessions = list(CashSession.all_objects.filter(account=self.account, status=CashSession.Status.CLOSED)
                        .order_by("-closed_at")[:4])
        rows = [("23.50", "cash", "Pico de movimento: venda no balcão sem registro", CashDiscrepancy.Status.OPEN, ""),
                ("12.00", "cash", "Troco a mais devolvido pelo cliente", CashDiscrepancy.Status.REVIEWED,
                 "Conferido nas câmeras."),
                ("49.90", "pix", "PIX recebido sem venda vinculada", CashDiscrepancy.Status.REGULARIZED,
                 "Venda lançada pelo contador com a data do dia."),
                ("5.00", "cash", "Moeda achada na gaveta", CashDiscrepancy.Status.CANCELLED, "Era troco do dia anterior.")]
        for session, (amount, method, reason, status, note) in zip(sessions, rows, strict=False):
            resolved = status != CashDiscrepancy.Status.OPEN
            CashDiscrepancy.all_objects.create(
                account=self.account, store=session.store, session=session, amount=Decimal(amount),
                by_payment_method=[{"method": method, "amount": amount}], reason=reason, status=status,
                resolved_by=self.admin if resolved else None, resolved_at=self.now if resolved else None,
                resolution_note=note)
        return f"{len(sessions)} diferenças de caixa (aberta, analisada, regularizada, cancelada)"

    # ── Fiscal: documentos da distribuição (DF-e), eventos e pendências ──────
    def fiscal_events(self):
        if self.has(DFeDocument) or self.has(NFeEvent):
            return "DF-e e eventos: já existem, nada a fazer"
        config = self.main.fiscal_config
        nfes = list(InboundNFe.all_objects.filter(account=self.account, deleted_at__isnull=True).order_by("number"))
        for index, nfe in enumerate(nfes, start=1):
            kind = DFeDocument.DocType.PROC_NFE if index % 3 else DFeDocument.DocType.RES_NFE
            DFeDocument.all_objects.create(
                account=self.account, config=config, nsu=f"{index:015d}", schema="procNFe_v4.00.xsd",
                access_key=nfe.access_key, doc_type=kind, processing=DFeDocument.Processing.OK, processed_at=self.now,
                xml=nfe.full_xml or f"<resNFe><chNFe>{nfe.access_key}</chNFe></resNFe>")
            # Manifestação enviada: ciência em todas, confirmação nas já recebidas.
            NFeEvent.all_objects.create(
                account=self.account, nfe=nfe, access_key=nfe.access_key, direction=NFeEvent.Direction.SENT,
                event_code="210210", description="Ciência da operação", status=NFeEvent.Status.ACCEPTED,
                protocol=f"1352{index:011d}", cstat="135", reason="Evento registrado e vinculado a NF-e",
                event_at=self.now - timedelta(days=index))
        # Uma nota cancelada pelo fornecedor depois de recebida: evento recebido + pendência aberta.
        if nfes:
            cancelled = nfes[-1]
            InboundNFe.all_objects.filter(pk=cancelled.pk).update(
                fiscal_status=InboundNFe.FiscalStatus.CANCELLED, cancelled_at=self.now - timedelta(hours=5),
                cancellation_protocol="135260000009999", cancellation_reason="Erro no preço unitário")
            NFeEvent.all_objects.create(
                account=self.account, nfe=cancelled, access_key=cancelled.access_key,
                direction=NFeEvent.Direction.RECEIVED, event_code="110111", description="Cancelamento",
                status=NFeEvent.Status.ACCEPTED, protocol="135260000009999", cstat="135", nsu=f"{len(nfes) + 1:015d}",
                reason="Erro no preço unitário", event_at=self.now - timedelta(hours=5))
            NFeIssue.all_objects.create(
                account=self.account, nfe=cancelled, kind=NFeIssue.Kind.CANCELLED_AFTER_RECEIPT,
                description=f"A NF-e {cancelled.number} de {cancelled.supplier_name} foi cancelada pelo fornecedor. "
                            "Combine a devolução da mercadoria ou peça a nota substituta.")
            NFeIssue.all_objects.create(
                account=self.account, nfe=nfes[0], kind=NFeIssue.Kind.STATUS_INCONSISTENCY,
                status=NFeIssue.Status.RESOLVED, resolved_by=self.admin, resolved_at=self.now,
                description="A SEFAZ respondeu situação diferente da registrada na consulta.",
                resolution_notes="Consulta refeita: nota autorizada.")
        return f"{len(nfes)} documentos DF-e, {len(nfes) + 1} eventos e 2 pendências de NF-e"

    # ── Divergência de recebimento: o que faltou, sobrou ou veio avariado ────
    def divergences(self):
        if self.has(ReceivingDivergence):
            return "divergências: já existem, nada a fazer"
        docs = list(StockDocument.all_objects.filter(account=self.account, kind="entry", status="posted",
                                                     supplier__isnull=False).prefetch_related("items")[:6])
        reasons = [("missing", -2, "Faltaram 2 na caixa"), ("damaged", -1, "Embalagem amassada"),
                   ("extra", 1, "Veio uma a mais"), ("expired", -3, "Validade curta, recusado"),
                   ("wrong_product", -1, "Veio outro sabor"), ("missing", -1, "Faltou 1")]
        made = 0
        for doc, (reason, diff, note) in zip(docs, reasons, strict=False):
            item = doc.items.first()
            arrived = item.quantity + diff
            accepted = arrived if reason in ("missing", "extra") else item.quantity + diff
            ReceivingDivergence.all_objects.create(
                account=self.account, store=doc.store, document=doc, document_item=item, supplier=doc.supplier,
                inbound_nfe=doc.inbound_nfe, variant=item.variant, expected_quantity=item.quantity,
                arrived_quantity=item.quantity if reason in ("damaged", "expired", "wrong_product") else arrived,
                accepted_quantity=accepted, reason=reason, notes=note, mode="scan", checked_by=self.admin)
            made += 1
        return f"{made} divergências de recebimento"

    # ── Estoque endereçado (WMS) com lotes: entrada no Depósito Central ──────
    def addressed_stock(self):
        central = Warehouse.all_objects.filter(account=self.account, store=self.main, uses_bins=True).first()
        if central is None:
            return "estoque endereçado: sem depósito com endereços, nada a fazer"
        from starrp.models import BinBalance, StorageBin

        if BinBalance.all_objects.filter(account=self.account, bin__warehouse=central).count() > 2:
            return "estoque endereçado: já há saldo nos endereços, nada a fazer"
        bins = list(StorageBin.all_objects.filter(warehouse=central, deleted_at__isnull=True).order_by("sequence"))
        stocked = [v for v in self.variants(product__track_stock=True, product__type__in=["simple", "variable"])
                   if not v.product.name.endswith("(kg)")][:10]
        suppliers = list(Supplier.all_objects.filter(account=self.account, deleted_at__isnull=True)[:2])
        # Duas entradas em dias diferentes: o mais antigo sai primeiro; os perecíveis com validades diferentes.
        for days_ago, supplier, expires in [(20, suppliers[0], 25), (2, suppliers[-1], 60)]:
            items = []
            for index, variant in enumerate(stocked):
                row = {"variant": str(variant.pk), "quantity": str(random.choice([6, 12, 18])),
                       "unit_cost": f"{variant.price * Decimal('0.5'):.2f}", "bin": str(bins[index % len(bins)].pk)}
                if variant.product.track_lots:
                    row |= {"lot_number": f"C{days_ago:02d}{index}", "expires_at": (TODAY + timedelta(days=expires)).isoformat(),
                            "manufactured_at": (TODAY - timedelta(days=days_ago + 5)).isoformat()}
                items.append(row)
            doc = self.api.post("/stock/documents/", {
                "kind": "entry", "warehouse": str(central.pk), "supplier": str(supplier.pk),
                "external_number": f"98{days_ago:02d}", "effective_date": (TODAY - timedelta(days=days_ago)).isoformat(),
                "reason": "Reposição do depósito central", "items": items})
            self.api.post(f"/stock/documents/{doc['id']}/post/")
        return f"2 entradas no Depósito Central em {len(bins)} endereços, com lotes e datas de entrada diferentes"

    # ── Patrimônio: bens da loja, movimentações e baixas ─────────────────────
    def assets(self):
        if self.has(Asset):
            return "patrimônio: já existe, nada a fazer"
        places = {w.kind: w for w in Warehouse.all_objects.filter(account=self.account, store=self.main,
                                                                 deleted_at__isnull=True)}
        floor = places.get("sales_floor") or next(iter(places.values()))
        storage = places.get("storage") or floor
        damaged = places.get("damaged") or storage
        suppliers = list(Supplier.all_objects.filter(account=self.account, deleted_at__isnull=True)[:3])
        bens = [
            ("Computador do caixa 01", "Dell", "OptiPlex 3000", "3890.00", "in_use", floor, 36),
            ("Computador do caixa 02", "Dell", "OptiPlex 3000", "3890.00", "in_use", floor, 36),
            ("Impressora térmica de cupom", "Elgin", "i9", "899.00", "in_use", floor, 12),
            ("Impressora de etiquetas", "Zebra", "ZD220", "1490.00", "in_use", storage, 12),
            ("Balança do balcão de frios", "Toledo", "Prix 4 Uno", "2350.00", "in_use", floor, 24),
            ("Leitor de código de barras sem fio", "Honeywell", "Voyager 1472g", "980.00", "loaned", storage, 12),
            ("Freezer horizontal 400 L", "Metalfrio", "DA420", "4200.00", "maintenance", floor, 12),
            ("Ar-condicionado 18.000 BTU", "LG", "Dual Inverter", "3100.00", "in_use", floor, 12),
            ("Notebook da gerência", "Lenovo", "IdeaPad 3", "3500.00", "in_stock", storage, 12),
            ("Gaveta de dinheiro", "Bematech", "GD-56", "420.00", "broken", damaged, 6),
            ("Tablet do estoque", "Samsung", "Galaxy Tab A8", "1300.00", "disposed", damaged, 12),
        ]
        made = []
        for index, (desc, brand, model, price, status, place, warranty) in enumerate(bens):
            bought = TODAY - timedelta(days=60 + index * 45)
            made.append(Asset.all_objects.create(
                account=self.account, store=self.main, description=desc, brand=brand, model=model,
                serial_number=f"SN{2024000 + index * 137}", supplier=suppliers[index % len(suppliers)] if suppliers else None,
                purchase_date=bought, purchase_price=Decimal(price), location=place, status=status,
                responsible=self.admin, warranty_until=bought + timedelta(days=30 * warranty),
                warranty_provider=f"Assistência {brand}", installed_at=bought + timedelta(days=2),
                useful_life_months=60, notes="Bem de demonstração."))
        for asset in made:
            if asset.location != storage:  # todo bem passa pelo depósito antes de ir para o lugar dele
                AssetMovement.all_objects.create(account=self.account, asset=asset, from_location=storage,
                                                 to_location=asset.location, moved_by=self.admin, reason="Instalação")
        tablet = made[-1]
        AssetDisposal.all_objects.create(account=self.account, asset=tablet, kind=AssetDisposal.Kind.SCRAPPED,
                                         authorized_by=self.admin, reason="Tela quebrada, conserto mais caro que um novo")
        return f"{len(made)} bens de patrimônio, movimentações e 1 baixa"

    # ── Periféricos: impressoras, balanças, leituras e fila de impressão ─────
    def devices(self):
        if self.has(Printer):
            return "periféricos: já existem, nada a fazer"
        terminals = list(Terminal.all_objects.filter(account=self.account, store=self.main, deleted_at__isnull=True))
        terminal = terminals[0] if terminals else None
        receipt = Printer.all_objects.create(account=self.account, store=self.main, name="Cupom - Caixa 01",
                                             purpose=Printer.Purpose.RECEIPT, terminal=terminal,
                                             endpoint="ELGIN i9", cash_drawer_enabled=True)
        label = Printer.all_objects.create(account=self.account, store=self.main, name="Etiquetas - Estoque",
                                           purpose=Printer.Purpose.LABEL, driver=Printer.Driver.BROWSER,
                                           connection=Printer.Connection.NETWORK, host="192.168.0.50", paper_width_mm=50)
        Printer.all_objects.create(account=self.account, store=self.main, name="Escritório (A4)",
                                   purpose=Printer.Purpose.REPORT, driver=Printer.Driver.BROWSER, endpoint="HP LaserJet",
                                   paper_width_mm=210, auto_print=False)
        for store in self.stores[1:4]:
            Printer.all_objects.create(account=self.account, store=store, name="Cupom - Caixa 01",
                                       purpose=Printer.Purpose.RECEIPT, endpoint="EPSON TM-T20")
        scale = Scale.all_objects.create(account=self.account, store=self.main, name="Balança dos frios",
                                         terminal=terminal, protocol=Scale.Protocol.TOLEDO, port="COM3")
        Scale.all_objects.create(account=self.account, store=self.main, name="Balança do hortifrúti",
                                 protocol=Scale.Protocol.FILIZOLA, port="COM4", is_active=False)
        for index in range(10):
            ScaleReading.all_objects.create(
                account=self.account, store=self.main, scale=scale, weight_kg=Decimal(f"0.{random.randint(150, 980)}"),
                tare_kg=Decimal("0.010"), is_stable=index != 3,
                source=ScaleReading.Source.MANUAL if index == 7 else ScaleReading.Source.AGENT,
                notes="Digitado: balança sem comunicação" if index == 7 else "")
        sales = list(self.completed_sales(store=self.main)[:8])
        for index, sale in enumerate(sales):
            status = [PrintJob.Status.PRINTED] * 5 + [PrintJob.Status.FAILED, PrintJob.Status.PENDING,
                                                      PrintJob.Status.CANCELLED]
            done = status[index] == PrintJob.Status.PRINTED
            PrintJob.all_objects.create(
                account=self.account, store=self.main, printer=receipt, kind=PrintJob.Kind.RECEIPT, status=status[index],
                sale=sale, payload={"sale_number": sale.number}, printed_by=self.admin if done else None,
                printed_at=sale.completed_at if done else None,
                error_message="Sem papel" if status[index] == PrintJob.Status.FAILED else "")
        PrintJob.all_objects.create(account=self.account, store=self.main, printer=label, kind=PrintJob.Kind.LABEL,
                                    status=PrintJob.Status.PRINTED, printed_by=self.admin, printed_at=self.now,
                                    payload={"labels": 24})
        PrintJob.all_objects.create(account=self.account, store=self.main, printer=receipt,
                                    kind=PrintJob.Kind.CASH_CLOSING, status=PrintJob.Status.PRINTED,
                                    printed_by=self.admin, printed_at=self.now)
        return "6 impressoras, 2 balanças, 10 leituras e 10 impressões na fila"

    # ── Notificações para o admin (algumas lidas) ────────────────────────────
    def notifications(self):
        if self.has(Notification):
            return "notificações: já existem, nada a fazer"
        rows = [
            ("stock", "warning", "Estoque baixo: Iogurte Natural 170g", "Restam 4 unidades na Matriz.", "/cadastros/produtos"),
            ("stock", "warning", "Lote vencendo em 7 dias", "Requeijão Cremoso 200g: confira a gôndola.", "/cadastros/lotes"),
            ("fiscal", "error", "NF-e cancelada pelo fornecedor", "Uma nota já recebida foi cancelada.", "/cadastros/notas-de-entrada"),
            ("fiscal", "info", "2 notas novas na SEFAZ", "Chegaram pela distribuição DF-e.", "/cadastros/notas-de-entrada"),
            ("cash", "warning", "Diferença de caixa em aberto", "R$ 23,50 sem venda registrada.", ""),
            ("cash", "success", "Caixa 01 fechado sem diferença", "Turno conferido.", ""),
            ("sales", "info", "Devolução com vale-troca", "Crédito gerado para o cliente.", ""),
            ("finance", "warning", "3 contas vencem amanhã", "Total de R$ 2.480,30.", ""),
            ("finance", "success", "Recebimento confirmado", "Parcela do crediário paga.", ""),
            ("system", "info", "Bem-vindo à demonstração", "Os dados desta conta são fictícios.", ""),
        ]
        for index, (category, level, title, body, url) in enumerate(rows):
            Notification.all_objects.create(account=self.account, recipient=self.admin if index % 2 else None,
                                            category=category, level=level, title=title, body=body, url=url,
                                            read_at=self.now if index >= 6 else None)
        return f"{len(rows)} notificações (4 lidas)"

    # ── Links de avaliação enviados ao cliente ───────────────────────────────
    def review_links(self):
        if self.has(ReviewLink):
            return "links de avaliação: já existem, nada a fazer"
        made = 0
        for sale in self.completed_sales(customer__isnull=False).order_by("-completed_at")[:30]:
            for kind in reviews.kinds_of(sale):
                if made >= 10 or reviews.already_reviewed(sale, kind):
                    continue
                link = reviews.generate_link(sale, kind, self.admin)
                if made % 4 == 3:  # alguns o cliente deixou vencer
                    ReviewLink.all_objects.filter(pk=link.pk).update(expires_at=self.now - timedelta(days=1))
                made += 1
        return f"{made} links de avaliação (alguns vencidos)"
