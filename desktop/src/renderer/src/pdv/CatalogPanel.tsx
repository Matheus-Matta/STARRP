/**
 * Catálogo: busca (Tab), chips de categoria e a grade de produtos — uma página do tamanho da
 * tela por vez, carregando mais ao rolar. Clique no cartão abre a vitrine; Enter na busca lança
 * pelo código (leitor de código de barras, SKU, etiqueta de balança ou "3*código" para 3 unidades).
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";

import { initials, money, quantity } from "@/lib/format";
import { cx, Empty } from "@/ui";

import type { Catalog, CatalogProduct } from "./useCatalog";

const TYPE_ICON: Record<string, string> = { service: "pi pi-wrench", kit: "pi pi-gift", variable: "pi pi-clone" };
const CARD_MIN_W = 250;
const CARD_H = 98;
const GAP = 8;

export type CatalogHandle = { focus: () => void };

type Props = {
  catalog: Catalog; disabled: boolean; opening: string | null; offline?: boolean;
  onPick: (p: CatalogProduct) => void; onCode: (v: string) => void;
};

const CatalogPanel = forwardRef<CatalogHandle, Props>(function CatalogPanel({ catalog, disabled, opening, onPick, onCode }, ref) {
  const input = useRef<HTMLInputElement>(null);
  const grid = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => input.current?.focus() }), []);
  const { query, visible, total, search, setSearch, category, setCategory, fit, more } = catalog;

  function onEnter() {
    const value = search.trim();
    if (!value) return;
    // Busca que achou um produto só: Enter abre ele. Senão, tenta como código lido.
    if (visible.length === 1 && !/^\d{6,}$|\*|^PV1/.test(value)) onPick(visible[0]!);
    else onCode(value);
    setSearch("");
  }

  const measure = useCallback(() => {
    if (!grid.current) return;
    const { width, height } = grid.current.getBoundingClientRect();
    if (width <= 0) return;
    fit(Math.floor((width + GAP) / (CARD_MIN_W + GAP)), Math.ceil((Math.min(height, window.innerHeight) + GAP) / (CARD_H + GAP)));
  }, [fit]);

  /** Mais uma página sempre que o fim da grade está à vista (ou a menos de 300 px dele). */
  const fill = useCallback(() => {
    requestAnimationFrame(() => {
      if (!sentinel.current || !grid.current || !catalog.hasMore || query.isFetchingNextPage) return;
      const bottom = Math.min(grid.current.getBoundingClientRect().bottom, window.innerHeight);
      if (sentinel.current.getBoundingClientRect().top - bottom < 300) more();
    });
  }, [catalog.hasMore, query.isFetchingNextPage, more]);

  useEffect(() => {
    const observer = new ResizeObserver(() => {
      measure();
      fill();
    });
    if (grid.current) observer.observe(grid.current);
    measure();
    return () => observer.disconnect();
  }, [measure, fill]);
  useEffect(() => fill(), [visible.length, query.isFetching, fill]);

  const refreshing = query.isFetching && !query.isFetchingNextPage;

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-2.5 p-3">
      <div className="flex h-[46px] items-center gap-2.5 rounded-[10px] border border-line bg-card px-3 transition-shadow focus-within:border-brand focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_20%,transparent)]">
        <i className="pi pi-search text-muted" />
        <input id="pdv-scanner" ref={input} value={search} onChange={(e) => setSearch(e.target.value)} disabled={disabled}
          placeholder="Buscar produto, código ou categoria — ou leia o código de barras" autoComplete="off"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onEnter();
            }
          }}
          className="min-w-0 flex-1 bg-transparent text-[15px] font-medium text-strong outline-0 placeholder:text-subtle" />
        <kbd className="kbd">Tab</kbd>
        {catalog.offline && (
          <span title="Sem servidor: busca no catálogo guardado neste PC" className="inline-flex items-center gap-1 rounded-md bg-warning-subtle px-1.5 py-0.5 text-[11.5px] font-bold text-warning-text">
            <i className="pi pi-database text-[10px]" /> Offline
          </span>
        )}
        <span className="text-[12px] whitespace-nowrap text-muted">{visible.length} de {total} produtos</span>
      </div>

      <div role="tablist" className="flex gap-1.5 overflow-x-auto pb-0.5">
        <Chip active={category === null} onClick={() => setCategory(null)}>Todos</Chip>
        {catalog.roots.map((c) => <Chip key={c.id} active={catalog.activeRoot === c.id} onClick={() => setCategory(c.id)}>{c.name}</Chip>)}
      </div>
      {catalog.children.length > 0 && (
        <div className="-mt-1 flex gap-1.5 overflow-x-auto pb-0.5">
          <Chip sub active={category === catalog.activeRoot} onClick={() => setCategory(catalog.activeRoot)}>Tudo</Chip>
          {catalog.children.map((c) => <Chip key={c.id} sub active={category === c.id} onClick={() => setCategory(c.id)}>{c.name}</Chip>)}
        </div>
      )}

      <div ref={grid} className="min-h-0 flex-1 overflow-y-auto" onScroll={fill}>
        {catalog.loading ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(min(250px,100%),1fr))] gap-2">
            {Array.from({ length: 12 }, (_, n) => <div key={n} className="h-[96px] animate-pulse rounded-[10px] bg-card" />)}
          </div>
        ) : !catalog.offline && query.isError ? (
          <Empty icon="pi pi-exclamation-triangle" title="Catálogo não carregado">{query.error.message}</Empty>
        ) : !visible.length ? (
          <Empty icon="pi pi-search" title={search || category ? "Nada encontrado" : "Nenhum produto ativo"}>
            {search || category ? "Tente outro nome, código ou categoria." : "Cadastre produtos na retaguarda para vender aqui."}
          </Empty>
        ) : (
          <div className={cx("grid grid-cols-[repeat(auto-fill,minmax(min(250px,100%),1fr))] gap-2 transition-opacity", refreshing && "opacity-60")}>
            {visible.map((p) => (
              <button key={p.id} type="button" title={p.name} disabled={disabled} onClick={() => onPick(p)}
                className={cx("flex h-[98px] min-w-0 items-center gap-3 overflow-hidden rounded-[10px] border border-line bg-card p-2.5 text-left transition",
                  "hover:enabled:border-brand hover:enabled:shadow-sm active:enabled:scale-[0.985] disabled:opacity-50",
                  opening === p.id && "cursor-progress opacity-60")}>
                <span className={cx("relative grid size-[76px] shrink-0 place-items-center overflow-hidden rounded-[10px] border text-[20px] font-extrabold",
                  p.image ? "border-line-subtle bg-sunken" : "border-brand-border bg-brand-subtle text-brand-text")}>
                  {initials(p.name)}{p.image && <img src={p.image} alt="" loading="lazy" className="absolute inset-0 size-full object-cover" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
                  {TYPE_ICON[p.type] && <i className={cx(TYPE_ICON[p.type], "absolute right-1 bottom-1 rounded bg-card p-[3px] text-[10px] text-brand-text")} />}
                  {opening === p.id && <i className="pi pi-spin pi-spinner absolute text-brand" />}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-[3px] self-stretch">
                  <strong className="truncate text-[13.5px] leading-tight font-bold text-strong uppercase">{p.name}</strong>
                  <small className="truncate font-mono text-[11px] text-muted">{p.sku || "Sem SKU"}</small>
                  <small className="truncate text-[11.5px] text-muted">{p.categoryName}</small>
                  <span className="mt-auto flex items-baseline justify-between gap-1.5 whitespace-nowrap">
                    <span className={cx("text-[16px] font-extrabold", p.promo ? "text-accent" : "text-brand")}>
                      {p.price !== p.priceMax && <small className="text-[11px] font-semibold">a partir de </small>}
                      {money(p.price)}{p.soldByWeight && <small className="text-[11px] font-semibold"> / kg</small>}
                    </span>
                    {p.stock !== null && p.type !== "service" && (
                      <small className={cx("text-[11px]", p.stock <= 0 ? "font-semibold text-danger-text" : "text-muted")}>
                        {quantity(p.stock)} {p.unit.toLowerCase()}
                      </small>
                    )}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
        <div ref={sentinel} className="h-px" />
        {query.isFetchingNextPage ? (
          <p className="my-2.5 text-center text-[12.5px] text-muted"><i className="pi pi-spin pi-spinner" /> Carregando mais…</p>
        ) : catalog.hasMore && visible.length ? (
          <button type="button" onClick={more}
            className="mx-auto my-2.5 block rounded-lg border border-line bg-card px-4 py-2 text-[13px] font-semibold text-brand-text hover:border-brand">
            Carregar mais ({total - visible.length} restantes)
          </button>
        ) : null}
      </div>
    </section>
  );
});

function Chip({ active, sub, onClick, children }: { active: boolean; sub?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={cx("shrink-0 rounded-lg border font-semibold whitespace-nowrap transition-colors",
        sub ? "h-7 px-3 text-[12px]" : "h-8 px-3.5 text-[12.5px]",
        active ? (sub ? "border-brand-border bg-brand-subtle text-brand-text" : "border-brand bg-brand text-on-brand")
          : cx("border-line text-body hover:border-line-strong hover:text-strong", sub ? "bg-transparent" : "bg-card"))}>
      {children}
    </button>
  );
}

export default CatalogPanel;
