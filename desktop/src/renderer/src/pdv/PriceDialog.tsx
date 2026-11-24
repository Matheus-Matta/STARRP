/** Consulta de preço (F5): lê o código e mostra preço vigente, promoção e estoque, sem lançar na venda. */
import { useEffect, useState } from "react";

import { salesApi } from "@/api/pdv";
import type { VariantLookup } from "@/api/types";
import { money, quantity } from "@/lib/format";
import { Dialog, Input } from "@/ui";

export default function PriceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [code, setCode] = useState("");
  const [found, setFound] = useState<VariantLookup | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setFound(null);
    setError("");
    setCode("");
  }, [open]);

  async function check() {
    const value = code.trim();
    if (!value) return;
    setError("");
    try {
      setFound(await salesApi.lookup(value));
    } catch {
      setFound(null);
      setError(`Nada encontrado para “${value}”.`);
    }
    setCode("");
  }

  return (
    <Dialog open={open} title="Consulta de preço" onClose={onClose} width={460}>
      <Input autoFocus value={code} onChange={(e) => setCode(e.target.value)} placeholder="Leia ou digite o código e tecle Enter"
        onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), void check())} />
      {error && <p className="mt-3 text-[13px] font-semibold text-danger-text">{error}</p>}
      {found && (
        <div className="mt-4 flex flex-col gap-1 rounded-xl border border-line bg-sunken p-4">
          <strong className="text-[15px] text-strong">{found.display_name}</strong>
          <small className="font-mono text-muted">{found.sku}</small>
          <span className="mt-1 text-[28px] font-extrabold text-brand">
            {found.list_price !== found.current_price && <s className="mr-2 text-[15px] font-semibold text-muted">{money(found.list_price)}</s>}
            {money(found.current_price)}{found.sold_by_weight && <small className="text-[14px] text-muted"> / kg</small>}
          </span>
          {found.stock_quantity != null && <small className="text-muted">{quantity(found.stock_quantity)} em estoque</small>}
        </div>
      )}
    </Dialog>
  );
}
