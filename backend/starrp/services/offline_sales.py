"""Vendas montadas PRONTAS no PDV desktop (local-first).

O PDV desktop monta a venda inteira no próprio PC (itens, preço, desconto, cupom, entrega,
cliente, pagamentos), emite a nota pelo ACBr local e manda tudo pronto para cá — com o
servidor no ar (na hora) ou depois (fila offline). Aqui ela vira uma venda comum,
concluída: estoque baixa, comissão, contas a receber e caixa — o mesmo `checkout` do PDV web.

- A venda é um FATO: o cliente já pagou e levou. Preço e desconto praticados no balcão valem
  como vieram; quem autorizou (gerente) vem em `discount_approved_by` / `approved_by` do item
  (o PDV conferiu a senha — online por `/pdv/authorize/`, offline pela senha que aprendeu).
- `dry_run` (`/pdv/offline-sales/?dry_run=1`): monta tudo numa transação desfeita no fim e
  devolve a venda como ficaria — o PDV online valida ANTES de cobrar (crediário, limite do
  cliente, cupom, frete) e usa o cupom/frete calculados aqui. Sem `payments`, só a prévia.
- `replaces`: o pedido do servidor que o PDV retomou (ex.: enviado pelo vendedor). Ainda sem
  pagamento, ele é CONCLUÍDO com o conteúdo do PDV (mantém número e vendedor); se já não
  estiver aberto/guardado, a venda nasce nova.
- `park`: o caixa guardou a venda (com o servidor no ar): vira um pedido guardado da loja,
  que qualquer caixa retoma (sem pagamento). Ainda NÃO é fato: preço/desconto sem autorização
  comprovada volta ao do sistema (R4-01), e a conclusão confere como qualquer venda.
- Reenviar a mesma venda (`offline_id`) devolve a já importada: a fila nunca duplica.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, CouponRejected
from starrp.core.permissions import has_permission_code
from starrp.core.values import moment, user_pk
from starrp.models import (
    CashSession, Coupon, Customer, CustomerAddress, FreightTable, Notification, PaymentMethod, ProductVariant, Sale, SaleItem, StockBalance, StockMovement, Terminal,
    UserProfile,
)
from starrp.services import approval_proof, checkout, finance, notifications, offline_cash, pricing, sale_addresses, sales, service_rules, stock
from starrp.services.approvals import max_discount_percent
from starrp.services.cash import session_for_user
from starrp.services.store_access import own_sales_q, profiles_reaching

User = get_user_model()
KEY = "_offline_id"


def parking_or_dry(data, dry_run):
    return bool(data.get("park")) or (dry_run and not data.get("payments"))


def find(store, offline_id):
    return Sale.all_objects.filter(store=store, deleted_at__isnull=True, **{f"metafields__{KEY}": offline_id}).first()


def _dec(value, default="0"):
    """Número vindo do PDV: finito e nunca negativo (M-15: desconto de -50 virava acréscimo escondido)."""
    try:
        number = Decimal(str(value if value not in (None, "") else default))
    except InvalidOperation:
        raise BusinessError("Número inválido na venda do PDV.", code="offline_invalid") from None
    if not number.is_finite() or number < 0 or number > Decimal("1e12"):
        raise BusinessError("Número inválido na venda do PDV.", code="offline_invalid")
    return number


def _count(value):
    try:
        count = max(int(value or 1), 1)
    except (TypeError, ValueError, OverflowError):
        count = 0
    if not 1 <= count <= 999:
        raise BusinessError("Número de parcelas inválido.", code="offline_invalid")
    return count


def _object(value, what):
    """Objeto opcional da venda (entrega, endereços)."""
    if value and not isinstance(value, dict):
        raise BusinessError(f"{what} da venda em formato inválido.", code="offline_invalid")
    return value or {}


def _text(value, limit):
    """Texto que cabe na coluna (no Postgres o que passa dela é erro, e a venda travava a fila)."""
    return "" if value is None else str(value)[:limit]


def _rows(value, what):
    """Lista de objetos (B-05: o formato errado virava erro 500)."""
    value = value or []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise BusinessError(f"{what} da venda em formato inválido.", code="offline_invalid")
    return value


def _seller(store, account, pk, checks):
    """Vendedor da FILIAL da venda (A-13): o de outra filial levava a comissão. A venda é fato: entra sem vendedor
    e a gerência é avisada."""
    seller = _account_user(account, pk, "vendedor")
    if seller is not None and not profile_sells(store, seller):
        checks.issues.append(f"Vendedor {seller.get_full_name() or seller.username} não é desta filial: a venda ficou "
                             "sem vendedor.")
        return None
    return seller


def profile_sells(store, user):
    return UserProfile.all_objects.filter(
        profiles_reaching([store.pk]), user=user, account=store.account, is_active=True, deleted_at__isnull=True).exists()


def _account_user(account, pk, what):
    """Usuário citado pela venda (vendedor, quem autorizou): tem de ser desta conta (S-06)."""
    if not pk:
        return None
    profile = (UserProfile.all_objects.select_related("user")
               .filter(account=account, user_id=user_pk(pk), deleted_at__isnull=True, user__is_superuser=False).first())
    if profile is None:
        raise BusinessError(f"O {what} da venda não pertence a esta conta.", code="offline_user_unknown")
    profile.user.profile = profile
    return profile.user


ITEM_CODES = {"sales.price_override", "sales.discount"}


def _percent(part, whole):
    return (Decimal(part) / Decimal(whole) * 100) if whole else Decimal("0")


class _Checks:
    """O que não pôde ser conferido na venda montada no PDV (vira alerta para a gerência)."""

    def __init__(self, account, store, operator, sender, proofs, dry_run):
        self.account, self.store, self.operator, self.sender = account, store, operator, sender
        self.proofs, self.dry_run, self.issues = approval_proof.decode(proofs), dry_run, []
        self.granted, self.header, self.header_by = {}, (Decimal("0"), Decimal("0")), None
        # O operador vem do PDV: vale o MENOR limite entre ele e quem enviou (rodada 1, P-4 — senão o caixa
        # escreve o id do gerente como operador e herda o limite dele).
        self.limit = min(max_discount_percent(operator), max_discount_percent(sender))

    def keep_grants(self, sale):
        """Pedido do servidor que o PDV refaz: o que já foi autorizado LÁ continua valendo, até o MESMO valor em
        reais e o mesmo percentual (R7-02/03). Medido contra o preço vigente: promoção não é autorização."""
        for item in sale.items.filter(status=SaleItem.Status.ACTIVE).select_related(
                "variant__product", "parent_item__variant__product"):
            if item.parent_item_id:  # serviço: o preço é o da REGRA dele, não o do cadastro
                shelf = service_rules.price_for(item.variant, item.parent_item.variant.product)
                shelf = item.unit_price if shelf is None else shelf
            else:
                shelf = pricing.quote(item.variant, sale.store_id).unit_price
            gross = sales.cents(item.quantity * shelf)
            money = max(gross - item.total, Decimal("0"))
            before = self.granted.get(item.variant_id, (Decimal("0"), Decimal("0")))
            self.granted[item.variant_id] = (before[0] + money, max(before[1], _percent(money, gross)))
        if sale.discount:
            self.header = (sale.discount, _percent(sale.discount, sale.subtotal))
            self.header_by = sale.discount_approved_by_id

    def use_grant(self, variant_id, money, percent):
        """Gasta o autorizado desta variante (a mesma variante em duas linhas não usa duas vezes)."""
        left, limit = self.granted.get(variant_id, (Decimal("0"), Decimal("0")))
        if not money or percent > limit + Decimal("0.01") or money > left + Decimal("0.01"):
            return False
        self.granted[variant_id] = (left - money, limit)
        return True

    def approval(self, approver, codes, percent, label, what="", granted=False):
        """Desconto/preço abaixo do limite do operador precisa de autorizador COMPROVADO (uso único). Devolve se
        a condição vale (sem isso entra marcada; pedido guardado volta ao preço do sistema)."""
        if percent <= self.limit + Decimal("0.01"):
            return "own"
        if granted:
            return "granted"
        if approver is None or approver.pk in (self.operator.pk, self.sender.pk):
            self.issues.append(f"{label}: {percent:.2f}% acima do limite do operador, sem autorização.")
            return False
        allowed = (any(has_permission_code(approver, code) for code in codes)
                   and percent <= max_discount_percent(approver) + Decimal("0.01"))
        if not allowed:
            self.issues.append(f"{label}: {approver.get_full_name() or approver.username} não tem permissão/limite "
                               f"para {percent:.2f}%.")
        else:
            proof = approval_proof.find(self.proofs, account=self.account, store=self.store, operator=self.operator,
                                        approver_id=approver.pk, codes=codes, percent=percent, what=what)
            if proof is not None and (self.dry_run or approval_proof.spend(proof)):
                return "proof"
            self.issues.append(f"{label}: autorização de {approver.get_full_name() or approver.username} sem "
                               "comprovante do servidor (feita offline ou já usada): confira.")
        return False


def _reuse(store, user, replaced_id, session, presale=None, checks=None):
    """O pedido do servidor que o PDV retomou (ou a pré-venda do vendedor que o caixa leu no
    ticket): se ainda não foi pago, é ele que conclui."""
    if not replaced_id and not presale:
        return None
    open_ = Sale.all_objects.select_for_update().filter(
        store=store, status__in=[Sale.Status.OPEN, Sale.Status.DRAFT], paid_amount=0, deleted_at__isnull=True)
    # Pelo id: só o pedido que ele enxerga (M-01: o vendedor assumia o do colega). Pelo ticket: quem o leu o tem.
    old = open_.filter(own_sales_q(), pk=replaced_id).first() if replaced_id else None
    if old is None and presale:
        old = open_.filter(**{f"metafields__{KEY}": presale}).first()
    if old is None:
        return None
    now = timezone.now()
    if checks is not None:
        checks.keep_grants(old)
    old.items.filter(status=SaleItem.Status.ACTIVE).update(
        status=SaleItem.Status.CANCELLED, cancelled_at=now, cancelled_by=user,
        cancel_reason="Refeito pelo PDV desktop (venda concluída no terminal).")
    old.status, old.operator, old.updated_by = Sale.Status.OPEN, user, user
    old.coupon, old.coupon_code, old.coupon_discount, old.discount, old.freight = None, "", 0, 0, 0
    old.cash_session = session  # nunca o turno de quem montou o pedido (R5-01: entrava dinheiro em turno fechado)
    old.save()
    return old


@transaction.atomic
def import_sale(store, user, data, dry_run=False):
    offline_id = str(data.get("offline_id") or "").strip()
    if not offline_id:
        raise BusinessError("offline_id é obrigatório.", code="offline_id_required")
    existing = find(store, offline_id)
    if existing is not None:
        return existing, False
    if data.get("park"):
        # Pré-venda do vendedor que o caixa já cobrou (leu o ticket sem servidor): não vira
        # um pedido guardado a mais — a venda concluída é ela.
        done = Sale.all_objects.filter(store=store, deleted_at__isnull=True, metafields___presale=offline_id).first()
        if done is not None:
            return done, False
    sender = user
    user = offline_cash.actor_for(store.account, user, data.get("operator"))
    items = _rows(data.get("items"), "Itens")
    payments = _rows(data.get("payments"), "Pagamentos")
    if not items:
        raise BusinessError("Venda sem itens.", code="offline_incomplete")
    parking = bool(data.get("park"))
    if not payments and not dry_run and not parking:
        raise BusinessError("Venda sem pagamento.", code="offline_incomplete")

    account = store.account
    terminal = Terminal.all_objects.filter(account=account, installation_id=data.get("installation_id")).first()
    customer = Customer.all_objects.filter(account=account, pk=data.get("customer")).first() if data.get("customer") else None
    checks = _Checks(account, store, user, sender, data.get("approval_proofs"), dry_run)
    seller = _seller(store, account, data.get("seller"), checks)
    session = offline_cash.resolve_session(store, data.get("cash_session")) if data.get("cash_session") else None
    if data.get("cash_session") and session is None:
        raise BusinessError("O turno de caixa desta venda ainda não chegou ao servidor.", code="offline_session_missing")
    if not parking_or_dry(data, dry_run):
        session = session or session_for_user(store, user)

    sale = _reuse(store, user, data.get("replaces"), session, data.get("presale"), checks)
    if sale is None:
        sale = sales.create(store, user, terminal=terminal, seller=seller, customer=customer,
                            customer_document=_text(data.get("customer_document"), 18),
                            customer_name=_text(data.get("customer_name"), 180), cash_session=session)
    else:
        sale.customer = customer or sale.customer
        sale.customer_document = _text(data.get("customer_document"), 18) or sale.customer_document
        sale.customer_name = _text(data.get("customer_name"), 180) or sale.customer_name
        sale.seller = seller or sale.seller
        sale.terminal = terminal or sale.terminal
        sale.save(update_fields=["customer", "customer_document", "customer_name", "seller", "terminal", "updated_at"])
    sale.metafields = {**(sale.metafields or {}), KEY: offline_id, **({"_presale": data["presale"]} if data.get("presale") else {}), "_offline": {
        "created_at": data.get("created_at"), "completed_at": data.get("completed_at"),
        "local_number": data.get("local_number"), "offline": bool(data.get("was_offline"))}}
    if data.get("notes"):
        sale.notes = f"{sale.notes}\n{data['notes']}".strip()
    sale.save(update_fields=["metafields", "notes"])

    parents, reverted = {}, False
    gross_total = own_discount = Decimal("0")  # preço do servidor; desconto que ninguém além do operador autorizou
    for row in items:
        variant = ProductVariant.all_objects.filter(account=account, pk=row.get("variant")).first()
        if variant is None:
            raise BusinessError(f"Produto da venda não existe mais: {row.get('description')}.",
                                code="offline_variant_missing")
        parent = parents.get(str(row["parent"])) if row.get("parent") else None
        item = sales.add_item(sale, variant, _dec(row.get("quantity"), "1"), user, seller=seller, parent_item=parent,
                              # Validação antes de cobrar e pedido guardado conferem; a venda
                              # concluída (fato) entra mesmo se o produto foi inativado depois.
                              check_sellable=dry_run or bool(data.get("park")))
        # O preço e o desconto praticados no balcão valem como vieram.
        server_promotion = item.promotion
        server_price = item.unit_price  # o que o servidor cobraria (já com promoção/tabela de desconto)
        price = _dec(row.get("unit_price"), str(item.unit_price))
        discount = sales.cents(_dec(row.get("discount")))
        item.unit_price, item.discount = price, discount
        item.total = max(sales.cents(item.quantity * price) - discount, Decimal("0"))
        if price != server_price:  # ao preço da promoção, é a promoção (o PDV omitia para acumular cupom)
            item.promotion = None
        approver = _account_user(account, row.get("approved_by"), "autorizador")
        # Base: o preço do servidor (promoção/tabela já aplicadas) — contra o cheio, toda promoção viraria alerta.
        gross = sales.cents(item.quantity * (server_price or price))
        missing = max(gross - item.total, Decimal("0"))
        # Arredondamento do peso (menos de 1 g, ao preço do SERVIDOR) não é desconto (R7-01: o preço vinha do PDV).
        weighed = item.quantity % 1 and price == server_price
        percent = (Decimal("0") if weighed and missing <= server_price * Decimal("0.001") + Decimal("0.01")
                   else _percent(missing, gross))
        if price > server_price and discount:
            checks.issues.append(f"Item {item.description}: preço R$ {price} acima do sistema com desconto na linha.")
        valid = checks.approval(approver, ITEM_CODES, percent, f"Item {item.description}", what=f"variant:{variant.pk}",
                                granted=checks.use_grant(variant.pk, missing, percent))
        if parking and not valid:
            item.unit_price, item.discount, item.promotion = server_price, Decimal("0"), server_promotion
            item.total, reverted = gross, True
        elif item.discount:
            # O autorizador só é gravado com comprovante (R7-05); o percentual é sobre o preço do sistema.
            by = approver if approver is not None and valid == "proof" else user
            item.metafields = {**(item.metafields or {}), "_discount_by": by.pk,
                               "_discount_ok": str(min(_percent(item.discount, sales.cents(item.quantity * price)), percent))}
        gross_total += gross
        if valid == "own":
            own_discount += max(gross - item.total, Decimal("0"))
        if approver is not None and valid in ("proof", False):
            item.metafields = {**(item.metafields or {}), "_approved_by": approver.pk}
        item.save(update_fields=["unit_price", "discount", "total", "promotion", "metafields"])
        if row.get("id"):
            parents[str(row["id"])] = item
    sale.refresh_from_db()

    # Entrega (frete da tabela, calculado aqui) ou retirada.
    fact, freight_lost = not dry_run and not parking, False  # `fact`: o cliente já pagou e levou
    delivery = _object(data.get("delivery"), "Entrega")
    if delivery.get("address") and delivery.get("table"):
        address = CustomerAddress.all_objects.filter(account=account, pk=delivery["address"]).first()
        table = FreightTable.all_objects.filter(account=account, pk=delivery["table"]).first()
        if address is None or table is None:
            raise BusinessError("Endereço ou tabela de frete da venda não existe mais.", code="offline_delivery_missing")
        try:
            with transaction.atomic():
                sale = sales.set_delivery(sale, user, address, table)
        except BusinessError as error:  # tabela desligada depois da venda: entrega no endereço, frete pelo cobrado
            if not fact or error.get_codes() != "freight_unavailable":
                raise
            checks.issues.append(f"Frete: {error.detail}")
            freight_lost = True
            sale.shipping_address, sale.freight = address, Decimal("0")
            sale.save(update_fields=["shipping_address", "freight"])
    else:
        sales.mark_pickup(sale)
        sale.freight = Decimal("0")
        sale.save(update_fields=["shipping_address", "freight", "metafields"])
    addresses = _object(data.get("addresses"), "Endereços")
    if addresses.get("delivery"):
        sale_addresses.save(sale, user, addresses["delivery"], addresses.get("billing"),
                            addresses.get("billing_same_as_delivery", True))
    sale.refresh_from_db()

    sale = sales.recalculate(sale)  # o subtotal com os preços do PDV (senão o percentual sai do preço do servidor)
    sale.discount = sales.cents(_dec(data.get("discount")))
    sale.discount_approved_by = (_account_user(account, data.get("discount_approved_by"), "autorizador")
                                 if sale.discount else None)
    if sale.discount:
        percent = _percent(sale.discount, sale.subtotal)
        valid = checks.approval(sale.discount_approved_by or None, {"sales.discount"}, percent, "Desconto da venda",
                                granted=(sale.discount <= checks.header[0] + Decimal("0.01")
                                         and percent <= checks.header[1] + Decimal("0.01")))
        if valid == "own":
            sale.discount_approved_by = user
        elif valid == "granted":
            sale.discount_approved_by_id = checks.header_by
        if valid in ("own", "granted"):  # R5-05: 10% no item e 10% na venda, cada um dentro do limite, davam 19%
            combined = _percent(own_discount + sale.discount, gross_total)
            if combined > max(checks.limit, checks.header[1] if valid == "granted" else Decimal("0")) + Decimal("0.01"):
                checks.issues.append(f"Descontos somados: {combined:.2f}% acima do limite do operador, sem autorização.")
                valid = False
        if valid:
            sale.metafields = {**sale.metafields, "_discount_ok": sales.discount_grant(sale, sale.discount)}
        elif parking:
            sale.discount, sale.discount_approved_by, reverted = Decimal("0"), None, True
    sale.save(update_fields=["discount", "discount_approved_by", "metafields"])
    sales.recalculate(sale)
    if data.get("coupon_code"):
        sale = _coupon(sale, str(data["coupon_code"]), checks, fact=fact)
    sale.refresh_from_db()

    expected = data.get("total")
    if reverted:
        note = "Preço/desconto sem autorização comprovada: o pedido ficou com o preço do sistema."
        sale.notes = f"{sale.notes}\n{note}".strip()
        sale.save(update_fields=["notes"])
    elif fact and expected not in (None, "") and sale.total != _dec(expected):
        _match_total(sale, _dec(expected), checks, freight_lost)
    elif expected not in (None, "") and abs(sale.total - _dec(expected)) > Decimal("0.01"):
        raise BusinessError(
            f"O total calculado no servidor (R$ {sale.total}) é diferente do total do PDV (R$ {_dec(expected)}). "
            "Atualize o catálogo do PDV e refaça o cupom/frete.", code="offline_total_mismatch")
    if parking:  # guardado no PDV com o servidor no ar: vira pedido guardado da loja
        return sales.park(sale, user, str(data.get("park_note") or "")), True
    if not payments:
        return sale, True  # prévia (dry run sem pagamento)

    rows = []
    for p in payments:
        method = PaymentMethod.all_objects.filter(account=account, pk=p.get("method")).first()
        if method is None:
            raise BusinessError("Forma de pagamento da venda não existe mais.", code="offline_method_missing")
        if not method.is_active:  # a venda cobrada já aconteceu (fato): entra e a gerência confere
            if dry_run:
                raise BusinessError(f"{method.name} está desativada.", code="payment_method_inactive")
            checks.issues.append(f"Forma de pagamento desativada: {method.name}.")
        if not dry_run and _count(p.get("installments")) > method.max_installments:
            checks.issues.append(f"{method.name} em {_count(p.get('installments'))}x (hoje o máximo é {method.max_installments}x).")
        if (not dry_run and method.requires_reference and store.rule.require_payment_reference
                and not (p.get("nsu") or p.get("authorization_code"))):
            checks.issues.append(f"{method.name} sem NSU/autorização.")
        rows.append({"method": method, "amount": _dec(p.get("amount")),
                     "tendered": _dec(p["tendered"]) if p.get("tendered") else None,
                     "installments": _count(p.get("installments")),
                     "nsu": _text(p.get("nsu"), 40), "authorization_code": _text(p.get("authorization_code"), 40),
                     "idempotency_key": f"{offline_id}:{len(rows)}"})
    sale = checkout.checkout(sale, user, rows, imported="dry" if dry_run else True)
    sale.refresh_from_db()
    if not stock.settings_for(account.pk, store.pk).allow_negative_stock:
        _check_stock(sale, checks)
    if not dry_run and sale.customer_id:
        _check_customer(sale, rows, checks)
    if sale.cash_session is not None:
        _check_shift(sale, sale.cash_session, sender, checks, dry_run)
    completed = moment(data.get("completed_at"))
    if completed is not None:
        # Hora da venda no PC: só dentro do turno e nunca no futuro (S-06: nada de retroagir/adiantar).
        now = timezone.now()
        opened = getattr(sale.cash_session, "opened_at", None)
        floor = (opened - timedelta(minutes=5)) if opened else now - timedelta(days=30)
        if floor <= completed <= now + timedelta(minutes=5):
            Sale.all_objects.filter(pk=sale.pk).update(completed_at=completed)
        else:
            checks.issues.append(f"Hora da venda informada pelo PDV ({completed:%d/%m/%Y %H:%M}) fora do turno: "
                                 "ficou a hora da importação.")
        sale.refresh_from_db()
    if checks.issues and not dry_run:
        _flag(sale, user, checks.issues)
    return sale, True


def _match_total(sale, charged, checks, freight_lost):
    """O cliente já pagou e levou (R6-B2, R7-04): recusar deixava o dinheiro na gaveta sem venda. A venda entra pelo
    valor cobrado, sem reavaliar cupom/frete, e a gerência é avisada."""
    gap = charged - sale.total
    if gap > 0:  # cobrou a mais: sai do cupom, depois do desconto; o que sobrar é frete
        if not freight_lost:
            for field in ("coupon_discount", "discount"):
                take = min(gap, getattr(sale, field))
                setattr(sale, field, getattr(sale, field) - take)
                gap -= take
        sale.freight += gap
    else:
        take = min(-gap, max(sale.subtotal - sale.discount - sale.coupon_discount, Decimal("0")))
        sale.discount += take
        sale.freight = max(sale.freight - (-gap - take), Decimal("0"))
    if abs(charged - sale.total) > Decimal("0.05"):
        checks.issues.append(f"O PDV cobrou R$ {charged} e o servidor calculou R$ {sale.total}.")
    sale.total = max(sale.subtotal - sale.discount - sale.coupon_discount + sale.freight, Decimal("0"))
    sale.save(update_fields=["discount", "coupon_discount", "freight", "total"])


def _coupon(sale, code, checks, fact):
    """Cupom da venda. Já cobrada: um cupom que venceu ou esgotou antes do envio é honrado, com aviso."""
    try:
        with transaction.atomic():
            return sales.apply_coupon(sale, code)
    except CouponRejected as error:
        if not fact:
            raise
        coupon = Coupon.all_objects.filter(account_id=sale.account_id, code=str(code).strip().upper()).first()
        checks.issues.append(f"Cupom {code}: {error.detail}")
        if coupon is None:
            return sale
        sale = Sale.all_objects.get(pk=sale.pk)
        sale.coupon, sale.coupon_code = coupon, coupon.code
        sale.coupon_discount = min(coupon.discount_for(sale.subtotal, sale.freight),
                                   max(sale.subtotal - sale.discount, Decimal("0")) + sale.freight)
        sale.total = max(sale.subtotal - sale.discount - sale.coupon_discount + sale.freight, Decimal("0"))
        sale.save(update_fields=["coupon", "coupon_code", "coupon_discount", "total"])
        return sale


def _check_customer(sale, rows, checks):
    """Vale ou crediário que já não cabia quando a venda chegou: a mercadoria saiu, a gerência acerta."""
    kinds = {row["method"].kind for row in rows}
    if PaymentMethod.Kind.STORE_CREDIT in kinds and (balance := checkout.credit_balance(sale.customer)) < 0:
        checks.issues.append(f"O vale-troca do cliente ficou em R$ {balance}.")
    if PaymentMethod.Kind.INSTALLMENT_PLAN in kinds:
        owed = finance.open_receivables(sale.customer)
        if owed > sale.customer.credit_limit:
            checks.issues.append(f"O cliente deve R$ {owed}, acima do limite de R$ {sale.customer.credit_limit}.")


def _check_stock(sale, checks):
    negative = StockBalance.all_objects.filter(
        # Pelos movimentos: no kit, quem fica negativo é o componente.
        variant__in=StockMovement.all_objects.filter(sale_item__sale=sale).values("variant"), warehouse__store=sale.store,
        quantity__lt=0).select_related("variant__product")
    for balance in negative[:5]:
        checks.issues.append(f"{balance.variant.display_name} ficou com saldo {balance.quantity.normalize():f}.")


def _check_shift(sale, session, sender, checks, dry_run):
    """A gaveta em que a venda entrou (R4-02, R4-03): a venda é fato, mas turno já conferido ou de outro operador
    nunca passa calado."""
    session.refresh_from_db()
    if session.status not in (CashSession.Status.OPEN, CashSession.Status.PENDING_OPENING):
        if not dry_run:
            session = offline_cash.late_sale(session)
        checks.issues.append(f"Chegou com o turno do {session.register.name} já fechado: a conferência foi refeita "
                             f"(diferença R$ {session.difference}).")
    if session.opened_by_id != sender.pk and not has_permission_code(sender, "cash.approve"):
        checks.issues.append(f"Entrou no turno de {session.opened_by.get_full_name() or session.opened_by.username}, "
                             f"mas quem enviou foi {sender.get_full_name() or sender.username}.")


def _flag(sale, operator, issues):
    """Venda do PDV com autorização não conferida: fica marcada e a gerência é avisada (S-06)."""
    Sale.all_objects.filter(pk=sale.pk).update(metafields={**(sale.metafields or {}), "_approval_unverified": issues})
    sale.refresh_from_db()
    notifications.send(
        account=sale.account, store=sale.store, category=Notification.Category.SALES, level=Notification.Level.WARNING,
        permission="sales.cancel", title=f"Venda {sale.number}: autorização a conferir",
        body=f"Operador {operator.get_full_name() or operator.username}. " + " ".join(issues),
        url=f"/cadastros/vendas/{sale.pk}", entity="sale", object_id=sale.pk)


class _Rollback(Exception):
    def __init__(self, payload):
        super().__init__("dry run")
        self.payload = payload


def preview(store, user, data, render):
    """Monta a venda e desfaz tudo: devolve `render(sale)` como ela ficaria (nada é gravado)."""
    try:
        with transaction.atomic():
            sale, _ = import_sale(store, user, {**data, "offline_id": f"dry:{data.get('offline_id') or 'preview'}"},
                                  dry_run=True)
            raise _Rollback(render(sale))
    except _Rollback as done:
        return done.payload
