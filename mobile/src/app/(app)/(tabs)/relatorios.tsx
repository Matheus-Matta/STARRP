/**
 * Relatórios = `ReportsHomePage.vue`: o MESMO livro da retaguarda (`frontend/src/reports/catalog.ts`), em grupos
 * (ícone na cor da série do grupo) e cartões com a faixa lateral, só com o que o cargo e os módulos liberam.
 */
import Feather from "@expo/vector-icons/Feather";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Screen } from "@/components/Screen";
import { EmptyState, PageHeader, SearchBar } from "@/components/ui";
import { series, tokens, useThemeColors } from "@/lib/tokens";
import { iconOf } from "@/shared/frontend";
import { reportGroups } from "@/session/access";
import { useSession } from "@/session/SessionContext";

export default function ReportsTab() {
  useThemeColors();
  const router = useRouter();
  const { me } = useSession();
  const [search, setSearch] = useState("");
  const term = search.trim().toLocaleLowerCase("pt-BR");
  const groups = reportGroups(me).map((g, index) => ({
    ...g, accent: series[index % series.length]!,
    reports: g.reports.filter((r) => !term || `${r.title} ${r.description}`.toLocaleLowerCase("pt-BR").includes(term)),
  })).filter((g) => g.reports.length);

  return (
    <Screen>
      <PageHeader title="Relatórios" icon="pie-chart"
                  subtitle="O livro do negócio: escolha um relatório. Todos comparam com o período anterior e exportam a tabela." />
      <SearchBar value={search} onChangeText={setSearch} placeholder="Buscar relatório" />
      {groups.length === 0 && (
        <EmptyState icon="lock" title={term ? "Nenhum relatório encontrado" : "Nenhum relatório liberado para o seu cargo"} />
      )}
      {groups.map((group) => (
        <View key={group.label} className="gap-2.5">
          <View className="flex-row items-center gap-3">
            <View className="size-[34px] items-center justify-center rounded-[10px]" style={{ backgroundColor: group.accent }}>
              <Feather name={iconOf(group.icon, "pie-chart")} size={15} color="#ffffff" />
            </View>
            <View className="min-w-0 flex-1">
              <Text className="section-title">{group.label}</Text>
              {group.description ? <Text className="mt-0.5 font-sans text-[12.5px] text-muted">{group.description}</Text> : null}
            </View>
          </View>
          <View className="gap-2.5">
            {group.reports.map((r) => (
              <Pressable key={r.slug} onPress={() => router.push({ pathname: "/relatorio/[slug]", params: { slug: r.slug } })}
                         className="gap-1 overflow-hidden rounded-xl border border-border bg-card py-3.5 pl-[18px] pr-10 active:bg-hover">
                <View className="absolute bottom-0 left-0 top-0 w-[3px]" style={{ backgroundColor: group.accent }} />
                <View className="mb-1"><Feather name={iconOf(r.icon, "bar-chart-2")} size={16} color={group.accent} /></View>
                <Text className="font-sans-bold text-[14px] text-strong">{r.title}</Text>
                <Text className="font-sans text-[12.5px] leading-[18px] text-muted">{r.description}</Text>
                <View className="absolute right-3.5 top-3.5"><Feather name="arrow-right" size={12} color={tokens.subtle} /></View>
              </Pressable>
            ))}
          </View>
        </View>
      ))}
    </Screen>
  );
}
