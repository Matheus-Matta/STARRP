/**
 * Os gráficos do relatório impresso (`frontend/src/components/report/*.vue`) desenhados em SVG para a folha:
 * linha (2px, área leve na 1ª série), colunas (agrupadas ou empilhadas, ponta arredondada), cascata (soma azul,
 * desconta vermelho, subtotal cinza) e mapa de calor. Mesma escala "redonda", mesmos eixos e cores da paleta
 * clara (a folha é sempre papel branco).
 */
import { date, money, percent, quantity } from "@front/utils/format";

import { esc } from "./shell";

export type Format = "money" | "number" | "decimal" | "quantity" | "percent" | "date" | "text";

const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const SEQ_LOW = [0xcd, 0xe2, 0xfb];
const SEQ_HIGH = [0x10, 0x42, 0x81];
const GRID = "#e5e7eb";
const INK = "#4b5563";
const DIVERGE = { pos: "#2a78d6", neg: "#e34948", mid: "#9aa0aa" };
const color = (i: number) => SERIES[Math.min(i, 7)]!;

const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
/** "12,5 mil" / "1,2 mi" sem depender de `notation: "compact"` (o Hermes de alguns Androids não tem: quebraria o app ao abrir). */
const compactBrl = {
  format(value: number) {
    const abs = Math.abs(value);
    const [div, unit] = abs >= 1e9 ? [1e9, " bi"] : abs >= 1e6 ? [1e6, " mi"] : abs >= 1e3 ? [1e3, " mil"] : [1, ""];
    return `${oneDecimal.format(value / div)}${unit}`;
  },
};

/** `fmt` de chart.ts. */
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

function axisFmt(value: number, format: Format = "number") {
  const short = Math.abs(value) >= 1000 ? compactBrl.format(value) : integer.format(value);
  return format === "money" ? `R$ ${short}` : format === "percent" ? `${short}%` : short;
}

function niceScale(max: number, ticks = 4) {
  if (max <= 0) return { max: 1, ticks: [0, 1] };
  const raw = max / ticks;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const top = step * Math.ceil(max / step);
  return { max: top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) };
}

