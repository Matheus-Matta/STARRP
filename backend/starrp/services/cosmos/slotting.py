"""A Cosmos organizando o armazém: lê as vendas e os endereços e recomenda onde guardar cada produto.

Só conta, sem modelo de IA: não gasta tokens, e cada número da recomendação pode ser conferido nas vendas.
Nada muda sozinho: aceitar cria a Movimentação entre endereços em RASCUNHO, que a equipe confere e confirma.

As recomendações, da mais urgente para a menos:
- doca: mercadoria parada no recebimento, fora de qualquer endereço de guarda;
- juntos: produtos que saem na mesma venda bem mais do que o acaso explica e estão longe na rota;
- giro: o que mais sai guardado no fim da rota;
- espalhado: o mesmo produto em vários endereços. Lote com validade fica de fora: separar validades num endereço é de propósito;
  o lote automático do FIFO por entrada entra, porque cada lote continua separado no saldo e a ordem de saída não muda;
- parado: o que não sai ocupando a frente da rota.

Um produto entra em uma recomendação só por análise, e um endereço livre só é oferecido uma vez.
O sistema não sabe o tamanho das caixas nem a capacidade do endereço: só oferece endereço VAZIO, e quem confere é a equipe.
"""
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from itertools import combinations

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import (
    BinBalance, CosmosFinding, Module, SaleItem, StockAdvice, StockDocument, StockDocumentItem, StorageBin, Warehouse,
)
from starrp.services import numbering

PERIOD_DAYS = 90
MIN_SALES = 20  # com menos vendas no período, padrão nenhum é confiável
MIN_TOGETHER = 5
MIN_LIFT = Decimal("1.5")  # saem juntos 50% mais do que o acaso explicaria
MAX_BASKET = 30  # venda enorme (atacado, kit de mudança) não diz o que combina com o quê
MAX_LINES = 200_000
MIN_LINES_FAST = 10
FAST_SHARE = Decimal("0.2")
DOCK_DAYS = 2
IDLE_DAYS = 30
SCATTERED_BINS = 3
MAX_PER_KIND = 10
KEEP_DECISION_DAYS = 60  # quem recusou não vê a mesma recomendação de novo por este tempo
ALERT = "stock-advice:"


def enabled(account):
    return account.cosmos_active and account.cosmos_stock_advice and account.has_module(Module.STOCK)


def _qty(value):
    return f"{value:f}".rstrip("0").rstrip(".") if "." in f"{value:f}" else f"{value:f}"


