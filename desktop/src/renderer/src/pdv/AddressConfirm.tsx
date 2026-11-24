/**
 * Etapa entre a venda e o pagamento (regra da filial "Confirmar endereço antes do pagamento"):
 * o endereço de entrega e de cobrança do pedido, herdados do cliente, para conferir e corrigir.
 * Confirmar grava no pedido (o cadastro do cliente não muda) e segue para o pagamento.
 */
import { useState } from "react";

import { blankAddress, type OrderAddress, type OrderAddresses, salesApi } from "@/api/pdv";
import type { Sale } from "@/api/types";
import { notify } from "@/state/toast";
import { Button, Field, IconButton, Input } from "@/ui";

import AddressFields from "./AddressFields";

export default function AddressConfirm({ sale, onConfirmed, onBack }: {
  sale: Sale; onConfirmed: (addresses: OrderAddresses) => void; onBack: () => void;
}) {
  const [draft, setDraft] = useState<OrderAddresses>(() => JSON.parse(JSON.stringify(sale.addresses)) as OrderAddresses);
  const [saving, setSaving] = useState(false);

  async function confirm() {
    setSaving(true);
    try {
      // Venda montada no PC: os endereços vão junto com ela ao servidor (nada a gravar agora).
      onConfirmed(sale.id.startsWith("off:") ? draft : await salesApi.saveAddresses(sale.id, draft));
    } catch (error) {
      notify.error(error, "Confira o endereço");
    } finally {
      setSaving(false);
    }
  }

  const recipient = (key: "delivery" | "billing", addr: OrderAddress) => (
    <Field label="Recebedor" className="col-span-12">
      <Input value={addr.recipient} disabled={saving} onChange={(e) => setDraft({ ...draft, [key]: { ...addr, recipient: e.target.value } })} />
    </Field>
  );

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <header className="flex items-center gap-2.5">
        <IconButton icon="pi pi-arrow-left" label="Voltar para a venda" onClick={onBack} />
        <div>
          <h2 className="panel-title">Confirme o endereço</h2>
          <p className="text-[13px] text-muted">
            Pedido {sale.number}{sale.customer_name ? ` de ${sale.customer_name}` : ""}: veio do cadastro do cliente.
            Corrija o que estiver errado (vale só para este pedido).
          </p>
        </div>
      </header>

      {draft.delivery && (
        <div className="flex flex-col gap-2 rounded-[10px] border border-line bg-card p-3.5">
          <span className="eyebrow">Endereço de entrega</span>
          <AddressFields value={draft.delivery} disabled={saving} onChange={(delivery) => setDraft({ ...draft, delivery })}
            extra={recipient("delivery", draft.delivery)} />
        </div>
      )}

      <label className="flex items-center gap-2 text-[13.5px] text-body">
        <input type="checkbox" checked={draft.billing_same_as_delivery} disabled={saving} className="size-4 accent-[var(--brand)]"
          onChange={(e) => setDraft({ ...draft, billing_same_as_delivery: e.target.checked,
            billing: e.target.checked ? null : draft.billing ?? { ...(draft.delivery ?? blankAddress()) } })} />
        Cobrança no mesmo endereço da entrega
      </label>
      {!draft.billing_same_as_delivery && draft.billing && (
        <div className="flex flex-col gap-2 rounded-[10px] border border-line bg-card p-3.5">
          <span className="eyebrow">Endereço de cobrança</span>
          <AddressFields value={draft.billing} disabled={saving} onChange={(billing) => setDraft({ ...draft, billing })}
            extra={recipient("billing", draft.billing)} />
        </div>
      )}

      <footer className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onBack}>Voltar</Button>
        <Button autoFocus loading={saving} onClick={() => void confirm()}>Confirmar e ir para o pagamento <i className="pi pi-arrow-right" /></Button>
      </footer>
    </section>
  );
}
