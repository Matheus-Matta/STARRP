// Gera o tema do app a partir de `frontend/src/styles/tokens.css` — tema CLARO e ESCURO, marca azul:
//  - src/styles/theme.css → `@theme` do Tailwind (bg-card, text-strong, border-border, rounded-lg, shadow-xs...) com os
//    valores claros, e `@layer theme` com as variáveis de cada tema (`@variant light` / `@variant dark`, Uniwind);
//  - src/lib/tokens.ts   → os mesmos valores em JS, por tema (cor de ícone, spinner, placeholder: o que não aceita className).
// Rode `npm run front:styles` sempre que tokens.css mudar. Nada aqui é escrito à mão.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(root, "../frontend/src/styles/tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Declarações dos blocos cujo seletor passa no filtro (as outras marcas ficam de fora). */
function declarations(accept) {
  const vars = {};
  for (const [, selector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!accept(selector.trim())) continue;
    for (const [, name, value] of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) vars[name] = value.trim();
  }
  return vars;
}
const lightRaw = declarations((s) => s.startsWith(":root") && !s.includes("dark"));
const darkRaw = { ...lightRaw, ...declarations((s) => s.includes('[data-theme="dark"]')) };

function resolver(raw) {
  const resolve = (value, depth = 0) => {
    if (depth > 10) throw new Error(`referência circular: ${value}`);
    const out = value.replace(/var\(--([\w-]+)\)/g, (_, name) => {
      if (!(name in raw)) throw new Error(`token desconhecido: --${name}`);
      return resolve(raw[name], depth + 1);
    });
    // color-mix(in srgb, #2563eb 28%, transparent) → rgba.
    return out.replace(/color-mix\(in srgb,\s*(#[0-9a-f]{6})\s+(\d+)%,\s*transparent\)/gi, (_, hex, pct) => {
      const n = parseInt(hex.slice(1), 16);
      return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${Number(pct) / 100})`;
    });
  };
  return Object.fromEntries(Object.keys(raw).map((k) => [k, resolve(raw[k])]));
}
const light = resolver(lightRaw);
const dark = resolver(darkRaw);

/** Nome no Tailwind ← token do frontend. `text-*` vira cor de texto sem o prefixo (text-strong, text-muted...). */
const COLORS = {
  ground: "surface-ground", card: "surface-card", raised: "surface-raised", sunken: "surface-sunken",
  hover: "surface-hover", active: "surface-active", overlay: "surface-overlay",
  strong: "text-strong", body: "text-body", muted: "text-muted", subtle: "text-subtle", "brand-text": "text-brand",
  border: "border", "border-strong": "border-strong", "border-subtle": "border-subtle", ring: "ring",
  brand: "brand", "brand-hover": "brand-hover", "brand-strong": "brand-strong", "brand-subtle": "brand-subtle",
  "brand-subtle-2": "brand-subtle-2", "brand-border": "brand-border", "on-brand": "on-brand",
  success: "success", "success-text": "success-text", "success-subtle": "success-subtle",
  warning: "warning", "warning-text": "warning-text", "warning-subtle": "warning-subtle",
  danger: "danger", "danger-text": "danger-text", "danger-subtle": "danger-subtle",
  info: "info", "info-text": "info-text", "info-subtle": "info-subtle", accent: "accent",
  "nav-bg": "nav-bg", "nav-border": "nav-border", "nav-text": "nav-text", "nav-muted": "nav-muted", "nav-strong": "nav-strong",
  "nav-hover": "nav-hover", "nav-active": "nav-active", "nav-active-text": "nav-active-text",
  "chart-grid": "chart-grid", "chart-axis": "chart-axis", "seq-low": "seq-low", "seq-high": "seq-high",
  ...Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map((i) => [`series-${i}`, `series-${i}`])),
  ...Object.fromEntries([50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((s) => [`brand-${s}`, `brand-${s}`])),
};

/**
 * Cores do PrimeVue (tema `StarrpPreset` + Aura) que não são variáveis do tokens.css: superfície ardósia no claro,
 * zinco no escuro, cada uma no índice que o Aura usa em cada tema (campo, botão secundário, contorno, contraste).
 */
const PRIME = {
  "field-bg": ["slate-0", "zinc-950"], "field-border": ["slate-300", "zinc-700"], "field-disabled": ["slate-50", "zinc-900"],
  "secondary-bg": ["slate-100", "zinc-800"], "secondary-bg-active": ["slate-200", "zinc-700"],
  "secondary-fg": ["slate-600", "zinc-300"], "outline-border": ["slate-200", "zinc-700"],
  "outline-fg": ["slate-500", "zinc-400"], "outline-active": ["slate-100", "zinc-800"],
  "contrast-bg": ["slate-900", "zinc-50"], "contrast-active": ["slate-800", "zinc-200"], "contrast-fg": ["slate-0", "zinc-900"],
};
const ZINC0 = { "zinc-0": "#ffffff" };

const RADII = { sm: "radius-sm", md: "radius-md", lg: "radius-lg", xl: "radius-xl" };
const SHADOWS = { xs: "shadow-xs", sm: "shadow-sm", md: "shadow-md", lg: "shadow-lg", brand: "shadow-brand" };

function palette(values) {
  const out = {};
  for (const [name, token] of Object.entries(COLORS)) {
    if (!(token in values)) throw new Error(`token ausente em tokens.css: --${token}`);
    out[name] = values[token];
  }
  return out;
}
const lightColors = palette(light);
const darkColors = palette(dark);
for (const [name, [l, d]] of Object.entries(PRIME)) {
  lightColors[name] = light[l] ?? ZINC0[l];
  darkColors[name] = dark[d] ?? ZINC0[d];
  if (!lightColors[name] || !darkColors[name]) throw new Error(`escala ausente: ${l} / ${d}`);
}

const lines = [
  "/* GERADO por scripts/sync-front-styles.mjs a partir de frontend/src/styles/tokens.css — não edite. */",
  "@theme {",
  "  --color-*: initial;",
  "  --color-white: #ffffff;",
  "  --color-black: #000000;",
  "  --color-transparent: transparent;",
  ...Object.entries(lightColors).map(([k, x]) => `  --color-${k}: ${x};`),
  ...Object.entries(RADII).map(([k, token]) => `  --radius-${k}: ${light[token]};`),
  "  --radius-pill: 999px;",
  ...Object.entries(SHADOWS).map(([k, token]) => `  --shadow-${k}: ${light[token]};`),
  "}",
  "",
  "/* Cada tema troca as variáveis (Uniwind.setTheme('light' | 'dark' | 'system')). */",
  "@layer theme {",
  "  :root {",
  "    @variant light {",
  ...Object.entries(lightColors).map(([k, x]) => `      --color-${k}: ${x};`),
  ...Object.entries(SHADOWS).map(([k, token]) => `      --shadow-${k}: ${light[token]};`),
  "    }",
  "    @variant dark {",
  ...Object.entries(darkColors).map(([k, x]) => `      --color-${k}: ${x};`),
  ...Object.entries(SHADOWS).map(([k, token]) => `      --shadow-${k}: ${dark[token]};`),
  "    }",
  "  }",
  "}",
  "",
];
writeFileSync(join(root, "src/styles/theme.css"), lines.join("\n"));

const camel = (s) => s.replace(/-(\w)/g, (_, c) => c.toUpperCase());
const obj = (colors) => Object.entries(colors).map(([k, x]) => `  ${camel(k)}: ${JSON.stringify(x)},`);
const seriesOf = (colors) => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => JSON.stringify(colors[`series-${i}`])).join(", ");
const ts = [
  "/* GERADO por scripts/sync-front-styles.mjs a partir de frontend/src/styles/tokens.css — não edite. */",
  "/** Cores da retaguarda por tema, para o que não aceita className (ícones, spinner, placeholder). */",
  "export const lightTokens = {",
  ...obj(lightColors),
  "};",
  "",
  "export const darkTokens: typeof lightTokens = {",
  ...obj(darkColors),
  "};",
  "",
  `export const lightSeries = [${seriesOf(lightColors)}];`,
  `export const darkSeries = [${seriesOf(darkColors)}];`,
  "",
];
writeFileSync(join(root, "src/styles/palette.ts"), ts.join("\n"));
console.log(`tema gerado: ${Object.keys(lightColors).length} cores (claro e escuro), ${Object.keys(RADII).length + 1} raios, `
  + `${Object.keys(SHADOWS).length} sombras`);
