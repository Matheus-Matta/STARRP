/**
 * Ações do pedido aberto em Pedidos (F2), as mesmas da retaguarda web (`resources/sales.ts`),
 * cada uma com a permissão do cargo — o backend confere de novo:
 *
 * - Endereços (entrega e cobrança só deste pedido);
 * - Alterar entrega (`sales.edit_delivery`): retirada ou outro endereço/tabela; o frete cobrado não muda;
 * - Trocar pagamento (`sales.edit_payment`): troca a FORMA de um pagamento, mesmo valor;
 * - Cancelar pedido: nota autorizada vai junto (justificativa da SEFAZ de 15 a 255 caracteres);
 *   sem `sales.cancel`, o gerente autoriza na hora;
 * - Emitir nota (NFC-e/NF-e por este PC) e imprimir a nota na impressora configurada ou em outra.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { blankAddress, customersApi, logisticsApi, type OrderAddresses, salesApi } from "@/api/pdv";
import type { Sale } from "@/api/types";
import { money } from "@/lib/format";
import { CANCEL_SALE_REASONS } from "@/lib/reasons";
import { PrinterEditor } from "@/pages/SettingsDialog";
import { ApprovalCancelled, withApproval } from "@/state/approval";
import { session } from "@/state/session";
import { useStore } from "@/state/store";
import { notify } from "@/state/toast";
import { Button, cx, Dialog, Field, Input, Segmented, Select, Toggle } from "@/ui";

import type { PrinterTarget } from "../../../shared/ipc";
import AddressFields from "./AddressFields";

type Done = () => void;

/* ── endereços ─────────────────────────────────────────────────────────────── */

