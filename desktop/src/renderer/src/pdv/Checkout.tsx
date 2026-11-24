/**
 * Tela de pagamento (não é modal): à esquerda a CONFERÊNCIA (itens, cliente, vendedor, entrega,
 * desconto, cupom, total e pagamentos lançados); à direita a forma, o valor e o teclado.
 *
 * O operador monta a lista (pode dividir em várias formas) e só no "Concluir venda" tudo vai junto
 * para o checkout — uma transação no backend. A lista mora no PdvPage: sair para trocar o cliente
 * ou a entrega e voltar não perde o que foi lançado. Troco só existe em dinheiro.
 * O valor entra com dígitos pela direita (centavos); enquanto ninguém digita, acompanha o que falta.
 */
import { saleLabel } from "./offline";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";

import type { PaymentInput } from "@/api/pdv";
import { deliveryOf, type PaymentMethod, type Sale, type SaleItem, type Seller } from "@/api/types";
import { money, quantity } from "@/lib/format";
import { Button, cx, IconButton, Input, Kbd, Select } from "@/ui";

import { orderedItems } from "./OrderPanel";

export type PaymentLine = PaymentInput & { name: string; kind: string };
export type CheckoutHandle = { finish: () => void };

const ICONS: Record<string, string> = {
  cash: "pi pi-money-bill", credit_card: "pi pi-credit-card", debit_card: "pi pi-credit-card", pix: "pi pi-qrcode",
  voucher: "pi pi-ticket", store_credit: "pi pi-replay", installment_plan: "pi pi-calendar", bank_slip: "pi pi-file",
};
const NEEDS_CUSTOMER = new Set(["installment_plan", "store_credit"]);

type Props = {
  sale: Sale; items: SaleItem[]; methods: PaymentMethod[]; sellers: Seller[]; operator: string; busy: boolean;
  requireReference: boolean; requireSeller: boolean; lines: PaymentLine[]; setLines: (lines: PaymentLine[]) => void;
  onBack: () => void; onFinish: (payments: PaymentInput[]) => void; onCustomer: () => void; onDelivery: () => void;
  onDiscount: () => void; onCoupon: () => void; onSeller: (id: number | null) => void;
};

