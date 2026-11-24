/**
 * Barra de atalhos no TOPO do app, da esquerda para a direita:
 *   Menu · [atalho 1] · Início · [atalho 2] · Relatórios
 * Menu abre o menu lateral da retaguarda (`MenuDrawer`). Os atalhos 1 e 2 se adaptam ao PERFIL: cada um é o
 * primeiro da sua lista que o cargo e os módulos liberam (o vendedor, sem estoque, vê Clientes no lugar de
 * Estoque; o estoquista, sem vendas, vê Produtos no lugar de Vendas). Sem repetir; sem nada liberado, some.
 * Cores do menu da retaguarda (`--nav-*`): item ativo com fundo azul-claro.
 */
import Feather from "@expo/vector-icons/Feather";
import { type Href, type Tabs, useRouter } from "expo-router";
import type { ComponentProps } from "react";
import { Pressable, Text, View } from "react-native";

import { useMenuDrawer } from "@/components/MenuDrawer";
import { tokens, useThemeColors } from "@/lib/tokens";
import { canSeeReports } from "@/session/access";
import { useAccess } from "@/shared/frontend";

type BarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>["tabBar"]>>[0];
type IconName = ComponentProps<typeof Feather>["name"];

/** Um atalho: aba do app (`tab`) ou tela empilhada (`href`), liberado por permissão/módulo. */
type Shortcut = { key: string; label: string; icon: IconName; permission?: string; module?: string; tab?: string;
                  href?: Href };

const cadastro = (resource: string): Href => ({ pathname: "/cadastros/[resource]", params: { resource } });

const SHORTCUTS: Record<string, Shortcut> = {
  vendas: { key: "vendas", label: "Vendas", icon: "shopping-cart", permission: "sales.view", href: cadastro("vendas") },
  estoque: { key: "estoque", label: "Estoque", icon: "package", permission: "stock.view", module: "stock", tab: "estoque" },
  clientes: { key: "clientes", label: "Clientes", icon: "users", permission: "partners.view", href: cadastro("clientes") },
  produtos: { key: "produtos", label: "Produtos", icon: "box", permission: "catalog.view", href: cadastro("produtos") },
  financeiro: { key: "financeiro", label: "Financeiro", icon: "dollar-sign", permission: "finance.view", module: "finance",
                href: "/financeiro" },
  caixas: { key: "caixas", label: "Caixas", icon: "inbox", permission: "cash.view", href: cadastro("turnos-de-caixa") },
};

/** Ordem de preferência de cada vaga variável (o primeiro liberado ganha). */
const SLOT_1 = ["vendas", "produtos", "clientes", "caixas", "financeiro"];
const SLOT_2 = ["estoque", "financeiro", "clientes", "produtos", "caixas"];

export function TopTabBar({ state, emitter, navigateToTab, insets }: BarProps) {
  useThemeColors();
  const { open } = useMenuDrawer();
  const router = useRouter();
  const { me, can, hasModule } = useAccess();
  const allowed = (s: Shortcut) => can(s.permission) && hasModule(s.module);
  const first = SLOT_1.map((k) => SHORTCUTS[k]!).find(allowed);
  const second = SLOT_2.map((k) => SHORTCUTS[k]!).find((s) => s.key !== first?.key && allowed(s));

  const items: Shortcut[] = [
    { key: "menu", label: "Menu", icon: "menu" },
    ...(first ? [first] : []),
    { key: "index", label: "Início", icon: "home", tab: "index" },
    ...(second ? [second] : []),
    ...(canSeeReports(me) ? [{ key: "relatorios", label: "Relatórios", icon: "bar-chart-2" as const, tab: "relatorios" }] : []),
  ];
  const focused = state.routes[state.index]?.name;

  function press(item: Shortcut) {
    if (item.key === "menu") return open();
    if (item.href) return router.push(item.href);
    const route = state.routes.find((r) => r.name === item.tab);
    if (!route) return;
    const event = emitter.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
    if (focused !== item.tab && !event.defaultPrevented) navigateToTab(route.key);
  }

  return (
    <View className="border-b border-nav-border bg-nav-bg" style={{ paddingTop: insets.top }}>
      <View className="h-[60px] flex-row items-stretch px-1">
        {items.map((item) => {
          const active = !!item.tab && focused === item.tab;
          return (
            <Pressable key={item.key} onPress={() => press(item)} accessibilityRole="tab"
                       accessibilityState={{ selected: active }} accessibilityLabel={item.key === "menu" ? "Abrir menu" : item.label}
                       className="flex-1 items-center justify-center gap-[3px] active:opacity-70">
              <View className={active ? "h-7 w-12 items-center justify-center rounded-full bg-nav-active"
                : "h-7 w-12 items-center justify-center rounded-full"}>
                <Feather name={item.icon} size={18} color={active ? tokens.navActiveText : tokens.navMuted} />
              </View>
              <Text numberOfLines={1}
                    className={active ? "font-sans-semibold text-[11px] text-nav-active-text" : "font-sans-semibold text-[11px] text-nav-muted"}>
                {item.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