export function AddressesDialog({ sale, onClose, onDone }: { sale: Sale; onClose: () => void; onDone: Done }) {
  const current = sale.addresses as unknown as OrderAddresses | undefined;
  const [draft, setDraft] = useState<OrderAddresses>(() => structuredClone(current?.delivery ? current
    : { delivery: blankAddress(), billing: null, billing_same_as_delivery: true }));
  const [saving, setSaving] = useState(false);
  async function run(body: Partial<OrderAddresses> & { inherit?: boolean }, message: string) {
    setSaving(true);
    try {
      await salesApi.saveAddresses(sale.id, body);
      notify.success(message);
      onDone();
    } catch (error) {
      notify.error(error, "Endereço não salvo");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog open onClose={onClose} width={640} title="Endereços do pedido"
      footer={<>
        {sale.customer && <Button variant="ghost" icon="pi pi-user" disabled={saving} onClick={() => void run({ inherit: true } as never, "Endereços copiados do cliente")}>Usar o do cliente</Button>}
        <Button variant="ghost" onClick={onClose}>Fechar</Button>
        <Button icon="pi pi-check" loading={saving} onClick={() => void run(draft, "Endereços do pedido salvos")}>Salvar</Button>
      </>}>
      <p className="mb-3 text-[12.5px] text-muted">Vale só para este pedido: o cadastro do cliente fica como está.</p>
      <h3 className="mb-1.5 text-[13px] font-bold text-strong">Entrega</h3>
      <AddressFields value={draft.delivery ?? blankAddress()} onChange={(delivery) => setDraft({ ...draft, delivery })}
        extra={<Field label="Quem recebe"><Input value={draft.delivery?.recipient ?? ""} onChange={(e) => setDraft({ ...draft, delivery: { ...(draft.delivery ?? blankAddress()), recipient: e.target.value } })} /></Field>} />
      <div className="mt-3">
        <Toggle checked={draft.billing_same_as_delivery} label="Cobrança no mesmo endereço"
          onChange={(same) => setDraft({ ...draft, billing_same_as_delivery: same, billing: same ? null : draft.billing ?? blankAddress() })} />
      </div>
      {!draft.billing_same_as_delivery && (
        <>
          <h3 className="mt-2 mb-1.5 text-[13px] font-bold text-strong">Cobrança</h3>
          <AddressFields value={draft.billing ?? blankAddress()} onChange={(billing) => setDraft({ ...draft, billing })} />
        </>
      )}
    </Dialog>
  );
}

/* ── alterar entrega ───────────────────────────────────────────────────────── */

export function DeliveryEditDialog({ sale, onClose, onDone }: { sale: Sale; onClose: () => void; onDone: Done }) {
  const [mode, setMode] = useState<"delivery" | "pickup">(sale.shipping_address ? "delivery" : "pickup");
  const customer = useQuery({ queryKey: ["order-customer", sale.customer], queryFn: () => customersApi.get(sale.customer!), enabled: Boolean(sale.customer) });
  const addresses = customer.data?.addresses ?? [];
  const [chosen, setChosen] = useState<string | null>(sale.shipping_address);
  useEffect(() => {
    if (addresses.length && !addresses.some((a) => a.id === chosen)) setChosen(addresses[0]!.id ?? null);
  }, [addresses.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const address = addresses.find((a) => a.id === chosen) ?? null;
  const quotes = useQuery({
    queryKey: ["order-delivery-quote", address?.zip_code], queryFn: () => logisticsApi.quote(address!.zip_code),
    enabled: mode === "delivery" && (address?.zip_code ?? "").replace(/\D/g, "").length === 8,
  });
  const current = ((sale.metafields ?? {}) as { _entrega?: { table: string } })._entrega;
  const [table, setTable] = useState<string | null>(current?.table ?? null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const ready = reason.trim() && (mode === "pickup" || (address && table));

  async function save() {
    setSaving(true);
    try {
      await salesApi.editDelivery(sale.id, mode === "pickup" ? { pickup: true, reason } : { address: address!.id!, table, reason });
      notify.success("Entrega do pedido alterada");
      onDone();
    } catch (error) {
      notify.error(error, "Entrega não alterada");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog open onClose={onClose} width={560} title="Alterar entrega"
      footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button><Button icon="pi pi-check" disabled={!ready} loading={saving} onClick={() => void save()}>Alterar</Button></>}>
      <div className="flex flex-col gap-3">
        <p className="text-[12.5px] text-muted">O frete cobrado ({money(sale.freight)}) não muda: a venda já está paga. Diferença de frete se acerta à parte.</p>
        <Segmented value={mode} onChange={setMode} options={[{ value: "delivery", label: "Entregar" }, { value: "pickup", label: "Retirar na loja" }]} />
        {mode === "delivery" && (
          !sale.customer ? <p className="text-[13px] text-danger-text">Vincule um cliente ao pedido para escolher o endereço.</p> : (
            <>
              <Field label="Endereço do cliente">
                <Select value={chosen} onChange={setChosen} placeholder={addresses.length ? undefined : "O cliente não tem endereço"}
                  options={addresses.map((a) => ({ value: a.id!, label: [[a.street, a.number].filter(Boolean).join(", "), a.district, a.city].filter(Boolean).join(" · ") }))} />
              </Field>
              <Field label="Tabela de frete">
                <Select value={table} onChange={setTable} placeholder={quotes.isFetching ? "Cotando…" : "Escolha a tabela"}
                  options={(quotes.data ?? []).filter((q) => !q.error).map((q) => ({ value: q.table, label: `${q.table_name} · ${q.value == null ? "—" : money(q.value)}${q.lead_days != null ? ` · ${q.lead_days} dia(s)` : ""}` }))} />
              </Field>
            </>
          )
        )}
        <Field label="Motivo *"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: cliente pediu para entregar no trabalho" /></Field>
      </div>
    </Dialog>
  );
}

/* ── trocar pagamento ──────────────────────────────────────────────────────── */

const NEEDS_CUSTOMER = new Set(["installment_plan", "store_credit"]);

export function PaymentChangeDialog({ sale, onClose, onDone }: { sale: Sale; onClose: () => void; onDone: Done }) {
  const payments = sale.payments.filter((p) => p.status === "approved");
  const methods = useQuery({ queryKey: ["order-payment-methods"], queryFn: salesApi.paymentMethods });
  const options = (methods.data?.results ?? []).filter((m) => !(NEEDS_CUSTOMER.has(m.kind) && !sale.customer));
  const [paymentId, setPaymentId] = useState<string | null>(payments.length === 1 ? payments[0]!.id : null);
  const payment = payments.find((p) => p.id === paymentId) ?? null;
  const [methodId, setMethodId] = useState<string | null>(null);
  const method = options.find((m) => m.id === methodId) ?? null;
  const [installments, setInstallments] = useState(1);
  const [nsu, setNsu] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const invoiced = (sale.invoices ?? []).some((i) => i.status === "authorized");
  const ready = payment && method && method.id !== payment.method && reason.trim();

  async function save() {
    setSaving(true);
    try {
      await salesApi.changePayment(sale.id, payment!.id, { method: method!.id, installments, nsu, reason });
      notify.success("Forma de pagamento trocada", `${payment!.method_name} → ${method!.name}`);
      onDone();
    } catch (error) {
      notify.error(error, "Pagamento não trocado");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog open onClose={onClose} width={520} title="Trocar forma de pagamento"
      footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button><Button icon="pi pi-check" disabled={!ready} loading={saving} onClick={() => void save()}>Trocar</Button></>}>
      <div className="flex flex-col gap-3">
        <p className="text-[12.5px] text-muted">Mesmo valor, outra forma ("lançou PIX, foi cartão"). O antigo é estornado (conta, título, gaveta) e o novo gera o que a forma nova gera.
          {invoiced && " A nota fiscal já emitida não muda."}</p>
        <Field label="Pagamento">
          <Select value={paymentId} onChange={setPaymentId} placeholder="Escolha"
            options={payments.map((p) => ({ value: p.id, label: `${p.method_name} · ${money(p.amount)}${(p.installments ?? 1) > 1 ? ` · ${p.installments}x` : ""}` }))} />
        </Field>
        <div className="grid grid-cols-[1fr_120px] gap-3">
          <Field label="Nova forma">
            <Select value={methodId} onChange={(v) => { setMethodId(v); setInstallments(1); }} placeholder="Escolha"
              options={options.map((m) => ({ value: m.id, label: m.name, disabled: m.id === payment?.method }))} />
          </Field>
          <Field label="Parcelas">
            <Select value={installments} onChange={(v) => setInstallments(v ?? 1)}
              options={Array.from({ length: Math.max(1, method?.max_installments ?? 1) }, (_, n) => ({ value: n + 1, label: `${n + 1}x` }))} />
          </Field>
        </div>
        <Field label="NSU / autorização (cartão)"><Input value={nsu} onChange={(e) => setNsu(e.target.value)} /></Field>
        <Field label="Motivo *"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: o caixa lançou PIX, mas foi cartão" /></Field>
      </div>
    </Dialog>
  );
}

/* ── cancelar pedido ───────────────────────────────────────────────────────── */

export function CancelOrderDialog({ sale, onClose, onDone }: { sale: Sale; onClose: () => void; onDone: Done }) {
  const invoice = (sale.invoices ?? []).find((i) => i.status === "authorized") ?? null;
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const min = invoice ? 15 : 3;
  const text = reason.trim();
  const ready = text.length >= min && text.length <= 255;
  const payments = sale.payments.filter((p) => p.status === "approved");

  async function save() {
    setSaving(true);
    try {
      if (invoice) await withApproval((approval) => salesApi.cancelInvoice(invoice.id, { reason: text, with_sale: true, approval }));
      else await withApproval((approval) => salesApi.cancel(sale.id, { reason: text, approval }));
      notify.success(`Pedido ${sale.number} cancelado`, payments.length ? "Pagamentos reembolsados (cartão/PIX: estorne na maquininha/banco)." : undefined);
      onDone();
    } catch (error) {
      if (!(error instanceof ApprovalCancelled)) notify.error(error, "Pedido não cancelado");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog open onClose={onClose} width={540} title={`Cancelar pedido ${sale.number}`}
      footer={<><Button variant="ghost" onClick={onClose}>Voltar</Button><Button variant="danger" icon="pi pi-times-circle" disabled={!ready} loading={saving} onClick={() => void save()}>Cancelar pedido</Button></>}>
      <div className="flex flex-col gap-3 text-[13px]">
        <ul className="list-disc pl-5 text-muted">
          {invoice && <li>A <b className="text-strong">{invoice.label}</b> autorizada é cancelada na SEFAZ (NFC-e até 30 min, NF-e até 24 h).</li>}
          {sale.status === "completed" && <li>O estoque volta, a comissão e o cupom saem e os títulos são cancelados.</li>}
          {payments.length > 0 && <li>Reembolso de {payments.map((p) => `${p.method_name} ${money(p.amount)}`).join(", ")}.</li>}
        </ul>
        <div className="flex flex-wrap gap-1.5">
          {CANCEL_SALE_REASONS.map((r) => <button key={r} type="button" onClick={() => setReason(r)}
            className={cx("rounded-full border px-2.5 py-1 text-[12px]", reason === r ? "border-brand text-brand-text" : "border-line text-muted hover:text-strong")}>{r}</button>)}
        </div>
        <Field label={invoice ? `Justificativa (vai para a SEFAZ — ${text.length}/255, mínimo 15)` : "Motivo"}>
          <Input value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

/* ── emitir e imprimir nota ────────────────────────────────────────────────── */

export function EmitDialog({ sale, onClose, onEmit }: { sale: Sale; onClose: () => void; onEmit: (model: "65" | "55") => void }) {
  const { config } = useStore(session);
  const [model, setModel] = useState<"65" | "55">(config?.fiscal.model ?? "65");
  const needsDocument = model === "55" && sale.customer_document.replace(/\D/g, "").length < 11;
  return (
    <Dialog open onClose={onClose} width={440} title="Emitir nota fiscal"
      footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button><Button icon="pi pi-send" disabled={needsDocument} onClick={() => onEmit(model)}>Emitir</Button></>}>
      <div className="flex flex-col gap-3 text-[13px]">
        <Segmented value={model} onChange={setModel} options={[{ value: "65", label: "NFC-e (cupom)" }, { value: "55", label: "NF-e" }]} />
        <p className="text-muted">Pelo comunicador ACBr deste computador. Sem SEFAZ, a NFC-e sai em contingência e é transmitida depois.</p>
        {needsDocument && <p className="text-danger-text">A NF-e precisa do CPF/CNPJ do cliente no pedido.</p>}
      </div>
    </Dialog>
  );
}

export function PrinterPickDialog({ title, onClose, onPrint }: { title: string; onClose: () => void; onPrint: (target: PrinterTarget) => void }) {
  const { config } = useStore(session);
  const [target, setTarget] = useState<PrinterTarget>(() => structuredClone(config!.printing.fiscal));
  return (
    <Dialog open onClose={onClose} width={560} title={title}
      footer={<><Button variant="ghost" onClick={onClose}>Cancelar</Button><Button icon="pi pi-print" onClick={() => onPrint(target)}>Imprimir</Button></>}>
      <PrinterEditor title="Imprimir em" value={target} onChange={setTarget} />
    </Dialog>
  );
}
