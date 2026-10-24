"""Lista de separação (picking) de um documento de saída/transferência em rascunho.

Diz ao separador ONDE pegar cada item — endereço e lote — na ordem do
caminho físico do depósito (`StorageBin.sequence`). Não grava nada: o
separador confere, e a confirmação do documento é que baixa o estoque,
seguindo o mesmo plano (`services.wms.plan`).

Traz também os volumes (caixas) a separar e o peso/cubagem da carga.
"""
from starrp.core.errors import StateConflict
from starrp.models import StockDocument
from starrp.services import stock, volumes, wms

PICKABLE = {StockDocument.Kind.EXIT, StockDocument.Kind.TRANSFER, StockDocument.Kind.SUPPLIER_RETURN,
            StockDocument.Kind.RELOCATION}


def picking_list(document):
    if document.kind not in PICKABLE:
        raise StateConflict("Lista de separação só existe para saída, transferência e movimentação.")
    warehouse = document.warehouse
    settings = stock.settings_for(document.account_id)
    lines, shortages = [], []
    items = list(document.items.select_related("variant__product", "bin", "lot"))
    for item in items:
        if warehouse.uses_bins:
            picks, missing = wms.plan(item.variant, warehouse, item.quantity, settings, bin=item.bin, lot=item.lot)
            lines += [{
                "bin": pick.bin.code, "sequence": pick.bin.sequence, "variant": str(item.variant_id),
                "description": item.variant.display_name, "sku": item.variant.sku,
                "lot": pick.lot.lot_number or pick.lot.code if pick.lot else "",
                "expires_at": pick.lot.expires_at if pick.lot else None, "quantity": pick.quantity,
            } for pick in picks]
        else:
            missing = max(item.quantity - stock.available(item.variant, warehouse), 0)
            lines.append({"bin": "", "sequence": 0, "variant": str(item.variant_id),
                          "description": item.variant.display_name, "sku": item.variant.sku,
                          "lot": item.lot.lot_number if item.lot else "", "expires_at": None,
                          "quantity": item.quantity})
        if missing > 0:
            shortages.append({"variant": str(item.variant_id), "description": item.variant.display_name,
                              "missing_quantity": missing})
    lines.sort(key=lambda line: (line["sequence"], line["bin"], line["description"]))
    load = volumes.shipping_totals((item.variant, item.quantity) for item in items)
    return {"document": document.number, "warehouse": warehouse.name, "lines": lines, "shortages": shortages,
            "load": load}