const MONTH_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
function xLabel(value: unknown, grain?: string) {
  const text = String(value ?? "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const d = new Date(`${text}T00:00:00`);
  if (grain === "month") return `${MONTH_SHORT[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function barPath(x: number, y: number, w: number, h: number, r = 4) {
  if (h <= 0 || w <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

const legend = (items: { name: string; color: string; line?: boolean }[]) => (items.length < 2 ? "" : `<ul class="legend">${
  items.map((s) => `<li><span class="${s.line ? "legend__line" : "legend__box"}" style="background:${s.color}"></span>${esc(s.name)}</li>`).join("")}</ul>`);

const W = 680;
type Series = { name: string; values: (string | number | null)[] };

export function lineChart(x: string[], series: Series[], format: Format, zero = true, grain?: string) {
  const H = 240;
  const M = { top: 12, right: 16, bottom: 28, left: 64 };
  const values = series.map((s) => s.values.map(Number));
  const all = values.flat();
  let minVal = 0;
  if (!zero) {
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const floor = lo - (hi - lo) * 0.15;
    minVal = floor > 0 ? niceScale(floor).ticks.filter((t) => t <= floor).at(-1) ?? 0 : Math.min(0, floor);
  } else minVal = Math.min(0, ...all);
  const scale = niceScale(Math.max(...all, 0) - minVal);
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  const xAt = (i: number) => M.left + (x.length <= 1 ? innerW / 2 : (i / (x.length - 1)) * innerW);
  const yAt = (v: number) => M.top + innerH - ((v - minVal) / scale.max) * innerH;
  const paths = values.map((vals) => vals.map((v, i) => `${i ? "L" : "M"}${xAt(i)},${yAt(v)}`).join(" "));
  const baseY = yAt(Math.max(0, minVal));
  const first = values[0] ?? [];
  const area = first.length ? `${paths[0]} L${xAt(first.length - 1)},${baseY} L${xAt(0)},${baseY} Z` : "";
  const every = Math.max(1, Math.ceil(x.length / Math.max(2, Math.floor(innerW / 70))));
  const svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">
    ${scale.ticks.map((t) => `<line x1="${M.left}" x2="${W - M.right}" y1="${yAt(t + minVal)}" y2="${yAt(t + minVal)}" stroke="${GRID}"/>
      <text x="${M.left - 8}" y="${yAt(t + minVal) + 4}" text-anchor="end" class="tick">${esc(axisFmt(t + minVal, format))}</text>`).join("")}
    ${x.map((label, i) => (i % every === 0 ? `<text x="${xAt(i)}" y="${H - 8}" text-anchor="middle" class="tick">${esc(xLabel(label, grain))}</text>` : "")).join("")}
    ${area ? `<path d="${area}" fill="${color(0)}" opacity="0.08"/>` : ""}
    ${paths.map((d, i) => `<path d="${d}" fill="none" stroke="${color(i)}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`).join("")}
  </svg>`;
  return `<div class="chart">${legend(series.map((s, i) => ({ name: s.name, color: color(i), line: true })))}${svg}</div>`;
}

export function barsChart(x: string[], series: Series[], format: Format, stacked = false, grain?: string) {
  const H = 240;
  const M = { top: 12, right: 12, bottom: 28, left: 64 };
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  const num = series.map((s) => s.values.map((v) => Math.max(0, Number(v))));
  const totals = x.map((_, i) => num.reduce((sum, vals) => sum + (vals[i] ?? 0), 0));
  const scale = niceScale(stacked ? Math.max(0, ...totals) : Math.max(0, ...num.flat()));
  const band = innerW / Math.max(1, x.length);
  const count = stacked ? 1 : series.length;
  const barW = Math.max(2, Math.min(24, (band * 0.72 - 2 * (count - 1)) / count));
  const groupW = barW * count + 2 * (count - 1);
  const y = (v: number) => M.top + innerH - (v / scale.max) * innerH;
  const every = Math.max(1, Math.ceil(x.length / Math.max(2, Math.floor(innerW / 56))));
  const bars: string[] = [];
  x.forEach((_, i) => {
    const left = M.left + band * i + (band - groupW) / 2;
    let base = 0;
    num.forEach((vals, s) => {
      const v = vals[i] ?? 0;
      if (!v) return;
      if (stacked) {
        const top = y(base + v);
        const bottom = y(base) - (base > 0 ? 2 : 0);
        const isTop = num.slice(s + 1).every((rest) => !(rest[i] ?? 0));
        const d = isTop ? barPath(left, top, barW, bottom - top) : bottom > top ? `M${left},${bottom} V${top} H${left + barW} V${bottom} Z` : "";
        if (d) bars.push(`<path d="${d}" fill="${color(s)}"/>`);
        base += v;
      } else {
        const x0 = left + s * (barW + 2);
        const d = barPath(x0, y(v), barW, y(0) - y(v));
        if (d) bars.push(`<path d="${d}" fill="${color(s)}"/>`);
      }
    });
  });
  const svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">
    ${scale.ticks.map((t) => `<line x1="${M.left}" x2="${W - M.right}" y1="${y(t)}" y2="${y(t)}" stroke="${GRID}"/>
      <text x="${M.left - 8}" y="${y(t) + 4}" text-anchor="end" class="tick">${esc(axisFmt(t, format))}</text>`).join("")}
    ${x.map((label, i) => (i % every === 0 ? `<text x="${M.left + band * i + band / 2}" y="${H - 8}" text-anchor="middle" class="tick">${esc(xLabel(label, grain))}</text>` : "")).join("")}
    ${bars.join("")}
  </svg>`;
  return `<div class="chart">${legend(series.map((s, i) => ({ name: s.name, color: color(i) })))}${svg}</div>`;
}

export function waterfallChart(steps: { label: string; value: string | number; kind: "add" | "sub" | "total" }[], format: Format) {
  const H = 280;
  const M = { top: 22, right: 12, bottom: 44, left: 70 };
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  let running = 0;
  const bars = steps.map((s) => {
    const v = Number(s.value);
    if (s.kind === "total") {
      running = v;
      return { ...s, from: 0, to: v };
    }
    const from = running;
    running += v;
    return { ...s, from, to: running };
  });
  const lo = Math.min(0, ...bars.flatMap((b) => [b.from, b.to]));
  const hi = Math.max(0, ...bars.flatMap((b) => [b.from, b.to]));
  const scale = niceScale(hi - lo);
  const y = (v: number) => M.top + innerH - ((v - lo) / scale.max) * innerH;
  const band = innerW / Math.max(1, steps.length);
  const barW = Math.min(36, band * 0.62);
  const fill = (b: (typeof bars)[number]) => (b.kind === "total" ? DIVERGE.mid : Number(b.value) >= 0 ? DIVERGE.pos : DIVERGE.neg);
  const twoLines = (label: string) => {
    const [first, ...rest] = label.split(" ");
    return rest.length ? [first!, rest.join(" ")] : [first!];
  };
  const svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">
    ${scale.ticks.map((t) => `<line x1="${M.left}" x2="${W - M.right}" y1="${y(t + lo)}" y2="${y(t + lo)}" stroke="${GRID}"/>
      <text x="${M.left - 8}" y="${y(t + lo) + 4}" text-anchor="end" class="tick">${esc(axisFmt(t + lo, format))}</text>`).join("")}
    <line x1="${M.left}" x2="${W - M.right}" y1="${y(0)}" y2="${y(0)}" stroke="#9ca3af"/>
    ${bars.map((b, i) => {
      const cx = M.left + band * i + band / 2;
      const link = i > 0 ? `<line x1="${M.left + band * (i - 1) + (band + barW) / 2}" x2="${M.left + band * i + (band - barW) / 2}" y1="${y(bars[i - 1]!.to)}" y2="${y(bars[i - 1]!.to)}" stroke="#9ca3af" stroke-dasharray="3 3"/>` : "";
      const top = Math.min(y(b.from), y(b.to));
      return `${link}<rect x="${M.left + band * i + (band - barW) / 2}" y="${top}" width="${barW}" height="${Math.max(1.5, Math.abs(y(b.from) - y(b.to)))}" rx="3" fill="${fill(b)}"/>
        ${b.kind === "total" ? `<text x="${cx}" y="${top - 6}" text-anchor="middle" class="value">${esc(axisFmt(Number(b.value), format))}</text>` : ""}
        <text x="${cx}" y="${H - 26}" text-anchor="middle" class="tick">${twoLines(b.label).map((line, w) => `<tspan x="${cx}" dy="${w ? 12 : 0}">${esc(line)}</tspan>`).join("")}</text>`;
    }).join("")}
  </svg>`;
  return `<div class="chart"><ul class="legend"><li><span class="legend__box" style="background:${DIVERGE.pos}"></span>Soma</li>
    <li><span class="legend__box" style="background:${DIVERGE.neg}"></span>Desconta</li>
    <li><span class="legend__box" style="background:${DIVERGE.mid}"></span>Subtotal</li></ul>${svg}</div>`;
}

export function heatmapChart(rows: string[], cols: string[], values: (string | number)[][], format: Format) {
  const max = Math.max(1, ...values.flat().map(Number));
  const fill = (v: unknown) => {
    const n = Number(v);
    if (!n) return "#f3f4f6";
    const t = (12 + (n / max) * 88) / 100;
    return `rgb(${SEQ_LOW.map((lo, i) => Math.round(lo + (SEQ_HIGH[i]! - lo) * t)).join(",")})`;
  };
  return `<div class="heat"><table class="heat__grid"><thead><tr><th></th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r, y) => `<tr><th>${esc(r)}</th>${cols.map((_c, x) =>
      `<td style="background:${fill(values[y]?.[x])}" title="${esc(fmt(values[y]?.[x] ?? 0, format))}"></td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

/** CSS dos gráficos no papel (legendas, eixos, mapa de calor, comparativo, conclusões). */
export const CHART_CSS = `
.chart { width: 100%; }
.chart svg { display: block; overflow: visible; }
.tick { fill: ${INK}; font-size: 11px; font-family: Arial, sans-serif; }
.value { fill: #111; font-size: 11px; font-weight: 700; font-family: Arial, sans-serif; }
.legend { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-wrap: wrap; gap: 14px; font-size: 9pt; color: #222; }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend__box { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.legend__line { width: 14px; height: 2px; border-radius: 1px; display: inline-block; }
.heat__grid { border-collapse: separate; border-spacing: 3px; width: 100%; }
.heat__grid th { font-size: 7.5pt; font-weight: 400; color: ${INK}; }
.heat__grid tbody th { text-align: left; white-space: nowrap; }
.heat__grid td { height: 18px; border-radius: 3px; }
`;
