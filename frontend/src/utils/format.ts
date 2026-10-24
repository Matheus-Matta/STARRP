/**
 * Formatação pt-BR. Dinheiro chega da API como TEXTO ("45.90") e assim é
 * enviado de volta: nunca passa por float na ida e volta.
 */
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });
const pct = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const dateFmt = new Intl.DateTimeFormat("pt-BR");
const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));

export function money(value: unknown) {
  const n = num(value);
  return n === null || Number.isNaN(n) ? "—" : brl.format(n);
}

export function quantity(value: unknown) {
  const n = num(value);
  return n === null || Number.isNaN(n) ? "—" : qty.format(n);
}

export function percent(value: unknown) {
  const n = num(value);
  return n === null || Number.isNaN(n) ? "—" : `${pct.format(n)}%`;
}

export function date(value: unknown) {
  if (!value) return "—";
  // Data pura ("2026-10-21") é local: `new Date` a leria como UTC e voltaria um dia.
  const text = String(value);
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(text) ? new Date(`${text}T00:00:00`) : new Date(text);
  return dateFmt.format(parsed);
}

export function dateTime(value: unknown) {
  return value ? dateTimeFmt.format(new Date(String(value))) : "—";
}

/** Número digitado → texto decimal com `places` casas para a API ("12.5" → "12.50"). */
export function toDecimal(value: number | string | null | undefined, places = 2) {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(String(value).replace(",", "."));
  return Number.isNaN(n) ? null : n.toFixed(places);
}

/** "1 venda", "3 vendas". */
export function plural(count: number, one: string, many: string) {
  return `${count.toLocaleString("pt-BR")} ${count === 1 ? one : many}`;
}
