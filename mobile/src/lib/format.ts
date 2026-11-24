/** Formatação pt-BR. A API manda decimais como texto ("12.500"). */

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });
const oneDecimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function toNumber(value: unknown): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : Number(String(value).replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

export const formatMoney = (value: unknown) => money.format(toNumber(value));
export const formatQty = (value: unknown) => decimal.format(toNumber(value));
export const formatInt = (value: unknown) => integer.format(toNumber(value));

/** Formatos do livro de relatórios: money | number | decimal | quantity | percent | text. */
export function formatValue(value: unknown, format = "number") {
  if (value === null || value === undefined) return "—";
  switch (format) {
    case "money":
      return formatMoney(value);
    case "number":
      return formatInt(value);
    case "decimal":
      return oneDecimal.format(toNumber(value));
    case "quantity":
      return formatQty(value);
    case "percent":
      return `${oneDecimal.format(toNumber(value))}%`;
    default:
      return String(value);
  }
}

/** Valor curto para eixos e barras: 12.500 → "12,5 mil". */
export function formatCompact(value: unknown, format = "number") {
  const n = toNumber(value);
  const abs = Math.abs(n);
  const prefix = format === "money" ? "R$ " : "";
  if (abs >= 1_000_000) return `${prefix}${oneDecimal.format(n / 1_000_000)} mi`;
  if (abs >= 10_000) return `${prefix}${oneDecimal.format(n / 1000)} mil`;
  return formatValue(n, format);
}

export function formatDate(value?: string | null) {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-");
  return d ? `${d}/${m}/${y}` : value;
}

export function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Data local AAAA-MM-DD (para filtros e `effective_date`). */
export function isoDate(date = new Date()) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function daysAgo(days: number) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return isoDate(date);
}

/** Texto digitado ("1,5") → decimal da API ("1.5"); vazio/ inválido → null. */
export function parseDecimalInput(text: string): string | null {
  // Com vírgula, ela é o decimal e os pontos são milhar ("1.250,5"); sem vírgula, o ponto é o decimal.
  const raw = text.trim();
  const clean = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw;
  if (!clean || clean === "-") return null;
  const n = Number(clean);
  return Number.isFinite(n) ? String(n) : null;
}
