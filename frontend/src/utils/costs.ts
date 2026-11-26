/**
 * Custo e margem: só para quem tem `catalog.view_costs` (o caixa e o vendedor não veem).
 *
 * Quem barra é o backend (`core/costs.py`): sem a permissão os campos nem chegam. Aqui só se
 * tiram as COLUNAS e os ITENS de tela que mostrariam esses campos vazios ("R$ 0,00", "—").
 * As duas expressões são as mesmas do backend: chave em inglês ("unit_cost", "gross_margin") e
 * rótulo em português ("Custo total", "Margem bruta").
 */
import type { ColumnDef, DisplayDef, DisplaySection, DisplayStat, ResourceDef } from "@/resources/types";

export const COST_PERMISSION = "catalog.view_costs";
const COST_KEY = /(^|_)(cost|costs|margin|profit|markup|cmv|loss|losses|result)(_|$)/;
const COST_LABEL = /(^|[^\p{L}])(custos?|margem|margens|lucros?|cmv|markup|prejuízos?|resultado|perda de)($|[^\p{L}])/iu;

export const isCostKey = (key: unknown) => typeof key === "string" && COST_KEY.test(key);
export const isCostLabel = (label: unknown) => typeof label === "string" && COST_LABEL.test(label);

/** Coluna, item ou número de destaque de custo: pela chave ou pelo rótulo. */
export function isCostEntry(entry: { key?: string; label?: string; title?: unknown }) {
  return isCostKey(entry.key) || isCostLabel(entry.label) || isCostLabel(entry.title);
}

let seesCosts = true;

/** Chamado pela sessão ao carregar o usuário (evita import circular cadastros ⇄ sessão). */
export function setSeesCosts(value: boolean) {
  if (value !== seesCosts) cache.clear();
  seesCosts = value;
}

export function canSeeCosts() {
  return seesCosts;
}

/** Linhas sem as chaves de custo (exportação CSV, impressão). */
export function withoutCostKeys<T extends Record<string, unknown>>(row: T): T {
  return Object.fromEntries(Object.entries(row).filter(([key]) => !isCostKey(key))) as T;
}

const keepColumns = (columns: ColumnDef[]) => columns.filter((c) => !isCostEntry(c));

function section(s: DisplaySection): DisplaySection | null {
  if (isCostLabel(s.title)) return null;
  const table = s.table && {
    ...s.table,
    columns: typeof s.table.columns === "function"
      ? ((fn) => (v: Record<string, unknown>) => keepColumns(fn(v)))(s.table.columns)
      : keepColumns(s.table.columns),
  };
  const items = s.items?.filter((item) => !isCostEntry(item));
  const fields = s.fields?.filter((name) => !isCostKey(name));
  if (s.items?.length && !items?.length && !s.table && !fields?.length) return null;
  return { ...s, items, fields, table };
}

function display(d: DisplayDef): DisplayDef {
  const sections = (list?: DisplaySection[]) => list?.map(section).filter((s): s is DisplaySection => s !== null);
  return {
    ...d,
    stats: d.stats?.filter((stat: DisplayStat) => !isCostLabel(stat.label)),
    sections: sections(d.sections),
    aside: sections(d.aside),
  };
}

const cache = new Map<string, ResourceDef>();

/** O cadastro como a pessoa logada pode ver: sem colunas/itens de custo se não tem a permissão.
 *  Os CAMPOS do formulário ficam (a entrada de estoque precisa do custo da nota). */
export function visibleResource(resource: ResourceDef): ResourceDef {
  if (seesCosts) return resource;
  let shown = cache.get(resource.name);
  if (!shown) {
    shown = {
      ...resource,
      columns: keepColumns(resource.columns),
      filters: resource.filters?.filter((f) => !isCostKey(f.name)),
      display: resource.display && display(resource.display),
      views: resource.views?.map((v) => (v.list ? { ...v, list: { ...v.list, columns: keepColumns(v.list.columns) } } : v)),
    };
    cache.set(resource.name, shown);
  }
  return shown;
}
