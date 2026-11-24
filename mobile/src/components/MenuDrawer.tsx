/**
 * Menu do app no TOPO, como a retaguarda no celular: a barra de cima (`AppTopbar.vue`) tem o botão ☰ que abre
 * o menu lateral (`AppSidebar.vue` ≤960px: gaveta que entra da esquerda com sombra e fundo escurecido).
 * O conteúdo é o mesmo menu da retaguarda (`navigation.ts`): filial, busca, grupos filtrados por cargo e
 * módulos, e o usuário no fim (sair). Tocar num item fecha a gaveta e abre a tela.
 */
import Feather from "@expo/vector-icons/Feather";
import { buildNavigation, type NavItem } from "@front/components/layout/navigation";
import { usePathname, useRouter } from "expo-router";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Animated, Easing, Image, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AnimatedView } from "@/components/styled";
import { type Appearance, currentAppearance, setAppearance } from "@/lib/appearance";
import { confirmAction } from "@/lib/dialog";
import { tokens, useThemeColors } from "@/lib/tokens";
import { useSession } from "@/session/SessionContext";
import { hrefFor, iconOf, useAccess } from "@/shared/frontend";

const LOGO = require("../../assets/brand/logo.png");
const LOGO_DARK = require("../../assets/brand/logo-light.png");
/** `--sidebar-w` é 232px; no celular um pouco mais larga para os alvos de toque. */
const WIDTH = 288;

const MenuContext = createContext<{ open: () => void }>({ open: () => undefined });

export function MenuDrawerProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(false);
  const [shown, setShown] = useState(false);
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    if (!visible) return;
    Animated.timing(progress, { toValue: 1, duration: 280, easing: Easing.bezier(0.22, 1, 0.36, 1), useNativeDriver: true })
      .start();
  }, [visible, progress]);

  const open = useCallback(() => {
    setVisible(true);
    setShown(true);
  }, []);
  const close = useCallback(() => {
    Animated.timing(progress, { toValue: 0, duration: 180, useNativeDriver: true }).start(() => setShown(false));
    setVisible(false);
  }, [progress]);
  const value = useMemo(() => ({ open }), [open]);

  return (
    <MenuContext.Provider value={value}>
      {children}
      <Modal visible={shown} transparent animationType="none" onRequestClose={close} statusBarTranslucent>
        <AnimatedView className="absolute bottom-0 left-0 right-0 top-0 bg-overlay" style={{ opacity: progress }}>
          <Pressable className="flex-1" onPress={close} accessibilityLabel="Fechar menu" />
        </AnimatedView>
        <AnimatedView className="absolute bottom-0 left-0 top-0 border-r border-nav-border bg-nav-bg shadow-lg"
                       style={{ width: WIDTH, transform: [{ translateX: progress.interpolate({ inputRange: [0, 1],
                                                                                              outputRange: [-WIDTH, 0] }) }] }}>
          <NavMenu onClose={close} />
        </AnimatedView>
      </Modal>
    </MenuContext.Provider>
  );
}

export const useMenuDrawer = () => useContext(MenuContext);

/** `.icon-btn` da barra de cima: 32px (alvo de toque 40px), ícone apagado. */
export function MenuButton() {
  useThemeColors();
  const { open } = useMenuDrawer();
  return (
    <Pressable onPress={open} hitSlop={8} accessibilityLabel="Abrir menu"
               className="size-9 items-center justify-center rounded-[7px] active:bg-hover">
      <Feather name="menu" size={18} color={tokens.muted} />
    </Pressable>
  );
}

/** Telas que só existem no computador. */
const DESKTOP = new Set(["/configuracoes", "/integracoes"]);

/** O item do menu corresponde à tela aberta? (`.nav__item--active`; também conta o uso para a tela Início) */
export function isActive(to: string, pathname: string) {
  if (to === "/") return pathname === "/";
  if (to === "/pdv") return pathname.startsWith("/venda");
  if (to === "/relatorios") return pathname.startsWith("/relatorio");
  return pathname === to || pathname.startsWith(`${to}/`);
}

