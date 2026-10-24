/**
 * Catálogo do PDV: 20 produtos por vez, do servidor, e mais 20 quando a grade
 * rola até o fim. Busca (nome, SKU, código) e categoria vão para o servidor —
 * o PDV abre rápido mesmo com milhares de produtos.
 *
 * Um cartão = um PRODUTO (a camiseta, não "camiseta P", "camiseta M"...); as
 * variações (com fotos, saldo e serviços) só vêm quando o operador clica (`/pdv/products/{id}/`).
 * Categoria escolhida traz também as de dentro (Bebidas → Cervejas, Águas...).
 */
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";

import { resourceApi } from "@/api/resource";
import type { Variant } from "@/api/types";
import { useSession } from "@/stores/session";

export type CatalogProduct = {
  id: string;
  name: string;
  type: string;
  category: string | null;
  categoryName: string;
  variants: Variant[];
  variantCount: number;
  /** Menor preço (com promocional fixo) entre as variantes. */
  price: number;
  priceMax: number;
  promo: boolean;
  soldByWeight: boolean;
  unit: string;
  sku: string;
  stock: number | null;
  /** Capa do produto; sem foto, o cartão mostra as iniciais na cor do tema. */
  image: string | null;
};

type ProductRow = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
export type CatalogCategory = { id: string; name: string; parent: string | null };

const PAGE = 20;

function toCard(p: ProductRow): CatalogProduct {
  const variants = ((p.variants ?? []) as ProductRow[]).filter((v) => v.is_active !== false);
  const prices = variants.map((v) => Number(v.promotional_price || v.price));
  return {
    id: p.id, name: p.name, type: p.type, category: p.category ?? null, categoryName: p.category_name ?? "Sem categoria",
    variants: variants as Variant[], variantCount: variants.length,
    price: prices.length ? Math.min(...prices) : Number(p.price ?? 0), priceMax: prices.length ? Math.max(...prices) : Number(p.price_max ?? 0),
    promo: variants.some((v) => v.promotional_price && Number(v.promotional_price) < Number(v.price)),
    soldByWeight: p.sale_method === "weight", unit: p.unit ?? "UN",
    sku: variants.length > 1 ? `${variants.length} variações` : p.sku ?? "",
    stock: p.stock_quantity == null || !p.track_stock ? null : Number(p.stock_quantity), image: p.cover ?? null,
  };
}

export function usePdvCatalog() {
  const session = useSession();
  const search = ref("");
  const category = ref<string | null>(null);
  /** Busca só vai ao servidor 250 ms depois da última tecla. */
  const term = ref("");
  let timer: ReturnType<typeof setTimeout> | undefined;
  watch(search, (value) => {
    clearTimeout(timer);
    timer = setTimeout(() => (term.value = value.trim()), 250);
  });

  const query = useInfiniteQuery({
    queryKey: computed(() => ["pdv-catalog", session.activeStoreId, term.value, category.value]),
    queryFn: ({ pageParam }) => resourceApi.list<ProductRow>("/catalog/products/", {
      // Serviço (montagem, garantia) não é vendido sozinho pela grade: aparece na vitrine do produto.
      is_active: true, with_stock: 1, ordering: "name", page: pageParam, page_size: PAGE, type__in: "simple,variable,kit",
      search: term.value, category: category.value ?? undefined,
    }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const visible = computed(() => (query.data.value?.pages ?? []).flatMap((page) => page.results.map(toCard)));
  const total = computed(() => query.data.value?.pages[0]?.count ?? 0);
  const more = () => (query.hasNextPage.value && !query.isFetchingNextPage.value ? query.fetchNextPage() : undefined);

  /** Chips: as categorias do topo; escolhida uma, as de dentro dela aparecem numa 2ª linha. */
  const categoryQuery = useQuery({
    queryKey: ["pdv-categories"],
    queryFn: () => resourceApi.list<CatalogCategory>("/catalog/categories/", { is_active: true, page_size: 200, ordering: "name" }),
    staleTime: 5 * 60_000,
  });
  const all = computed(() => categoryQuery.data.value?.results ?? []);
  const roots = computed(() => all.value.filter((c) => !c.parent));
  const rootOf = (id: string | null): string | null => {
    let current = all.value.find((c) => c.id === id);
    while (current?.parent) current = all.value.find((c) => c.id === current!.parent);
    return current?.id ?? null;
  };
  const children = computed(() => {
    const root = rootOf(category.value);
    return root ? all.value.filter((c) => c.parent === root) : [];
  });
  const activeRoot = computed(() => rootOf(category.value));

  /** Variações de um produto (com preço vigente e saldo da loja), só quando o operador clica. */

  return { query, visible, total, more, search, category, roots, children, activeRoot,
           refresh: () => query.refetch() };
}
