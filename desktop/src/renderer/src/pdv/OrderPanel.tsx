/**
 * Painel da venda (direita): cliente, entrega, vendedor, itens, totais e o caminho para o
 * pagamento. Quantidade muda nos botões − / + da linha; remover pede o motivo.
 */
import { saleLabel } from "./offline";
import { type Sale, type SaleItem, type Seller, deliveryOf } from "@/api/types";
import { money, quantity } from "@/lib/format";
import { Button, cx, Kbd, Select } from "@/ui";

type Props = {
  sale: Sale | null; items: SaleItem[]; sellers: Seller[]; busy: boolean; seller: boolean;
  onCustomer: () => void; onSeller: (id: number | null) => void; onQuantity: (item: SaleItem, value: string) => void;
  onRemove: (item: SaleItem) => void; onDiscount: () => void; onCoupon: () => void; onPay: () => void; onCancel: () => void;
  onPark: () => void; onSend: () => void; onDelivery: () => void;
  /** Sem servidor: a venda é local (OFF-n) ou a do servidor pode ser terminada offline. */
  offline?: boolean; localSale?: boolean; onContinueOffline?: () => void;
};

/** Item e logo abaixo os serviços dele (montagem, garantia), mesmo se lançados depois. */
export function orderedItems(items: SaleItem[]) {
  const ids = new Set(items.map((i) => i.id));
  return items.filter((i) => !i.parent_item || !ids.has(i.parent_item))
    .flatMap((i) => [i, ...items.filter((c) => c.parent_item === i.id)]);
}