function NavMenu({ onClose }: { onClose: () => void }) {
  const { dark } = useThemeColors();
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { me, can, hasModule } = useAccess();
  const { storeName, signOut, canUse } = useSession();
  const [search, setSearch] = useState("");

  const groups = buildNavigation(can, hasModule);
  // Do app (não existem na retaguarda): o lançamento rápido de estoque pelo leitor.
  const app: NavItem[] = canUse("stockManage") ? [{ label: "Movimentar estoque", icon: "pi pi-arrow-right-arrow-left", to: "/movimentar" }] : [];
  const all = app.length ? [...groups, { label: "No celular", items: app }] : groups;
  const term = search.trim().toLocaleLowerCase("pt-BR");
  const filtered = term
    ? all.map((g) => ({ ...g, items: g.items.filter((i) => i.label.toLocaleLowerCase("pt-BR").includes(term)
                                                           || g.label.toLocaleLowerCase("pt-BR").includes(term)) }))
      .filter((g) => g.items.length)
    : all;

  const roles = me?.roles.length ? me.roles : me?.role ? [me.role] : [];
  const initials = (me?.name || me?.username || "?").split(" ").filter(Boolean).slice(0, 2)
    .map((w) => w[0]?.toUpperCase()).join("");

  function go(item: NavItem) {
    onClose();
    if (item.to === "/movimentar") return router.navigate("/movimentar");
    router.navigate(item.children ? "/relatorios" : hrefFor(item.to));
  }

  return (
    <View className="flex-1" style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}>
      {/* `.nav__brand`: logo e fechar, na altura da barra de cima (52px). */}
      <View className="h-[52px] flex-row items-center gap-2.5 px-4">
        <Image source={dark ? LOGO_DARK : LOGO} className="h-[26px] w-[96px]" resizeMode="contain" accessibilityLabel="Starrp" />
        <Pressable onPress={onClose} hitSlop={8} accessibilityLabel="Fechar menu"
                   className="ml-auto size-8 items-center justify-center rounded-md active:bg-nav-hover">
          <Feather name="x" size={16} color={tokens.navMuted} />
        </Pressable>
      </View>

      {/* `.nav__store` */}
      <View className="px-2.5 pb-2">
        <Pressable onPress={() => {
          onClose();
          router.navigate("/filial");
        }} className="flex-row items-center gap-2.5 rounded-lg border border-nav-border bg-nav-hover px-2.5 py-2 active:border-border-strong">
          <View className="size-7 items-center justify-center rounded-[7px] bg-nav-active">
            <Feather name="home" size={13} color={tokens.navActiveText} />
          </View>
          <View className="min-w-0 flex-1">
            <Text numberOfLines={1} className="font-sans-semibold text-[13px] text-nav-strong">{storeName}</Text>
            <Text numberOfLines={1} className="font-sans text-[11px] text-nav-muted">{me?.account?.name ?? "Filial ativa"}</Text>
          </View>
          <Feather name="chevron-down" size={12} color={tokens.navMuted} />
        </Pressable>
      </View>

      {/* `.nav__search` */}
      <View className="mx-2.5 mb-1.5 h-10 flex-row items-center gap-2 rounded-[7px] border border-nav-border px-2.5">
        <Feather name="search" size={13} color={tokens.navMuted} />
        <TextInput value={search} onChangeText={setSearch} placeholder="Buscar no menu" placeholderTextColor={tokens.navMuted}
                   autoCorrect={false} autoCapitalize="none" className="flex-1 py-1.5 font-sans-medium text-[16px] text-nav-text" />
        {search ? (
          <Pressable hitSlop={8} onPress={() => setSearch("")} accessibilityLabel="Limpar">
            <Feather name="x" size={14} color={tokens.navMuted} />
          </Pressable>
        ) : null}
      </View>

      {/* `.nav__list` */}
      <ScrollView className="flex-1" contentContainerClassName="px-2.5 pb-3 pt-1" keyboardShouldPersistTaps="handled">
        {filtered.map((group) => (
          <View key={group.label} className="mt-2.5">
            <Text className="nav-group-header">{group.label}</Text>
            {group.items.map((item) => {
              const active = isActive(item.to, pathname);
              return (
                <Pressable key={item.to + item.label} onPress={() => go(item)}
                           className={active ? "nav-item bg-nav-active" : "nav-item active:bg-nav-hover"}>
                  <View className="w-4 items-center">
                    <Feather name={iconOf(item.icon, "circle")} size={14} color={active ? tokens.navActiveText : tokens.navMuted} />
                  </View>
                  <Text numberOfLines={1}
                        className={active ? "nav-item-text flex-1 font-sans-semibold text-nav-active-text" : "nav-item-text flex-1"}>
                    {item.to === "/pdv" ? "PDV móvel" : item.label}
                  </Text>
                  {DESKTOP.has(item.to) && <Feather name="monitor" size={12} color={tokens.navMuted} />}
                  {item.children ? <Feather name="chevron-right" size={11} color={tokens.navMuted} /> : null}
                </Pressable>
              );
            })}
          </View>
        ))}
        {!!term && !filtered.length && (
          <Text className="px-2 py-4 font-sans text-[13px] text-nav-muted">Nada no menu com “{search}”.</Text>
        )}
      </ScrollView>

      <AppearancePicker />

      {/* `.nav__user`: avatar 28px, nome e cargo; tocar sai. */}
      <Pressable onPress={() => confirmAction("Sair do app?", "Você vai precisar entrar de novo.", "Sair", () => {
        onClose();
        void signOut();
      }, true)} className="flex-row items-center gap-2.5 border-t border-nav-border px-3.5 py-2.5 active:bg-nav-hover">
        <View className="size-7 items-center justify-center rounded-full bg-brand-300">
          <Text className="font-sans-bold text-[11px] text-brand-950">{initials}</Text>
        </View>
        <View className="min-w-0 flex-1">
          <Text numberOfLines={1} className="font-sans-bold text-[12.5px] text-nav-strong">{me?.name}</Text>
          <Text numberOfLines={1} className="font-sans text-[11px] text-nav-muted">
            {roles.map((r) => r.name).join(", ") || (me?.is_superuser ? "Superusuário" : me?.username)}
          </Text>
        </View>
        <Feather name="log-out" size={14} color={tokens.navMuted} />
      </Pressable>
    </View>
  );
}