@dataclass
class Floor:
    """O armazém como está agora: a rota, o que está onde e o que já está reservado."""

    warehouse: Warehouse
    route: list = field(default_factory=list)  # endereços de guarda e separação, na ordem da coleta
    dock: list = field(default_factory=list)
    rows: dict = field(default_factory=lambda: defaultdict(list))  # variante → saldos em endereços
    busy: set = field(default_factory=set)
    claimed: set = field(default_factory=set)
    now: object = None

    def __post_init__(self):
        self.rank = {}

    @property
    def near(self):
        """Até quantos endereços de distância na rota ainda é "perto"."""
        return max(5, len(self.route) // 10)

    def main(self, variant_id):
        """O endereço onde está a maior parte do produto. Quem só está na doca não tem."""
        totals = Counter()
        for row in self.rows[variant_id]:
            if row.bin_id in self.rank:
                totals[row.bin_id] += row.quantity
        if not totals:
            return None
        best = max(totals, key=lambda pk: (totals[pk], -self.rank[pk]))
        return self.route[self.rank[best]]

    def free(self, order):
        return next((self.route[i] for i in order if self.route[i].pk not in self.busy), None)

    def free_near(self, anchor, limit):
        place = self.rank[anchor.pk]
        order = sorted(range(len(self.route)), key=lambda i: (abs(i - place), i))
        return self.free([i for i in order if i != place and abs(i - place) <= limit])

    def moves(self, variant_id, source, target):
        rows = [row for row in self.rows[variant_id] if row.bin_id == source.pk]
        return [{"variant": str(variant_id), "description": row.variant.display_name, "lot": str(row.lot_id) if row.lot_id else None,
                 "lot_label": (row.lot.lot_number or row.lot.code) if row.lot_id else "", "from_bin": str(source.pk),
                 "from_code": source.code, "to_bin": str(target.pk), "to_code": target.code, "quantity": str(row.quantity)}
                for row in rows]


@dataclass
class Found:
    kind: str
    key: str
    title: str
    detail: str
    impact: int
    moves: list


def _floor(warehouse, now):
    floor = Floor(warehouse, now=now)
    bins = StorageBin.all_objects.filter(warehouse=warehouse, is_active=True, deleted_at__isnull=True).order_by("sequence", "code")
    for item in bins:
        if item.kind in (StorageBin.Kind.STORAGE, StorageBin.Kind.PICKING):
            floor.rank[item.pk] = len(floor.route)
            floor.route.append(item)
        elif item.kind == StorageBin.Kind.RECEIVING:
            floor.dock.append(item)
    balances = (BinBalance.all_objects.filter(bin__warehouse=warehouse, bin__is_active=True, quantity__gt=0, deleted_at__isnull=True,
                                              variant__deleted_at__isnull=True).select_related("bin", "lot", "variant__product"))
    for row in balances:
        floor.rows[row.variant_id].append(row)
        floor.busy.add(row.bin_id)
    # O que já está em movimentação aberta: não recomenda de novo, e o destino já tem dono.
    drafts = StockDocumentItem.all_objects.filter(document__warehouse=warehouse, document__kind=StockDocument.Kind.RELOCATION,
                                                  document__status=StockDocument.Status.DRAFT, document__deleted_at__isnull=True,
                                                  deleted_at__isnull=True)
    for variant_id, target in drafts.values_list("variant_id", "destination_bin_id"):
        floor.claimed.add(variant_id)
        if target:
            floor.busy.add(target)
    return floor


def _baskets(warehouse, now):
    """As vendas do período: {venda: {variantes}}. Um item é "uma coleta", qualquer que seja a quantidade."""
    lines = (SaleItem.all_objects.filter(sale__store=warehouse.store, sale__status="completed", status=SaleItem.Status.ACTIVE,
                                         sale__completed_at__gte=now - timedelta(days=PERIOD_DAYS), parent_item__isnull=True,
                                         deleted_at__isnull=True).order_by("-sale__completed_at")
             .values_list("sale_id", "variant_id")[:MAX_LINES])
    baskets = defaultdict(set)
    for sale, variant in lines:
        baskets[sale].add(variant)
    return baskets


def _name(floor, variant_id):
    return floor.rows[variant_id][0].variant.display_name


def _dock(floor):
    found, limit = [], floor.now - timedelta(days=DOCK_DAYS)
    dock = {item.pk: item for item in floor.dock}
    stuck = defaultdict(list)
    for variant_id, rows in floor.rows.items():
        for row in rows:
            if row.bin_id in dock and row.updated_at < limit and variant_id not in floor.claimed:
                stuck[variant_id].append(row)
    for variant_id, rows in stuck.items():
        target = floor.main(variant_id) or floor.free(range(len(floor.route)))
        sources = [dock[pk] for pk in dict.fromkeys(row.bin_id for row in rows)]
        days = (floor.now - min(row.updated_at for row in rows)).days
        total = sum(row.quantity for row in rows)
        moves = [move for source in sources for move in floor.moves(variant_id, source, target)] if target else []
        if target:
            floor.busy.add(target.pk)
        floor.claimed.add(variant_id)
        where = f"Guarde em {target.code}." if target else "Não há endereço livre: libere um para guardar."
        found.append(Found(StockAdvice.Kind.DOCK, f"{variant_id}", f"{_name(floor, variant_id)} parado na doca há {days} dias",
                           f"{_qty(total)} unidades em {', '.join(item.code for item in sources)}. Enquanto não é guardado, a coleta precisa ir até a doca. {where}",
                           days + 1000, moves))
    return found


def _together(floor, baskets):
    found, sold = [], Counter()
    pairs = Counter()
    stocked = {variant_id for variant_id in floor.rows if floor.main(variant_id)}
    for items in baskets.values():
        sold.update(items)
        if len(items) <= MAX_BASKET:
            pairs.update(combinations(sorted(items & stocked, key=str), 2))
    total = len(baskets)
    for (first, second), count in pairs.most_common():
        if count < MIN_TOGETHER or len(found) >= MAX_PER_KIND:
            break
        if first in floor.claimed or second in floor.claimed:
            continue
        lift = Decimal(count * total) / Decimal(sold[first] * sold[second])
        if lift < MIN_LIFT:
            continue
        here, there = floor.main(first), floor.main(second)
        gap = abs(floor.rank[here.pk] - floor.rank[there.pk])
        if gap <= floor.near:
            continue
        # Fica quem sai mais: mexe no menor número de coletas.
        anchor, mover, source = (first, second, there) if sold[first] >= sold[second] else (second, first, here)
        target = floor.free_near(floor.main(anchor), min(floor.near, gap - 1))
        moves = floor.moves(mover, source, target) if target else []
        if target:
            floor.busy.add(target.pk)
        floor.claimed.update({first, second})
        action = (f"Mova {_name(floor, mover)} de {source.code} para {target.code}, perto de {floor.main(anchor).code}." if target else
                  f"Não há endereço livre perto de {floor.main(anchor).code}: libere um para aproximar os dois.")
        key = ":".join(sorted((str(first), str(second))))
        found.append(Found(StockAdvice.Kind.TOGETHER, key, f"{_name(floor, first)} e {_name(floor, second)} saem juntos, mas estão longe",
                           f"Saíram na mesma venda {count} vezes em {PERIOD_DAYS} dias, {lift:.1f} vezes mais do que o acaso explica, e estão "
                           f"a {gap} endereços de distância na rota ({here.code} e {there.code}). {action}", count, moves))
    return found


def _fast(floor, baskets):
    sold = Counter()
    for items in baskets.values():
        sold.update(items)
    ranking = [(variant_id, n) for variant_id, n in sold.most_common() if floor.rows.get(variant_id) and floor.main(variant_id)]
    top = ranking[:max(3, math.ceil(len(ranking) * FAST_SHARE))]  # catálogo pequeno: 20% seriam um ou dois produtos
    found, half, third = [], len(floor.route) // 2, max(1, len(floor.route) // 3)
    for variant_id, count in top:
        if count < MIN_LINES_FAST or len(found) >= MAX_PER_KIND:
            break
        here = floor.main(variant_id)
        if variant_id in floor.claimed or floor.rank[here.pk] < half or here.kind == StorageBin.Kind.PICKING:
            continue
        picking = [i for i, item in enumerate(floor.route) if item.kind == StorageBin.Kind.PICKING]
        target = floor.free(picking) or floor.free(range(third))
        moves = floor.moves(variant_id, here, target) if target else []
        if target:
            floor.busy.add(target.pk)
        floor.claimed.add(variant_id)
        action = f"Mova para {target.code}, no início da rota." if target else "Não há endereço livre no início da rota: libere um."
        found.append(Found(StockAdvice.Kind.FAST, str(variant_id), f"{_name(floor, variant_id)} sai muito e está no fim da rota",
                           f"Saiu em {count} vendas em {PERIOD_DAYS} dias e está em {here.code}, a posição {floor.rank[here.pk] + 1} de "
                           f"{len(floor.route)} na rota. {action}", count, moves))
    return found


def _scattered(floor):
    found = []
    for variant_id, rows in floor.rows.items():
        if variant_id in floor.claimed or len(found) >= MAX_PER_KIND:
            continue
        if any(row.lot_id and row.lot.expires_at for row in rows):
            continue
        places = Counter()
        for row in rows:
            if row.bin_id in floor.rank:
                places[row.bin_id] += row.quantity
        if len(places) < SCATTERED_BINS:
            continue
        target = floor.main(variant_id)
        ordered = sorted(places, key=floor.rank.get)
        moves = [move for pk in ordered if pk != target.pk for move in floor.moves(variant_id, floor.route[floor.rank[pk]], target)]
        codes = ", ".join(floor.route[floor.rank[pk]].code for pk in ordered)
        floor.claimed.add(variant_id)
        found.append(Found(StockAdvice.Kind.SCATTERED, str(variant_id), f"{_name(floor, variant_id)} está em {len(places)} endereços",
                           f"Está em {codes}. Junte tudo em {target.code}: a coleta passa em um lugar só e a contagem fica mais simples.",
                           len(places), moves))
    return found


def _idle(floor, baskets):
    sold = set().union(*baskets.values()) if baskets else set()
    limit, found = floor.now - timedelta(days=IDLE_DAYS), []
    front = len(floor.route) // 5
    back = [i for i in range(len(floor.route) // 2, len(floor.route)) if floor.route[i].kind == StorageBin.Kind.STORAGE]
    for variant_id, rows in floor.rows.items():
        if variant_id in floor.claimed or variant_id in sold or len(found) >= MAX_PER_KIND:
            continue
        here = floor.main(variant_id)
        if here is None or not (here.kind == StorageBin.Kind.PICKING or floor.rank[here.pk] < front):
            continue
        if any(row.updated_at >= limit for row in rows):  # chegou agora: ainda não teve tempo de vender
            continue
        target = floor.free(back)
        if target is None:
            continue
        floor.busy.add(target.pk)
        floor.claimed.add(variant_id)
        found.append(Found(StockAdvice.Kind.IDLE, str(variant_id), f"{_name(floor, variant_id)} não sai e ocupa a frente da rota",
                           f"Sem venda em {PERIOD_DAYS} dias e guardado em {here.code}. Mova para {target.code} e libere o endereço para o que sai mais.",
                           1, floor.moves(variant_id, here, target)))
    return found


def recommend(warehouse, now=None):
    """O que recomendar neste depósito agora. Não grava nada."""
    now = now or timezone.now()
    floor = _floor(warehouse, now)
    baskets = _baskets(warehouse, now)
    patterns = len(baskets) >= MIN_SALES and len(floor.route) > 1  # com poucas vendas, nenhum padrão é confiável
    found = _dock(floor)
    if patterns:
        found += _together(floor, baskets) + _fast(floor, baskets)
    found += _scattered(floor)
    if patterns:
        found += _idle(floor, baskets)
    return found


def analyze(account):
    """Refaz as recomendações da conta. O que deixou de valer sai da lista; recusado e aceito não voltam por um tempo."""
    if not enabled(account):
        return 0
    now, keep, opened = timezone.now(), timezone.now() - timedelta(days=KEEP_DECISION_DAYS), 0
    warehouses = Warehouse.all_objects.filter(account=account, uses_bins=True, deleted_at__isnull=True).select_related("store")
    alive = set()
    for warehouse in warehouses:
        for item in recommend(warehouse, now):
            fingerprint = f"{item.kind}:{warehouse.pk}:{item.key}"
            current = StockAdvice.all_objects.filter(account=account, fingerprint=fingerprint, deleted_at__isnull=True).first()
            if current and current.status in (StockAdvice.Status.APPLIED, StockAdvice.Status.DISMISSED) and current.decided_at and current.decided_at >= keep:
                continue
            alive.add(fingerprint)
            values = {"title": item.title[:200], "detail": item.detail, "impact": item.impact, "moves": item.moves, "checked_at": now,
                      "status": StockAdvice.Status.OPEN, "document": None, "decided_by": None, "decided_at": None}
            if current is None:
                StockAdvice.all_objects.create(account=account, store=warehouse.store, warehouse=warehouse, kind=item.kind,
                                               fingerprint=fingerprint, **values)
                opened += 1
            else:
                opened += current.status != StockAdvice.Status.OPEN
                for name, value in values.items():
                    setattr(current, name, value)
                current.save()
    stale = StockAdvice.all_objects.filter(account=account, status=StockAdvice.Status.OPEN, deleted_at__isnull=True).exclude(fingerprint__in=alive)
    stale.update(status=StockAdvice.Status.EXPIRED, updated_at=now)
    _alert(account)
    return opened


def _alert(account):
    """Um alerta por filial, com o total: uma linha por recomendação encheria a lista de quem supervisiona."""
    from starrp.services.cosmos import supervision

    counts = Counter(StockAdvice.all_objects.filter(account=account, status=StockAdvice.Status.OPEN, deleted_at__isnull=True)
                     .values_list("store_id", flat=True))
    still = {f"{ALERT}{store}:{count}" for store, count in counts.items()}
    supervision._settle(account, ALERT, still)
    for store, count in counts.items():
        text = "1 recomendação" if count == 1 else f"{count} recomendações"
        supervision.open_finding(account.pk, f"{ALERT}{store}:{count}", rule="organizacao_estoque", severity=CosmosFinding.Severity.INFO,
                                 title=f"Estoque: {text} para agilizar a separação",
                                 detail="Veja em Estoque › Organização do estoque. Aceitar cria uma movimentação em rascunho para a equipe conferir.",
                                 store_id=store, entity="stockadvice", endpoint="stock/advices")


def _settle_store(advice):
    from starrp.services.cosmos import supervision

    left = StockAdvice.all_objects.filter(account_id=advice.account_id, store_id=advice.store_id, status=StockAdvice.Status.OPEN,
                                          deleted_at__isnull=True).exists()
    if not left:
        supervision._settle(advice.account, f"{ALERT}{advice.store_id}:", set())


def _decide(advice, status, user, document=None):
    advice.status, advice.decided_by, advice.decided_at, advice.document, advice.updated_by = status, user, timezone.now(), document, user
    advice.save()
    _settle_store(advice)
    return advice


@transaction.atomic
def apply(advice, user):
    """Aceitou: cria a movimentação em RASCUNHO, com o saldo de agora. O estoque só muda quando a equipe confirmar o documento."""
    advice = StockAdvice.all_objects.select_for_update().select_related("warehouse", "store", "account").get(pk=advice.pk)
    if advice.status != StockAdvice.Status.OPEN:
        raise StateConflict("Esta recomendação já foi decidida.")
    if not advice.moves:
        raise BusinessError("Não há endereço livre para esta recomendação: libere um e clique em Analisar agora.", code="advice_no_target")
    bins = StorageBin.all_objects.filter(account_id=advice.account_id, warehouse=advice.warehouse, deleted_at__isnull=True).in_bulk(
        {move["from_bin"] for move in advice.moves} | {move["to_bin"] for move in advice.moves})
    lines = []
    for move in advice.moves:
        source, target = bins.get(_uuid(move["from_bin"])), bins.get(_uuid(move["to_bin"]))
        if source is None or target is None or not target.is_active:
            raise StateConflict("Um dos endereços mudou desde a análise. Clique em Analisar agora.")
        taken = BinBalance.all_objects.filter(bin=target, quantity__gt=0).exclude(variant_id=move["variant"]).exists()
        if taken:
            raise StateConflict(f"O endereço {target.code} foi ocupado desde a análise. Clique em Analisar agora.")
        row = BinBalance.all_objects.filter(bin=source, variant_id=move["variant"], lot_id=move["lot"], quantity__gt=0).first()
        if row is not None:
            lines.append((row, source, target))
    if not lines:
        raise StateConflict("O saldo já saiu destes endereços desde a análise. Clique em Analisar agora.")
    today = timezone.localdate()
    document = StockDocument.all_objects.create(
        account_id=advice.account_id, store=advice.store, kind=StockDocument.Kind.RELOCATION, warehouse=advice.warehouse,
        number=numbering.next_number(advice.store, "stock_document"), effective_date=today, reason=f"Recomendação da Cosmos: {advice.title}"[:500],
        created_by=user, updated_by=user)
    for row, source, target in lines:
        StockDocumentItem.all_objects.create(account_id=advice.account_id, document=document, variant_id=row.variant_id, lot_id=row.lot_id,
                                             quantity=row.quantity, bin=source, destination_bin=target, created_by=user, updated_by=user)
    return _decide(advice, StockAdvice.Status.APPLIED, user, document)


def dismiss(advice, user):
    if advice.status != StockAdvice.Status.OPEN:
        raise StateConflict("Esta recomendação já foi decidida.")
    return _decide(advice, StockAdvice.Status.DISMISSED, user)


def _uuid(value):
    from uuid import UUID

    return UUID(str(value))