const Checkout = forwardRef<CheckoutHandle, Props>(function Checkout(props, ref) {
  const { sale, items, methods, lines, setLines, busy } = props;
  const creditBalance = Number(sale.customer_credit_balance ?? 0);
  const queuedCredit = lines.filter((line) => line.kind === "store_credit")
    .reduce((sum, line) => sum + Number(line.amount), 0);
  const creditAvailable = Math.max(creditBalance - queuedCredit, 0);
  const blockedReason = (m: PaymentMethod) => {
    if (NEEDS_CUSTOMER.has(m.kind) && !sale.customer) return "exige cliente";
    if (m.kind === "store_credit" && creditAvailable <= 0.001) return "sem saldo";
    return "";
  };
  const blocked = (m: PaymentMethod) => Boolean(blockedReason(m));
  const { delivery, pickup } = deliveryOf(sale);
  const undecided = !delivery && !pickup;
  const customerLabel = sale.customer_name || (sale.customer_document ? `CPF/CNPJ ${sale.customer_document}` : "");
  const units = items.filter((i) => !i.parent_item).reduce((s, i) => s + ((i.unit ?? "UN") === "UN" ? Number(i.quantity) : 1), 0);

  /* ---- Valores ---- */
  const due = Number(sale.balance_due ?? sale.total);
  const paid = lines.reduce((s, l) => s + Number(l.amount), 0);
  const remaining = Math.max(due - paid, 0);
  const change = lines.reduce((s, l) => s + Math.max(Number(l.tendered ?? l.amount) - Number(l.amount), 0), 0);

  /* ---- Lançamento ---- */
  const [method, setMethod] = useState<PaymentMethod | null>(null);
  const [digits, setDigits] = useState("0");
  const [typed, setTyped] = useState(false);
  const [installments, setInstallments] = useState(1);
  const [reference, setReference] = useState("");
  const [error, setError] = useState("");
  const amountInput = useRef<HTMLInputElement>(null);
  const refInput = useRef<HTMLInputElement>(null);
  const amount = Number(digits) / 100;
  const isCash = method?.kind === "cash";
  const pendingChange = isCash ? Math.max(amount - remaining, 0) : 0;
  const centsOf = (value: number) => String(Math.round(value * 100));

  // O total mudou (desconto, cupom, frete) ou uma linha saiu: o visor volta a mostrar o que falta.
  useEffect(() => {
    if (!typed) setDigits(centsOf(method?.kind === "store_credit" ? Math.min(remaining, creditAvailable) : remaining));
  }, [remaining, typed, method?.kind, creditAvailable]);

  function pick(next: PaymentMethod | null) {
    if (next && blocked(next)) {
      setError(blockedReason(next) === "sem saldo"
        ? "O cliente não tem saldo disponível na carteira."
        : `${next.name} exige o cliente na venda: identifique o cliente antes (F3).`);
      return;
    }
    setMethod(next);
    setInstallments(1);
    setReference("");
    setError("");
    setTyped(false);
    setDigits(centsOf(next?.kind === "store_credit" ? Math.min(remaining, creditAvailable) : remaining));
  }

  useEffect(() => {
    pick(methods.find((m) => !blocked(m)) ?? null);
    setTimeout(() => amountInput.current?.focus());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function press(key: string) {
    setTyped(true);
    if (key === "clear") setDigits("0");
    else if (key === "back") setDigits((d) => (d.length <= 1 ? "0" : d.slice(0, -1)));
    else setDigits((d) => (d === "0" ? key : d + key).slice(0, 9));
  }

  /** Valor exato + notas comuns acima do saldo, para o troco sair em um toque. */
  const quickCash = useMemo(() => {
    const out = new Set<number>([Number(remaining.toFixed(2))]);
    for (const note of [5, 10, 20, 50, 100, 200]) {
      const v = Math.ceil(remaining / note) * note;
      if (v > remaining + 0.001) out.add(v);
    }
    return [...out].sort((a, b) => a - b).slice(0, 4);
  }, [remaining]);

  /** Lança a linha; devolve as linhas novas (ou null com a mensagem) — `value` força o valor. */
  function add(value = amount): PaymentLine[] | null {
    setError("");
    const m = method;
    if (!m) return setError("Escolha a forma de pagamento."), null;
    if (value <= 0) return setError("Informe o valor."), null;
    if (remaining <= 0.001) return setError("A venda já está paga."), null;
    const cash = m.kind === "cash";
    const line = cash ? Math.min(value, remaining) : value;
    if (!cash && line > remaining + 0.001) {
      return setError(`Em ${m.name} o valor não pode passar de ${money(remaining)} (troco só em dinheiro).`), null;
    }
    if (m.kind === "store_credit" && line > creditAvailable + 0.001) {
      return setError(`O crédito não pode passar do saldo disponível de ${money(creditAvailable)}.`), null;
    }
    if (m.requires_reference && props.requireReference && !reference.trim()) {
      setError(`Digite o NSU/autorização do comprovante de ${m.name}.`);
      refInput.current?.focus();
      return null;
    }
    const next = [...lines, {
      method: m.id, name: m.name, kind: m.kind, amount: line.toFixed(2), tendered: cash ? value.toFixed(2) : undefined,
      installments, ...(m.requires_reference && reference.trim() ? { nsu: reference.trim() } : {}),
    }];
    setLines(next);
    setReference("");
    setInstallments(1);
    setTyped(false);
    return next;
  }

  /** F10 / "Concluir": com valor no visor e saldo aberto, lança antes — pagamento único sai num toque. */
  function finish() {
    if (props.requireSeller && !sale.seller) return setError("Esta filial exige vendedor: escolha o vendedor na conferência ao lado.");
    if (undecided) return setError("Escolha se é entrega ou retirada na loja (Shift+F11) antes de concluir.");
    let current = lines;
    if (amount > 0 && remaining > 0.001) {
      const added = add();
      if (!added) return;
      current = added;
    }
    const total = current.reduce((s, l) => s + Number(l.amount), 0);
    if (total - due > 0.001) return setError("Os pagamentos passam do total (o desconto ou o cupom mudou). Remova um pagamento.");
    if (due - total > 0.001) return setError(`Ainda falta ${money(due - total)}.`);
    props.onFinish(current.map((l) => ({ method: l.method, amount: l.amount, tendered: l.tendered, installments: l.installments, nsu: l.nsu })));
  }
  useImperativeHandle(ref, () => ({ finish }));

  const changeTone = change > 0 ? "bg-brand-subtle border-brand-border [&_strong]:text-brand-text"
    : remaining > 0.001 ? "bg-warning-subtle border-transparent [&_strong]:text-warning-text"
      : "bg-success-subtle border-transparent [&_strong]:text-success-text";

  return (
    <>
      <section aria-label="Conferência da venda" className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pt-3 pb-4">
        <header className="flex items-start gap-2.5">
          <IconButton icon="pi pi-arrow-left" label="Voltar para a venda (Esc)" onClick={props.onBack} />
          <div>
            <h2 className="panel-title">Pagamento · Venda {saleLabel(sale)}</h2>
            <p className="text-[13px] text-muted">Confira tudo antes de receber. Voltar (Esc) mantém a venda como está.</p>
          </div>
        </header>

        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(240px,100%),1fr))] gap-2">
          <WhoCard icon="pi pi-user" label="Cliente" onClick={props.onCustomer} kbd="F3">{customerLabel || "Consumidor (sem cliente)"}</WhoCard>
          <WhoCard icon={delivery ? "pi pi-truck" : pickup ? "pi pi-shop" : "pi pi-exclamation-circle"} kbd="Shift+F11" todo={undecided}
            label={delivery ? `Entrega · ${delivery.table_name}` : "Entrega"} onClick={props.onDelivery}>
            {delivery ? `${delivery.address_label} · ${delivery.lead_days ? `${delivery.lead_days} dia(s) útil(eis)` : "no mesmo dia"}`
              : pickup ? "Retirada na loja" : "Escolha entrega ou retirada"}
          </WhoCard>
          <div className="flex min-h-14 items-center gap-2.5 rounded-[10px] border border-line-subtle bg-card px-3 py-2.5">
            <i className="pi pi-id-card text-[16px] text-brand" />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <small className="eyebrow">Vendedor</small>
              {props.sellers.length ? (
                <Select value={sale.seller ?? null} disabled={busy} className="h-8 text-[13px]" aria-invalid={(props.requireSeller && !sale.seller) || undefined}
                  placeholder={props.requireSeller ? "Escolha o vendedor (obrigatório)" : "Sem vendedor (fica com o caixa)"}
                  options={props.sellers.map((s) => ({ value: s.user_id, label: s.name }))} onChange={props.onSeller} />
              ) : <strong className="truncate text-[13.5px] text-strong">{sale.seller_name || "Sem vendedor"}</strong>}
            </span>
          </div>
          <div className="flex min-h-14 items-center gap-2.5 rounded-[10px] border border-line-subtle bg-card px-3 py-2.5">
            <i className="pi pi-desktop text-[16px] text-brand" />
            <span className="flex min-w-0 flex-col gap-0.5"><small className="eyebrow">Operador</small>
              <strong className="truncate text-[13.5px] text-strong">{props.operator || "—"}</strong></span>
          </div>
        </div>

        <Box title="Itens" aside={`${items.length} ${items.length === 1 ? "linha" : "linhas"} · ${quantity(units)} un.`}>
          <ul>
            {orderedItems(items).map((item) => (
              <li key={item.id} className={cx("flex items-baseline gap-2.5 border-t border-line-subtle py-[7px] text-[13.5px] first:border-t-0",
                item.parent_item && "pl-[18px]")}>
                <span className="min-w-[46px] font-bold text-strong tabular-nums">
                  {quantity(item.quantity)}{(item.unit ?? "UN") === "UN" ? "×" : ` ${(item.unit ?? "").toLowerCase()}`}
                </span>
                <span className="min-w-0 flex-1 text-strong">
                  {item.parent_item && <i className="pi pi-wrench mr-1 text-[11px] text-brand" />}{item.description}
                  <small className="block text-[12px] text-muted">
                    {money(item.unit_price)}
                    {Number(item.list_price) > Number(item.unit_price) && ` · de ${money(item.list_price)}`}
                    {item.promotion && <> · <b className="text-accent">promoção</b></>}
                  </small>
                </span>
                <strong className="whitespace-nowrap text-strong tabular-nums">{money(item.total)}</strong>
              </li>
            ))}
          </ul>
        </Box>

        <div className="flex flex-col gap-2.5 rounded-[10px] border border-line-subtle bg-card px-3.5 py-2.5">
          <dl className="flex flex-col gap-1 text-[13.5px]">
            <BillRow label="Subtotal dos itens" value={money(sale.subtotal)} />
            {Number(sale.discount) > 0 && <BillRow label="Desconto" value={`− ${money(sale.discount)}`} negative />}
            {sale.coupon_code && <BillRow label={`Cupom ${sale.coupon_code}`} value={`− ${money(sale.coupon_discount)}`} negative />}
            <BillRow label={delivery ? `Frete · ${delivery.table_name}` : pickup ? "Frete (retirada na loja)" : "Frete (a escolher)"}
              value={Number(sale.freight) ? `+ ${money(sale.freight)}` : money(0)} />
            {Number(sale.paid_amount) > 0 && <BillRow label="Já pago" value={`− ${money(sale.paid_amount)}`} />}
            <div className="mt-1 flex items-baseline justify-between border-t border-line-subtle pt-2">
              <dt className="text-[15px] font-bold text-strong">Total a pagar</dt>
              <dd className="text-[1.6rem] leading-none font-extrabold text-brand">{money(due)}</dd>
            </div>
          </dl>
          <div className="flex flex-wrap gap-1.5">
            <Button variant="secondary" size="sm" icon="pi pi-percentage" disabled={busy} onClick={props.onDiscount}>
              {Number(sale.discount) ? "Alterar desconto" : "Desconto"} <Kbd>F6</Kbd></Button>
            <Button variant="secondary" size="sm" icon="pi pi-ticket" disabled={busy} onClick={props.onCoupon}>
              {sale.coupon_code ? "Trocar cupom" : "Cupom"} <Kbd>F7</Kbd></Button>
          </div>
        </div>

        <Box title="Pagamentos desta venda" aside={lines.length ? "Vão juntos ao concluir" : ""}>
          {!lines.length ? (
            <p className="my-1 text-[13px] text-muted">Nenhum pagamento lançado. Escolha a forma ao lado e adicione.</p>
          ) : (
            <ul>
              {lines.map((line, index) => (
                <li key={`${line.method}-${index}`} className="flex items-center gap-2.5 border-t border-line-subtle py-1.5 first:border-t-0 animate-fade-up">
                  <i className={cx(ICONS[line.kind] ?? "pi pi-wallet", "text-brand")} />
                  <span className="flex-1 text-[13.5px] font-semibold text-strong">
                    {line.name}
                    <small className="font-medium text-muted">
                      {(line.installments ?? 1) > 1 && ` · ${line.installments}x`}
                      {line.nsu && ` · NSU ${line.nsu}`}
                      {line.tendered && Number(line.tendered) > Number(line.amount)
                        && ` · recebido ${money(line.tendered)} · troco ${money(Number(line.tendered) - Number(line.amount))}`}
                    </small>
                  </span>
                  <strong className="text-strong tabular-nums">{money(line.amount)}</strong>
                  <IconButton icon="pi pi-times" label="Remover pagamento" className="size-7 text-danger-text"
                    onClick={() => setLines(lines.filter((_, i) => i !== index))} />
                </li>
              ))}
            </ul>
          )}
        </Box>
      </section>

      <aside aria-label="Recebimento" className="flex min-h-0 w-[360px] shrink-0 flex-col gap-2.5 overflow-y-auto border-l border-line bg-card px-4 pt-3 pb-3.5 xl:w-[400px]">
        <div className="grid grid-cols-2 gap-1.5">
          <Tile label="Total" value={money(due)} />
          <Tile label="Recebido" value={money(paid)} />
          <div className={cx("col-span-2 flex flex-col gap-[3px] rounded-[10px] border px-3 py-2", changeTone)}>
            <span className="eyebrow">{change > 0 ? "Troco a entregar" : remaining > 0.001 ? "Falta receber" : "Pago"}</span>
            <strong className="text-[1.7rem] leading-tight font-extrabold tabular-nums">{money(change > 0 ? change : remaining)}</strong>
          </div>
        </div>

        <label className="flex flex-col gap-1">
          <span className="label">Forma de pagamento</span>
          <select value={method?.id ?? ""} disabled={remaining <= 0.001} className="input"
            onChange={(e) => pick(methods.find((m) => m.id === e.target.value) ?? null)}>
            <option value="" disabled>Escolha</option>
            {methods.map((m) => (
              <option key={m.id} value={m.id} disabled={blocked(m)}>
                {m.name}{blocked(m) ? ` — ${blockedReason(m)}` : ""}
              </option>
            ))}
          </select>
          {method?.kind === "store_credit" && (
            <small className="text-[12px] text-muted">
              Carteira do cliente: {money(creditBalance)} · disponível nesta venda: {money(creditAvailable)}
            </small>
          )}
        </label>

        {method && ((method.max_installments ?? 1) > 1 || method.requires_reference) && (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
            {(method.max_installments ?? 1) > 1 && (
              <label className="flex flex-col gap-1">
                <span className="label">Parcelas</span>
                <select className="input" value={installments} onChange={(e) => setInstallments(Number(e.target.value))}>
                  {Array.from({ length: method.max_installments ?? 1 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}x</option>)}
                </select>
              </label>
            )}
            {method.requires_reference && (
              <label className="flex flex-col gap-1">
                <span className="label">NSU / autorização {props.requireReference && <b className="text-danger-text">*</b>}</span>
                <Input ref={refInput} value={reference} onChange={(e) => setReference(e.target.value)}
                  placeholder={props.requireReference ? "Do comprovante" : "Opcional"} invalid={!!error && !reference}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())} />
              </label>
            )}
          </div>
        )}

        <label className="flex flex-col gap-1">
          <span className="label">{isCash ? "Valor recebido" : "Valor do pagamento"}</span>
          <div className="flex h-14 items-center gap-2 rounded-[10px] border border-line-strong bg-sunken px-3 focus-within:border-brand focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_18%,transparent)]">
            <span className="font-bold text-muted">R$</span>
            <input ref={amountInput} id="pdv-pay-amount" inputMode="numeric" autoComplete="off" disabled={remaining <= 0.001}
              value={amount.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
              onChange={(e) => {
                setTyped(true);
                setDigits(String(Number(e.target.value.replace(/\D/g, "").slice(-9) || "0")));
              }}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
              className="min-w-0 flex-1 bg-transparent text-right text-[1.8rem] font-black text-strong tabular-nums outline-0" />
          </div>
        </label>
        {pendingChange > 0.001 && (
          <div className="flex items-center justify-between rounded-[10px] bg-success-subtle px-3 py-2 font-extrabold text-success-text">
            <span>Troco</span><strong className="text-[1.25rem]">{money(pendingChange)}</strong>
          </div>
        )}
        {isCash && remaining > 0.001 && (
          <div className="grid grid-cols-4 gap-1.5">
            {quickCash.map((v) => (
              <button key={v} type="button" onClick={() => add(v)}
                className="h-[34px] rounded-lg border border-line bg-card text-[13px] font-bold text-strong hover:border-brand-border hover:bg-hover">
                {money(v)}
              </button>
            ))}
          </div>
        )}

        <div className="grid grid-cols-3 gap-1.5">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"].map((key) => (
            <button key={key} type="button" disabled={remaining <= 0.001} onClick={() => press(key)}
              aria-label={key === "back" ? "Apagar" : key === "clear" ? "Limpar" : key}
              className="h-12 rounded-lg border border-line bg-card text-[18px] font-extrabold text-strong hover:enabled:border-brand-border hover:enabled:bg-hover disabled:opacity-45">
              {key === "back" ? <i className="pi pi-delete-left" /> : key === "clear" ? "C" : key}
            </button>
          ))}
        </div>

        {error && <p role="alert" className="flex items-center gap-1.5 text-[13px] font-semibold text-danger-text"><i className="pi pi-exclamation-circle" /> {error}</p>}

        <Button variant="secondary" icon="pi pi-plus" disabled={remaining <= 0.001 || amount <= 0 || busy} onClick={() => add()}>
          {pendingChange > 0.001 ? "Receber e registrar troco" : "Adicionar pagamento"} <Kbd>Enter</Kbd>
        </Button>
        <Button size="lg" icon="pi pi-check-circle" loading={busy} disabled={busy || (remaining > 0.001 && amount <= 0)}
          onClick={finish} className="mt-auto h-[3.2rem]">
          Concluir venda <Kbd className="border-white/40 text-inherit">F10</Kbd>
        </Button>
      </aside>
    </>
  );
});