const APPEARANCES: { value: Appearance; label: string; icon: "sun" | "moon" | "smartphone" }[] = [
  { value: "light", label: "Claro", icon: "sun" },
  { value: "dark", label: "Escuro", icon: "moon" },
  { value: "system", label: "Sistema", icon: "smartphone" },
];

/** Aparência do app (como o seletor de tema da retaguarda): claro, escuro ou a do celular. Fica salva no aparelho. */
function AppearancePicker() {
  useThemeColors();
  const [value, setValue] = useState<Appearance>(currentAppearance);
  return (
    <View className="gap-1.5 border-t border-nav-border px-3.5 py-2.5">
      <Text className="nav-group-header px-0">Aparência</Text>
      <View className="flex-row gap-[3px] rounded-[9px] border border-nav-border p-[3px]">
        {APPEARANCES.map((option) => {
          const on = value === option.value;
          return (
            <Pressable key={option.value} accessibilityRole="button" accessibilityState={{ selected: on }}
                       accessibilityLabel={`Tema ${option.label.toLowerCase()}`}
                       onPress={() => {
                         setValue(option.value);
                         void setAppearance(option.value);
                       }}
                       className={on ? "min-h-9 flex-1 flex-row items-center justify-center gap-1.5 rounded-md bg-nav-active"
                         : "min-h-9 flex-1 flex-row items-center justify-center gap-1.5 rounded-md active:bg-nav-hover"}>
              <Feather name={option.icon} size={13} color={on ? tokens.navActiveText : tokens.navMuted} />
              <Text className={on ? "font-sans-semibold text-[12px] text-nav-active-text" : "font-sans-semibold text-[12px] text-nav-muted"}>
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
