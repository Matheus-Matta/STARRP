/**
 * Catálogo do PDV: produtos em páginas do tamanho da TELA (`fit`), mais uma página quando a
 * grade rola até o fim. Busca (nome, SKU, código) e categoria vão para o servidor.
 * Um cartão = um PRODUTO; as variações (fotos, saldo, serviços) só vêm no clique.
 * Sem servidor: a mesma grade, filtrada aqui no catálogo guardado (`/pdv/catalog-snapshot/`).
 */
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { mediaUrl } from "@/api/client";
import { catalogApi, type ProductRow } from "@/api/pdv";
import { net } from "@/state/net";
import { useStore } from "@/state/store";

import { searchSnapshot, type SnapProduct } from "./offline";

export type CatalogProduct = {
  id: string;
  name: string;
  type: string;
  categoryName: string;
  price: number;
  priceMax: number;
  promo: boolean;
  soldByWeight: boolean;
  unit: string;
  sku: string;
  stock: number | null;
  image: string | null;
};

const PAGE = 20;
const MAX_PAGE = 120;

function toCard(p: ProductRow): CatalogProduct {
  const variants = ((p.variants ?? []) as Record<string, unknown>[]).filter((v) => v.is_active !== false);
  const prices = variants.map((v) => Number(v.promotional_price || v.price));
  return {
    id: p.id, name: p.name, type: String(p.type ?? ""), categoryName: String(p.category_name ?? "Sem categoria"),
    price: prices.length ? Math.min(...prices) : Number(p.price ?? 0),
    priceMax: prices.length ? Math.max(...prices) : Number(p.price_max ?? 0),
    promo: variants.some((v) => v.promotional_price && Number(v.promotional_price) < Number(v.price)),
    soldByWeight: p.sale_method === "weight", unit: String(p.unit ?? "UN"),
    sku: variants.length > 1 ? `${variants.length} variações` : String(p.sku ?? ""),
    stock: p.stock_quantity == null || !p.track_stock ? null : Number(p.stock_quantity),
    image: mediaUrl(p.cover as string | null),
  };
}

function snapCard(p: SnapProduct): CatalogProduct {
  const prices = p.variants.map((v) => Number(v.current_price));
  const stocks = p.variants.map((v) => v.stock);
  return {
    id: p.id, name: p.name, type: p.type, categoryName: p.category_name ?? "Sem categoria",
    price: prices.length ? Math.min(...prices) : 0, priceMax: prices.length ? Math.max(...prices) : 0,
    promo: p.variants.some((v) => Number(v.current_price) < Number(v.price)), soldByWeight: p.sale_method === "weight",
    unit: p.unit, sku: p.variants.length > 1 ? `${p.variants.length} variações` : p.variants[0]?.sku ?? "",
    stock: stocks.every((s) => s === null) ? null : stocks.reduce((a, s) => a + Number(s ?? 0), 0),
    image: mediaUrl(p.images[0] ?? null),
  };
}

export function useCatalog(storeId: string | null, offline = false) {
  const { snapshotAt } = useStore(net);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [pageSize, setPageSize] = useState(PAGE);
  const [sized, setSized] = useState(false);

  // Busca só vai ao servidor 250 ms depois da última tecla.
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  /** Tamanho da página medido pela grade: uma tela e meia em linhas cheias. Só cresce. */
  const fit = useCallback((columns: number, rows: number) => {
    const cols = Math.max(1, columns);
    const wanted = Math.min(Math.ceil(Math.max(PAGE, cols * Math.ceil(rows * 1.5)) / cols) * cols, MAX_PAGE);
    setPageSize((prev) => (wanted > prev ? wanted : prev));
    setSized(true);
  }, []);

  const query = useInfiniteQuery({
    queryKey: ["pdv-catalog", storeId, term, category, pageSize],
    queryFn: ({ pageParam }) => catalogApi.products({
      // Serviço (montagem, garantia) não é vendido sozinho pela grade: aparece na vitrine do produto.
      is_active: true, with_stock: 1, ordering: "name", page: pageParam, page_size: pageSize, type__in: "simple,variable,kit",
      search: term, category: category ?? undefined,
    }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled: sized && !offline,
  });

  // Offline: o catálogo guardado, filtrado aqui; a "página" cresce como na grade online.
  const snapshot = useQuery({
    queryKey: ["pdv-snapshot", storeId, snapshotAt], queryFn: () => window.starrp.offline.snapshot(), enabled: offline, staleTime: Infinity,
  });
  const [localPages, setLocalPages] = useState(1);
  useEffect(() => setLocalPages(1), [term, category, offline]);

  const categories = useQuery({ queryKey: ["pdv-categories", storeId], queryFn: catalogApi.categories, staleTime: 5 * 60_000, enabled: !offline });
  const all = offline ? snapshot.data?.categories ?? [] : categories.data?.results ?? [];
  const descendants = useCallback((id: string): string[] => {
    const kids = all.filter((c) => c.parent === id).map((c) => c.id);
    return [...kids, ...kids.flatMap(descendants)];
  }, [all]);
  const localRows = useMemo(() => (offline ? searchSnapshot(snapshot.data ?? null, term, category, descendants) : []),
    [offline, snapshot.data, term, category, descendants]);

  const visible = useMemo(() => (offline
    ? localRows.slice(0, localPages * pageSize).map(snapCard)
    : (query.data?.pages ?? []).flatMap((page) => page.results.map(toCard))), [offline, localRows, localPages, pageSize, query.data]);
  const total = offline ? localRows.length : query.data?.pages[0]?.count ?? 0;
  const more = useCallback(() => {
    if (offline) {
      if (localPages * pageSize < localRows.length) setLocalPages((n) => n + 1);
    } else if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
  }, [query, offline, localPages, pageSize, localRows.length]);

  /** Chips: as categorias do topo; escolhida uma, as de dentro aparecem numa 2ª linha. */
  const roots = all.filter((c) => !c.parent);
  const rootOf = (id: string | null): string | null => {
    let current = all.find((c) => c.id === id);
    while (current?.parent) current = all.find((c) => c.id === current!.parent);
    return current?.id ?? null;
  };
  const activeRoot = rootOf(category);
  const children = activeRoot ? all.filter((c) => c.parent === activeRoot) : [];

  return {
    query, visible, total, more, fit, search, setSearch, category, setCategory, roots, children, activeRoot,
    loading: offline ? snapshot.isPending : query.isPending, offline,
    hasMore: offline ? localPages * pageSize < localRows.length : Boolean(query.hasNextPage),
    refresh: () => (offline ? snapshot.refetch() : query.refetch()),
  };
}

export type Catalog = ReturnType<typeof useCatalog>;