function WhoCard({ icon, label, kbd, todo, onClick, children }: {
  icon: string; label: string; kbd: string; todo?: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick}
      className={cx("flex min-h-14 items-center gap-2.5 rounded-[10px] border px-3 py-2.5 text-left",
        todo ? "border-dashed border-warning-text bg-warning-subtle" : "border-line-subtle bg-card hover:border-brand-border hover:bg-hover")}>
      <i className={cx(icon, "text-[16px]", todo ? "text-warning-text" : "text-brand")} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <small className="eyebrow">{label}</small>
        <strong className={cx("truncate text-[13.5px]", todo ? "text-warning-text" : "text-strong")}>{children}</strong>
      </span>
      <Kbd>{kbd}</Kbd>
    </button>
  );
}

function Box({ title, aside, children }: { title: string; aside?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-[10px] border border-line-subtle bg-card px-3.5 py-2.5">
      <div className="mb-1.5 flex items-baseline justify-between"><span className="eyebrow">{title}</span><small className="text-[12px] text-muted">{aside}</small></div>
      {children}
    </div>
  );
}

const BillRow = ({ label, value, negative }: { label: string; value: string; negative?: boolean }) => (
  <div className="flex justify-between">
    <dt className="text-muted">{label}</dt>
    <dd className={cx("font-semibold tabular-nums", negative ? "text-danger-text" : "text-strong")}>{value}</dd>
  </div>
);

const Tile = ({ label, value }: { label: string; value: string }) => (
  <div className="flex flex-col gap-[3px] rounded-[10px] border border-line-subtle bg-sunken px-3 py-2">
    <span className="eyebrow">{label}</span>
    <strong className="text-[1.15rem] leading-tight font-extrabold text-strong tabular-nums">{value}</strong>
  </div>
);

export default Checkout;
