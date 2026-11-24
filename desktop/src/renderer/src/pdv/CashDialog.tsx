/**
 * Caixa: abrir turno, sangria/suprimento e fechamento (com contagem cega). A abertura NÃO pergunta
 * o caixa: usa o do usuário ou, sem caixa próprio, o 1º livre; nenhum livre = aviso, sem abrir.
 */
import { type FormEvent, useEffect, useState } from "react";

import type { CashRegister } from "@/api/types";
import { Button, Dialog, Field, Input, MoneyInput } from "@/ui";

export type CashMode = "open" | "withdrawal" | "supply" | "close";

const TITLES: Record<CashMode, string> = { open: "Abrir caixa", withdrawal: "Sangria", supply: "Suprimento", close: "Fechar caixa" };
const AMOUNT_LABEL: Record<CashMode, string> = {
  open: "Dinheiro contado na gaveta", withdrawal: "Valor retirado", supply: "Valor colocado", close: "Dinheiro contado na gaveta",
};

export default function CashDialog({ open, mode, registers, myRegister, busy, onClose, onConfirm }: {
  open: boolean; mode: CashMode; registers: CashRegister[]; myRegister: string | null; busy: boolean; onClose: () => void;
  onConfirm: (data: { register?: string; amount: string; reason: string }) => void;
}) {
  const [amount, setAmount] = useState<number | null>(0);
  const [reason, setReason] = useState("");
  const mine = registers.find((r) => r.id === myRegister) ?? null;
  const chosen = mine ?? registers.find((r) => !r.in_use_by) ?? null;

  useEffect(() => {
    if (!open) return;
    setAmount(mode === "open" ? 0 : null);
    setReason("");
  }, [open, mode]);

  function confirm(event: FormEvent) {
    event.preventDefault();
    if (amount === null || (mode === "open" && !chosen)) return;
    onConfirm({ register: mode === "open" ? chosen?.id : undefined, amount: amount.toFixed(2), reason });
  }

  return (
    <Dialog open={open} title={TITLES[mode]} onClose={onClose} width={420}>
      <form className="flex flex-col gap-3" onSubmit={confirm}>
        {mode === "open" && chosen && (
          <div className="flex items-center gap-2 rounded-lg bg-brand-subtle px-3 py-2.5 text-brand-text">
            <i className="pi pi-wallet" /><strong>{chosen.name}</strong>
            <small className="ml-auto text-muted">{mine ? "o seu caixa" : "caixa livre da filial"}</small>
          </div>
        )}
        {mode === "open" && !chosen && (
          <p className="flex gap-2 rounded-lg bg-warning-subtle px-3 py-2.5 text-[13px] text-warning-text">
            <i className="pi pi-exclamation-circle mt-0.5" />
            Nenhum caixa livre: {registers.length ? "todos estão com turno aberto." : "você não está vinculado a um caixa. Peça ao gerente em Financeiro › Caixas."}
          </p>
        )}
        <Field label={AMOUNT_LABEL[mode]}
          hint={mode === "close" ? "Conte o dinheiro antes: o sistema compara com o esperado depois."
            : mode === "open" ? "Conte o que está na gaveta e digite. Se não bater com o último fechamento, o gerente confere antes de vender." : undefined}>
          <MoneyInput autoFocus value={amount} onChange={setAmount} className="h-12 text-[18px] font-bold" />
        </Field>
        {mode !== "close" && (
          <Field label={mode === "open" ? "Observação (opcional)" : "Motivo"}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        )}
        <Button type="submit" size="lg" loading={busy} disabled={amount === null || (mode === "open" && !chosen)}>{TITLES[mode]}</Button>
      </form>
    </Dialog>
  );
}
