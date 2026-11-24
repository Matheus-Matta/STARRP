/**
 * O que o app reaproveita da retaguarda, adaptado ao celular: ícones (PrimeIcons → Feather),
 * permissões no formato do frontend (`can(código?)`, `hasModule(módulo?)`) e o endereço de cada
 * tela da retaguarda dentro do app.
 */
import type { Href } from "expo-router";
import { useCallback } from "react";

import type { IconName } from "@/components/ui";
import { can as canCode, hasModule as hasMod } from "@/session/access";
import { useSession } from "@/session/SessionContext";

const ICONS: Record<string, IconName> = {
  "align-left": "align-left", "arrow-down-left": "arrow-down-left", "arrow-right-arrow-left": "repeat",
  "arrow-up-right": "arrow-up-right", bolt: "zap", book: "book", bookmark: "bookmark", box: "box", briefcase: "briefcase",
  building: "home", "building-columns": "briefcase", calculator: "hash", calendar: "calendar",
  "calendar-clock": "calendar", "chart-bar": "bar-chart-2", "chart-line": "trending-up", "chart-pie": "pie-chart",
  "chart-scatter": "activity", check: "check", "check-circle": "check-circle", "check-square": "check-square",
  clock: "clock", "cloud-download": "download-cloud", cog: "settings", comment: "message-square",
  "credit-card": "credit-card", desktop: "monitor", directions: "navigation", dollar: "dollar-sign",
  download: "download", "exclamation-triangle": "alert-triangle", eye: "eye", file: "file", "file-edit": "edit",
  filter: "filter", gauge: "activity", globe: "globe", heart: "heart", history: "clock", home: "home",
  "id-card": "credit-card", images: "image", inbox: "inbox", "info-circle": "info", key: "key", lightbulb: "sun",
  link: "link", list: "list", "list-check": "check-square", map: "map", "map-marker": "map-pin", pencil: "edit-2",
  percentage: "percent", phone: "phone", print: "printer", qrcode: "grid", receipt: "file-text", refresh: "refresh-cw",
  replay: "rotate-ccw", search: "search", "search-plus": "zoom-in", send: "send", shield: "shield",
  "shopping-cart": "shopping-cart", sitemap: "git-branch", "sliders-h": "sliders", "sort-alt": "bar-chart",
  "sort-amount-down": "trending-down", sparkles: "star", "stop-circle": "stop-circle", star: "star", sync: "refresh-cw",
  tag: "tag", tags: "tag", "th-large": "grid", "thumbs-up": "thumbs-up", ticket: "award", times: "x",
  "times-circle": "x-circle", truck: "truck", undo: "rotate-ccw", upload: "upload", user: "user", "user-edit": "user",
  users: "users", verified: "check-circle", wallet: "credit-card", warehouse: "archive", wrench: "tool",
};

/** "pi pi-box" → "box" (Feather). Ícone desconhecido vira um ponto neutro. */
export function iconOf(primeIcon?: string, fallback: IconName = "circle"): IconName {
  const name = primeIcon?.split(" ").find((c) => c.startsWith("pi-") && c !== "pi-spin")?.slice(3);
  return (name && ICONS[name]) || fallback;
}

/** Permissões no formato da retaguarda: código/módulo vazio = livre. */
export function useAccess() {
  const { me } = useSession();
  const can = useCallback((code?: string) => !code || canCode(me, code), [me]);
  const hasModule = useCallback((module?: string) => !module || hasMod(me, module), [me]);
  return { can, hasModule, me };
}

/** Telas da retaguarda que o celular não tem (abrem um aviso). */
const WEB_ONLY: Record<string, string> = {
  "/configuracoes": "Configurações da conta",
  "/integracoes": "Integrações",
};

/** Endereço da retaguarda (`/cadastros/produtos/12`, `/relatorios/vendas`...) → rota do app. */
export function hrefFor(to: string): Href {
  const [path, search = ""] = to.split("?");
  const params = Object.fromEntries(searchPairs(search));
  if (!path || path === "/") return "/";
  if (path === "/estoque") return "/estoque";
  if (path === "/financeiro") return "/financeiro";
  if (path === "/pdv") return "/venda";
  if (path === "/relatorios") return "/relatorios";
  const report = path.match(/^\/relatorios\/([^/]+)$/);
  if (report) return { pathname: "/relatorio/[slug]", params: { slug: report[1]!, ...params } };
  const record = path.match(/^\/cadastros\/([^/]+)(?:\/([^/]+))?(?:\/([^/]+))?$/);
  if (record) {
    const [, resource, id, view] = record as unknown as [string, string, string | undefined, string | undefined];
    if (!id) return { pathname: "/cadastros/[resource]", params: { resource, ...params } };
    if (id === "novo") return { pathname: "/cadastros/[resource]/novo", params: { resource, ...params } };
    if (!view) return { pathname: "/cadastros/[resource]/[id]", params: { resource, id, ...params } };
    return { pathname: "/cadastros/[resource]/[id]/[view]", params: { resource, id, view, ...params } };
  }
  return { pathname: "/retaguarda", params: { title: WEB_ONLY[path] ?? "Esta tela", path } };
}

/** `?a=1&b=2` sem depender do URLSearchParams (incompleto em alguns motores JS). */
function searchPairs(search: string): [string, string][] {
  return search.split("&").filter(Boolean).map((pair) => {
    const [k = "", v = ""] = pair.split("=");
    return [decodeURIComponent(k), decodeURIComponent(v.replace(/\+/g, " "))];
  });
}
