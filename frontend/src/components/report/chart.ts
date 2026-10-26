/**
 * Utilitários dos gráficos de relatório: formatos, cor de série (ordem fixa) e escala "redonda".
 */
import { date, money, percent, quantity } from "@/utils/format";

export type Format = "money" | "number" | "decimal" | "quantity" | "percent" | "text" | "date";

const compactBrl = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
/** Médias (nota 4,3; 3,4 dias): sempre uma casa. */
const oneDecimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function fmt(value: unknown, format: Format = "number"): string {
  if (value === null || value === undefined || value === "") return "—";
  switch (format) {
    case "money": return money(value);
    case "quantity": return quantity(value);
    case "percent": return percent(value);
    case "date": return date(value);
    case "decimal": return oneDecimal.format(Number(value));
    case "text": return String(value);
    default: return integer.format(Number(value));
  }
}

/** Rótulo curto para eixo (R$ 12,5 mil · 1,2 mi). */
export function axisFmt(value: number, format: Format = "number"): string {
  const short = Math.abs(value) >= 1000 ? compactBrl.format(value) : integer.format(value);
  return format === "money" ? `R$ ${short}` : format === "percent" ? `${short}%` : short;
}

/** Cor da série pela POSIÇÃO fixa (1ª série = slot 1...). Nunca recicla: passou de 8, é "Outros". */
export const seriesColor = (index: number) => `var(--series-${Math.min(index, 7) + 1})`;

/** Teto "redondo" do eixo e as marcas (0, 25%, 50%...). */
export function niceScale(max: number, ticks = 4) {
  if (max <= 0) return { max: 1, ticks: [0, 1] };
  const raw = max / ticks;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const top = step * Math.ceil(max / step);
  return { max: top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) };
}

export type Grain = "day" | "week" | "month";
const MONTH_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MONTH_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
                    "novembro", "dezembro"];
const WEEKDAY = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const isoDate = (value: unknown) => {
  const text = String(value ?? "");
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? new Date(`${text}T00:00:00`) : null;
};
const dm = (d: Date) => `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;

/** Eixo X, curto para não cortar nem encavalar (pt-BR): dia e semana "27/07", mês "out/26".
 *  O que não é data (hora "9h", dia da semana, faixa de vencimento) passa como está. */
export function xLabel(value: unknown, grain?: Grain) {
  const d = isoDate(value);
  if (!d) return String(value);
  if (grain === "month") return `${MONTH_SHORT[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
  return dm(d);
}

/** Título do balão, por extenso: "sáb, 24/10/2026", "Semana de 19/10 a 25/10/2026", "outubro de 2026". */
export function tipTitle(value: unknown, grain?: Grain) {
  const d = isoDate(value);
  if (!d) return String(value);
  if (grain === "month") return `${MONTH_LONG[d.getMonth()]} de ${d.getFullYear()}`;
  if (grain === "week") {
    const end = new Date(d);
    end.setDate(end.getDate() + 6);
    return `Semana de ${dm(d)} a ${dm(end)}/${end.getFullYear()}`;
  }
  return `${WEEKDAY[d.getDay()]}, ${dm(d)}/${d.getFullYear()}`;
}

/** Retângulo com a ponta de dados arredondada (4px) e a base reta (nasce da linha de base). */
export function barPath(x: number, y: number, w: number, h: number, r = 4) {
  if (h <= 0 || w <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}
