/**
 * Menu da retaguarda. Os cadastros entram sozinhos (de `resources/`), agrupados
 * pelo `group` deles; telas especiais (painel, PDV) são declaradas aqui.
 * Item sem permissão ou de módulo fora do plano nem aparece.
 */
import { resources } from "@/resources";

export type NavItem = { label: string; icon: string; to: string; permission?: string; module?: string };
export type NavGroup = { label: string; items: NavItem[] };

/** Pelo processo: vender → o que se vende → comprar → guardar → entregar → receber/pagar → fiscal → ajustes. */
const GROUP_ORDER = ["Vendas", "Catálogo", "Promoções", "Compras", "Estoque", "Logística", "Financeiro", "Fiscal",
                     "Configurações"];

/** Telas especiais que FECHAM o grupo (depois dos cadastros). `account.admin` só o administrador tem. */
const FOOTERS: Record<string, NavItem> = {
  Configurações: { label: "Configurações da conta", icon: "pi pi-cog", to: "/configuracoes", permission: "account.admin" },
};

/** Telas especiais que abrem o grupo (painéis), antes dos cadastros dele. */
const PANELS: Record<string, NavItem> = {
  Estoque: { label: "Painel de estoque", icon: "pi pi-warehouse", to: "/estoque", permission: "stock.view", module: "stock" },
  Financeiro: { label: "Painel financeiro", icon: "pi pi-chart-line", to: "/financeiro", permission: "finance.view",
                module: "finance" },
};

export function buildNavigation(can: (code?: string) => boolean, hasModule: (m?: string) => boolean): NavGroup[] {
  const groups: NavGroup[] = [
    {
      label: "Operação",
      items: [
        { label: "Painel", icon: "pi pi-chart-bar", to: "/", permission: "reports.view" },
        { label: "PDV", icon: "pi pi-shopping-cart", to: "/pdv", permission: "sales.manage" },
      ],
    },
  ];
  for (const name of GROUP_ORDER) {
    const items = resources
      .filter((r) => r.group === name)
      .map((r) => ({ label: r.title, icon: r.icon, to: `/cadastros/${r.name}`, permission: `${r.permission}.view`,
                     module: r.module }));
    groups.push({ label: name, items: [...(PANELS[name] ? [PANELS[name]] : []), ...items,
                                       ...(FOOTERS[name] ? [FOOTERS[name]] : [])] });
  }
  return groups
    .map((g) => ({ ...g, items: g.items.filter((i) => can(i.permission) && hasModule(i.module)) }))
    .filter((g) => g.items.length);
}
