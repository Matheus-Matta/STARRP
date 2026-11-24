/**
 * Vitrine do produto: galeria · nome, preço e saldo · um botão por valor de cada eixo da grade
 * (Cor, Tamanho) · quantidade (kg na balança) · serviços (montagem, garantia) · descrição e ficha.
 * Combinação que não existe fica apagada; sem saldo fica tracejada. Enter adiciona ao pedido.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { mediaUrl } from "@/api/client";
import type { PdvProductView } from "@/api/types";
import { initials, money, parseDecimal, quantity as qty } from "@/lib/format";
import { approvalPending } from "@/state/approval";
import { Button, cx, Dialog, Kbd, Segmented } from "@/ui";

type Variant = PdvProductView["variants"][number];
const inStock = (v: Variant) => v.stock === null || Number(v.stock) > 0;

export default function ProductDialog({ product, busy, onConfirm, onClose }: {
  product: PdvProductView | null; busy: boolean; onConfirm: (variant: string, quantity: string, services: string[]) => void;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<string | null>(null);
  const [amountText, setAmountText] = useState("1");
  const [services, setServices] = useState<string[]>([]);
  const [image, setImage] = useState(0);
  const [tab, setTab] = useState<"details" | "specs" | "services">("details");
  const qtyInput = useRef<HTMLInputElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);

  const p = product;
  const byWeight = p?.sale_method === "weight";
  const fractional = byWeight || (p?.unit ?? "UN") !== "UN";
  const hasAxes = Boolean(p?.axes.length);

  useEffect(() => {
    if (!product) return;
    const start = product.variants.find((v) => v.is_default && inStock(v)) ?? product.variants.find(inStock) ?? product.variants[0];
    setSelected(start ? { ...start.options } : {});
    setPicked(!product.axes.length && product.variants.length > 1 ? null : start?.id ?? null);
    setAmountText(product.sale_method === "weight" ? "" : "1");
    setServices([]);
    setImage(0);
    setTab("details");
    // O foco sai da busca do catálogo (atrás): senão o Enter/leitor iria para ela.
    setTimeout(() => (product.sale_method === "weight" ? qtyInput.current : addButton.current)?.focus());
  }, [product]);

  const variant = useMemo<Variant | null>(() => {
    if (!p) return null;
    if (!hasAxes) return p.variants.find((v) => v.id === picked) ?? null;
    return p.variants.find((v) => p.axes.every((a) => v.options[a.id] === selected[a.id])) ?? null;
  }, [p, hasAxes, picked, selected]);
  useEffect(() => setImage(0), [variant?.id]);

  /** Variantes que ainda casam se o valor `valueId` do eixo `axisId` for escolhido. */
  const candidates = (axisId: string, valueId: string) => (p?.variants ?? []).filter((v) => v.options[axisId] === valueId
    && (p?.axes ?? []).every((a) => a.id === axisId || !selected[a.id] || v.options[a.id] === selected[a.id]));
  const exists = (a: string, v: string) => candidates(a, v).length > 0;
  const available = (a: string, v: string) => candidates(a, v).some(inStock);

  function choose(axisId: string, valueId: string) {
    const next = { ...selected, [axisId]: valueId };
    const match = p?.variants.find((v) => p.axes.every((a) => v.options[a.id] === next[a.id]));
    if (match) return setSelected(next);
    // Combinação inexistente com o resto: ajusta os outros eixos para a 1ª que existe.
    const fallback = p?.variants.find((v) => v.options[axisId] === valueId && inStock(v)) ?? p?.variants.find((v) => v.options[axisId] === valueId);
    setSelected(fallback ? { ...fallback.options } : next);
  }

  const gallery = useMemo(() => {
    const own = variant?.images ?? [];
    return [...own, ...(p?.images ?? []).filter((url) => !own.includes(url))].map((u) => mediaUrl(u)!);
  }, [variant, p]);

  const amount = fractional ? parseDecimal(amountText) : Number(amountText) || null;
  const unitPrice = Number(variant?.current_price ?? 0);
  const servicesTotal = (p?.services ?? []).filter((s) => services.includes(s.variant)).reduce((sum, s) => sum + Number(s.price), 0);
  const total = (amount ?? 0) * (unitPrice + (byWeight ? 0 : servicesTotal)) + (byWeight ? servicesTotal : 0);
  const missing = !variant
    ? hasAxes ? `Escolha ${p!.axes.filter((a) => !selected[a.id]).map((a) => a.name.toLowerCase()).join(" e ") || "a combinação"}.` : "Escolha a variação."
    : !amount || amount <= 0 ? (byWeight ? "Informe o peso." : "Informe a quantidade.") : "";

  function confirm() {
    if (missing || busy || !variant || !amount) return;
    onConfirm(variant.id, amount.toFixed(3), services);
  }

  // Enter adiciona de qualquer lugar da vitrine (mesmo com o foco num botão de cor/serviço).
  useEffect(() => {
    if (!product) return;
    const onEnter = (event: KeyboardEvent) => {
      // Com a autorização do gerente aberta por cima, o Enter é do formulário dela.
      if (event.key !== "Enter" || event.isComposing || approvalPending.get()) return;
      event.preventDefault();
      event.stopPropagation();
      confirm();
    };
    window.addEventListener("keydown", onEnter, true);
    return () => window.removeEventListener("keydown", onEnter, true);
  });

  const specs = ([
    ...(p?.specs ?? []).map((s) => [s.label, s.text]),
    ["SKU", variant?.sku], ["Código de barras", variant?.barcode], ["Referência", p?.reference],
    ["Categoria", p?.category_name], ["Marca", p?.brand_name], ["Unidade", p?.unit],
    ["Variações", p && p.variants.length > 1 ? String(p.variants.length) : ""],
  ] as [string, string | null | undefined][]).filter(([, v]) => v) as [string, string][];

  return (
    <Dialog open={product !== null} onClose={onClose} width={1120} bare>
      {p && (
        <div className="relative flex flex-col gap-5 p-6">
          <button type="button" aria-label="Fechar (Esc)" onClick={onClose}
            className="absolute top-4 right-4 z-10 grid size-[34px] place-items-center rounded-full border border-line bg-card text-muted hover:text-strong">
            <i className="pi pi-times" />
          </button>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 gap-2.5">
              {gallery.length > 1 && (
                <div role="tablist" aria-label="Fotos" className="flex max-h-[460px] shrink-0 flex-col gap-2 overflow-y-auto">
                  {gallery.map((url, i) => (
                    <button key={url} type="button" role="tab" aria-selected={i === image} onClick={() => setImage(i)}
                      className={cx("size-[76px] overflow-hidden rounded-[10px] border-2 bg-sunken p-0", i === image ? "border-brand" : "border-transparent")}>
                      <img src={url} alt="" loading="lazy" className="size-full object-cover" />
                    </button>
                  ))}
                </div>
              )}
              <div className="grid aspect-square max-h-[460px] flex-1 place-items-center overflow-hidden rounded-[14px] bg-sunken">
                {gallery.length ? <img src={gallery[image]} alt={p.name} className="size-full object-contain" />
                  : <span className="grid size-full place-items-center bg-brand-subtle text-[64px] font-extrabold text-brand-text">{initials(p.name)}</span>}
              </div>
            </div>

            <div className="flex min-w-0 flex-col gap-3.5 pr-12">
              <small className="text-[12.5px] font-semibold text-muted">{[p.category_name, p.brand_name].filter(Boolean).join(" · ") || "Produto"}</small>
              <h2 className="-mt-2 text-[22px] leading-tight font-extrabold text-strong">{p.name}</h2>
              <div className="flex flex-wrap items-baseline gap-2.5">
                <strong className="text-[28px] leading-none font-extrabold text-strong">
                  {money(unitPrice)}{byWeight && <small className="text-[14px] text-muted"> / kg</small>}
                </strong>
                {variant && Number(variant.price) > unitPrice && <s className="text-[15px] text-muted">{money(variant.price)}</s>}
                {variant && variant.stock !== null && (
                  <span className={cx("ml-auto inline-flex items-center gap-1.5 text-[12.5px] font-semibold",
                    Number(variant.stock) > 0 ? "text-success-text" : "text-warning-text")}>
                    <i className={Number(variant.stock) > 0 ? "pi pi-check-circle" : "pi pi-exclamation-triangle"} />
                    {Number(variant.stock) > 0 ? `${qty(variant.stock)} em estoque` : "Sem estoque"}
                  </span>
                )}
              </div>
              {variant && <small className="-mt-2 font-mono text-[12px] text-muted">SKU {variant.sku}</small>}

              {p.axes.map((axis) => (
                <div key={axis.id} className="flex flex-col gap-2">
                  <span className="text-[13px] font-bold text-strong">
                    {axis.name}{selected[axis.id] && <b className="font-medium text-muted">: {axis.values.find((v) => v.id === selected[axis.id])?.value}</b>}
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {axis.values.map((value) => (
                      <OptionChip key={value.id} active={selected[axis.id] === value.id} out={!available(axis.id, value.id)}
                        faded={!exists(axis.id, value.id)} disabled={!p.variants.some((v) => v.options[axis.id] === value.id)}
                        onClick={() => choose(axis.id, value.id)}>{value.value}</OptionChip>
                    ))}
                  </div>
                </div>
              ))}
              {!hasAxes && p.variants.length > 1 && (
                <div className="flex flex-col gap-2">
                  <span className="text-[13px] font-bold text-strong">Variação</span>
                  <div className="flex flex-wrap gap-2">
                    {p.variants.map((v) => <OptionChip key={v.id} active={picked === v.id} out={!inStock(v)} onClick={() => setPicked(v.id)}>{v.name}</OptionChip>)}
                  </div>
                </div>
              )}

              <div className="flex flex-col gap-2">
                <span className="text-[13px] font-bold text-strong">
                  {byWeight ? "Peso (kg)" : fractional ? `Quantidade (${p.unit.toLowerCase()})` : "Quantidade"}
                </span>
                {fractional ? (
                  <input ref={qtyInput} inputMode="decimal" value={amountText} placeholder="0,000" className="input w-[180px]"
                    onChange={(e) => setAmountText(e.target.value.replace(/[^\d,.]/g, ""))} />
                ) : (
                  <span className="inline-flex w-max items-center overflow-hidden rounded-lg border border-line">
                    <button type="button" aria-label="Menos um" disabled={(amount ?? 1) <= 1}
                      onClick={() => setAmountText(String(Math.max(1, (amount ?? 1) - 1)))}
                      className="size-10 text-brand disabled:text-muted"><i className="pi pi-minus" /></button>
                    <input ref={qtyInput} inputMode="numeric" value={amountText} onChange={(e) => setAmountText(e.target.value.replace(/\D/g, ""))}
                      className="h-10 w-14 border-x border-line bg-card text-center font-bold text-strong outline-0" />
                    <button type="button" aria-label="Mais um" onClick={() => setAmountText(String((amount ?? 0) + 1))}
                      className="size-10 text-brand"><i className="pi pi-plus" /></button>
                  </span>
                )}
              </div>

              {p.services.length > 0 && (
                <div className="flex flex-col gap-2">
                  <span className="text-[13px] font-bold text-strong">Serviços</span>
                  <div className="flex flex-col gap-1.5">
                    {p.services.map((s) => {
                      const on = services.includes(s.variant);
                      return (
                        <button key={s.variant} type="button" role="checkbox" aria-checked={on}
                          onClick={() => setServices(on ? services.filter((x) => x !== s.variant) : [...services, s.variant])}
                          className={cx("flex items-center gap-2.5 rounded-[10px] border px-3 py-2.5 text-left",
                            on ? "border-brand bg-brand-subtle" : "border-line bg-card")}>
                          <i className={cx(on ? "pi pi-check-square text-brand" : "pi pi-stop text-muted", "text-[16px]")} />
                          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <strong className="text-[13.5px] text-strong">{s.name}</strong>
                            {s.description && <small className="truncate text-[12px] text-muted">{s.description}</small>}
                          </span>
                          <span className="text-[13.5px] font-bold whitespace-nowrap text-strong">+ {money(s.price)}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="mt-1 flex items-center gap-3.5">
                <div className="flex flex-col">
                  <span className="eyebrow">Total</span>
                  <strong className="text-[20px] leading-tight font-extrabold text-strong">{money(total)}</strong>
                </div>
                <Button ref={addButton} size="lg" icon="pi pi-shopping-cart" loading={busy} disabled={!!missing} onClick={confirm} className="flex-1">
                  Adicionar ao pedido <Kbd className="border-white/40 text-inherit">Enter</Kbd>
                </Button>
              </div>
              {missing && <small className="-mt-1.5 flex items-center gap-1.5 text-muted"><i className="pi pi-info-circle" /> {missing}</small>}
            </div>
          </div>

          <div className="flex flex-col gap-3 border-t border-line-subtle pt-4">
            <Segmented value={tab} onChange={setTab} className="self-start"
              options={[{ value: "details", label: "Detalhes" }, { value: "specs", label: "Ficha técnica" },
                ...(p.services.length ? [{ value: "services" as const, label: "Serviços" }] : [])]} />
            {tab === "details" && (p.description
              // HTML limpo no backend (nh3), igual à versão web.
              ? <div className="rich max-w-[820px] text-[14px] leading-relaxed text-body" dangerouslySetInnerHTML={{ __html: p.description }} />
              : <p className="text-muted">Sem descrição cadastrada.</p>)}
            {tab === "specs" && (
              <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-[13.5px]">
                {specs.map(([k, v]) => <div key={k} className="contents"><dt className="font-semibold text-muted">{k}</dt><dd className="text-strong">{v}</dd></div>)}
              </dl>
            )}
            {tab === "services" && (
              <ul className="flex list-disc flex-col gap-2 pl-5 text-body">
                {p.services.map((s) => (
                  <li key={s.variant}><strong>{s.name}</strong> — {money(s.price)}{s.description && <small className="block text-muted">{s.description}</small>}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

function OptionChip({ active, out, faded, disabled, onClick, children }: {
  active: boolean; out?: boolean; faded?: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" disabled={disabled} onClick={onClick}
      title={faded ? "Não existe com a escolha atual" : out ? "Sem estoque" : undefined}
      className={cx("min-w-12 rounded-lg border px-3.5 py-2 text-[13px] font-semibold transition-colors",
        "disabled:cursor-not-allowed disabled:line-through disabled:opacity-35",
        active ? "border-brand bg-brand-subtle text-brand-text shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_18%,transparent)]"
          : "border-line bg-card text-body hover:enabled:border-brand-border",
        out && !active && "border-dashed text-muted", faded && !active && "opacity-55")}>
      {children}
    </button>
  );
}