export default function OrderPanel(p: Props) {
  const { sale, items, busy } = p;
  const { delivery, pickup } = deliveryOf(sale);
  const customerLabel = sale?.customer_name || (sale?.customer_document ? `CPF ${sale.customer_document}` : "");
  const step = (item: SaleItem, delta: number) => {
    const next = Number(item.quantity) + delta;
    if (next > 0) p.onQuantity(item, next.toFixed(3));
  };
  const isWeight = (item: SaleItem) => (item.unit ?? "UN") !== "UN";

  return (
    <aside className="flex min-h-0 w-[340px] shrink-0 flex-col border-l border-line bg-card xl:w-[380px]">
      <header className="flex items-start justify-between border-b border-line-subtle px-4 pt-3.5 pb-2.5">
        <div>
          <h2 className="text-[17px] font-extrabold text-strong">
            {sale ? `${p.seller ? "Pedido" : "Venda"} ${saleLabel(sale)}` : p.seller ? "Novo pedido" : "Nova venda"}
          </h2>
          <small className="text-[12px] text-muted">
            Balcão · {items.length} {items.length === 1 ? "item" : "itens"}
            {sale && p.localSale && !p.offline && " · neste PC, recebe o número do servidor ao concluir"}
          </small>
        </div>
        {sale && (
          <button type="button" disabled={busy} onClick={p.onCancel}
            className="flex items-center gap-1.5 p-1 text-[12.5px] font-semibold text-danger-text hover:underline">
            <i className="pi pi-times-circle" /> Cancelar
          </button>
        )}
      </header>

      {p.localSale && p.offline && (
        <p className="mx-4 mt-2.5 flex items-start gap-2 rounded-lg bg-warning-subtle px-3 py-2 text-[12.5px] text-warning-text">
          <i className="pi pi-cloud-upload mt-0.5" />
          <span><b>Sem servidor</b>: a venda segue neste PC com o catálogo guardado. Cupom, entrega e crediário esperam a conexão; o resto funciona. Vai para o servidor quando ele voltar.</span>
        </p>
      )}
      {p.offline && sale && !p.localSale && (
        <div className="mx-4 mt-2.5 flex flex-col gap-1.5 rounded-lg bg-danger-subtle px-3 py-2 text-[12.5px] text-danger-text">
          <span><i className="pi pi-exclamation-triangle" /> O servidor não responde. Esta venda está nele.</span>
          <Button size="sm" variant="secondary" icon="pi pi-cloud-upload" disabled={busy} onClick={p.onContinueOffline}>Continuar offline</Button>
        </div>
      )}
      <button type="button" onClick={p.onCustomer}
        className={cx("mx-4 mt-2.5 flex h-[38px] items-center gap-2 rounded-lg border px-3 text-[13px] font-semibold",
          customerLabel ? "border-line-strong bg-sunken text-strong" : "border-dashed border-line-strong text-body hover:border-brand hover:text-strong")}>
        <i className={customerLabel ? "pi pi-user" : "pi pi-user-plus"} />
        <span className="flex-1 truncate text-left">{customerLabel || "Vincular cliente (opcional)"}</span>
        <Kbd>F3</Kbd>
      </button>
      <button type="button" disabled={!sale} onClick={p.onDelivery}
        className={cx("mx-4 mt-2 flex h-[38px] items-center gap-2 rounded-lg border px-3 text-[13px] font-semibold disabled:opacity-50",
          delivery || pickup ? "border-line-strong bg-sunken text-strong" : "border-dashed border-line-strong text-body hover:enabled:border-brand")}>
        <i className={delivery ? "pi pi-truck" : pickup ? "pi pi-shop" : "pi pi-map-marker"} />
        <span className="flex-1 truncate text-left">
          {delivery ? `${delivery.table_name} · ${delivery.address_label} · ${delivery.lead_days ? `${delivery.lead_days} dia(s)` : "hoje"}`
            : pickup ? "Retirada na loja" : "Entrega ou retirada?"}
        </span>
        <Kbd>Shift+F11</Kbd>
      </button>
      {p.sellers.length > 0 && (
        <div className="mx-4 mt-2">
          <Select value={sale?.seller ?? null} disabled={busy} placeholder="Vendedor (opcional)" className="h-9 text-[13px]"
            options={p.sellers.map((s) => ({ value: s.user_id, label: s.name }))} onChange={(id) => p.onSeller(id)} />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2.5">
        {!items.length ? (
          <div className="flex h-full flex-col items-center justify-center gap-1.5 text-center text-muted">
            <span className="grid size-13 place-items-center rounded-xl bg-sunken text-xl"><i className="pi pi-shopping-bag" /></span>
            <strong className="text-[14px] text-strong">A venda está vazia</strong>
            <small className="text-[12.5px]">Clique num produto ou leia o código de barras.</small>
          </div>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {orderedItems(items).map((item) => (
              <li key={item.id} className={cx("rounded-lg border border-line-subtle bg-card px-2.5 py-2 hover:border-line-strong animate-fade-up",
                item.parent_item && "ml-[18px] border-l-2 border-l-brand-border")}>
                <div className="flex justify-between gap-2">
                  <strong className={cx("text-[13px] leading-snug text-strong", item.parent_item && "font-semibold")}>
                    {item.parent_item && <i className="pi pi-wrench mr-1 text-[12px] text-brand" />}{item.description}
                  </strong>
                  <span className="font-extrabold whitespace-nowrap text-strong">{money(item.total)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  {item.parent_item ? (
                    <span className="text-[13px] font-bold text-strong">Serviço · {quantity(item.quantity)}×</span>
                  ) : isWeight(item) ? (
                    <span className="text-[13px] font-bold text-strong">{quantity(item.quantity)} {(item.unit ?? "").toLowerCase()}</span>
                  ) : (
                    <span className="inline-flex items-center overflow-hidden rounded-md border border-line">
                      <button type="button" aria-label="Menos um" disabled={busy || Number(item.quantity) <= 1} onClick={() => step(item, -1)}
                        className="grid h-6 w-[26px] place-items-center bg-sunken text-body hover:enabled:bg-hover disabled:opacity-40">
                        <i className="pi pi-minus text-[10px]" />
                      </button>
                      <span className="min-w-[34px] text-center text-[13px] font-bold text-strong">{quantity(item.quantity)}</span>
                      <button type="button" aria-label="Mais um" disabled={busy} onClick={() => step(item, 1)}
                        className="grid h-6 w-[26px] place-items-center bg-sunken text-body hover:enabled:bg-hover disabled:opacity-40">
                        <i className="pi pi-plus text-[10px]" />
                      </button>
                    </span>
                  )}
                  <small className="flex-1 text-[12px] text-muted">
                    × {money(item.unit_price)}{item.promotion && <> · <span className="font-semibold text-accent">promoção</span></>}
                  </small>
                  <button type="button" aria-label="Remover item" disabled={busy} onClick={() => p.onRemove(item)}
                    className="rounded p-1 text-subtle hover:enabled:bg-danger-subtle hover:enabled:text-danger-text">
                    <i className="pi pi-trash" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <footer className="flex flex-col gap-2.5 border-t border-line px-4 pt-3 pb-3.5">
        <dl className="flex flex-col gap-1 text-[13px]">
          <Row label="Subtotal" value={money(sale?.subtotal ?? 0)} />
          {Number(sale?.discount) > 0 && <Row label="Desconto" value={`− ${money(sale?.discount)}`} negative />}
          {sale?.coupon_code && <Row label={`Cupom ${sale.coupon_code}`} value={`− ${money(sale.coupon_discount)}`} negative />}
          {Number(sale?.freight) > 0 && <Row label="Frete" value={`+ ${money(sale?.freight)}`} />}
        </dl>
        <div className="flex items-baseline justify-between">
          <span className="text-[15px] font-bold text-strong">Total</span>
          <strong className="text-[2rem] leading-none font-extrabold tracking-tight text-brand">{money(sale?.total ?? 0)}</strong>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <Button variant="secondary" size="sm" icon="pi pi-percentage" disabled={!sale || busy} onClick={p.onDiscount}>Desconto <Kbd>F6</Kbd></Button>
          <Button variant="secondary" size="sm" icon="pi pi-ticket" disabled={!sale || busy} onClick={p.onCoupon}>Cupom <Kbd>F7</Kbd></Button>
        </div>
        <Button variant="secondary" icon="pi pi-bookmark" disabled={!items.length || busy} onClick={p.onPark}>Guardar pedido <Kbd>F9</Kbd></Button>
        {p.seller ? (
          <Button size="lg" icon="pi pi-send" disabled={!items.length || busy} onClick={p.onSend} className="h-[3.2rem]">
            Enviar ao caixa <Kbd className="border-white/40 text-inherit">F10</Kbd>
          </Button>
        ) : (
          <Button size="lg" icon="pi pi-credit-card" disabled={!sale || !Number(sale.total) || busy} onClick={p.onPay} className="h-[3.2rem]">
            Ir para pagamento <Kbd className="border-white/40 text-inherit">F10</Kbd>
          </Button>
        )}
      </footer>
    </aside>
  );
}

function Row({ label, value, negative }: { label: string; value: string; negative?: boolean }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted">{label}</dt>
      <dd className={cx("font-semibold", negative ? "text-danger-text" : "text-strong")}>{value}</dd>
    </div>
  );
}
