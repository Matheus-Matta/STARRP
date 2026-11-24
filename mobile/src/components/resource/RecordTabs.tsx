/**
 * Abas do registro (`RecordTabs.vue`): "Dados" + as consultas (movimentos, vendas, extrato...). Rolam para o lado;
 * a ativa tem o texto e o traço de baixo na cor da marca.
 */
import Feather from "@expo/vector-icons/Feather";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, Text } from "react-native";

import { notify } from "@/lib/dialog";
import { tokens, useThemeColors } from "@/lib/tokens";
import { iconOf, useAccess } from "@/shared/frontend";
import { isWebOnly } from "@/shared/resource";
import type { ResourceDef } from "@/shared/types";

export function RecordTabs({ resource, id, active }: { resource: ResourceDef; id: string; active: string }) {
  useThemeColors();
  const router = useRouter();
  const { can, hasModule } = useAccess();
  const views = (resource.views ?? []).filter((v) => can(v.permission) && hasModule(v.module));
  if (!views.length) return null;
  const tabs = [{ name: "dados", label: "Dados", icon: "pi pi-file", webOnly: false }, ...views.map((v) => ({
    name: v.name, label: v.label, icon: v.icon, webOnly: isWebOnly(v.component) && !v.list,
  }))];

  function open(name: string, label: string, webOnly: boolean) {
    if (name === active) return;
    if (webOnly) return notify(label, "Esta consulta tem uma tela própria na retaguarda. Abra pelo computador.");
    if (name === "dados") return router.back();
    const params = { resource: resource.name, id, view: name };
    if (active === "dados") router.push({ pathname: "/cadastros/[resource]/[id]/[view]", params });
    else router.replace({ pathname: "/cadastros/[resource]/[id]/[view]", params });
  }

  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
                className="mx-[-16px] grow-0 border-b border-border" contentContainerClassName="gap-0.5 px-4">
      {tabs.map((tab) => {
        const on = tab.name === active;
        return (
          <Pressable key={tab.name} onPress={() => open(tab.name, tab.label, tab.webOnly)}
                     className={on ? "mb-[-1px] flex-row items-center gap-[7px] border-b-2 border-brand px-3.5 py-3"
                       : "mb-[-1px] flex-row items-center gap-[7px] border-b-2 border-transparent px-3.5 py-3 active:opacity-70"}>
            <Feather name={iconOf(tab.icon, "list")} size={12.5} color={on ? tokens.brandText : tokens.muted} />
            <Text className={on ? "font-sans-semibold text-[13px] text-brand-text" : "font-sans-semibold text-[13px] text-muted"}>
              {tab.label}
            </Text>
            {tab.webOnly && <Feather name="monitor" size={11} color={tokens.subtle} />}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
