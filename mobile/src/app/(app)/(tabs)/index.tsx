/**
 * Início: só os ATALHOS (as telas do menu que o cargo, os módulos e as permissões liberam), no formato do
 * `.shortcut` da retaguarda, ordenados pelo uso neste aparelho (`lib/usage.ts`):
 *   1º–3º os mais acessados · 4º o último acessado (se não estiver entre eles) · depois a ordem do menu.
 * Os mais usados levam a marca "Mais usado"; o último, "Último acesso".
 */
import Feather from "@expo/vector-icons/Feather";
import { buildNavigation } from "@front/components/layout/navigation";
import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { useProductScan } from "@/components/ProductScan";
import { Screen } from "@/components/Screen";
import { PageHeader } from "@/components/ui";
import { tokens, useThemeColors } from "@/lib/tokens";
import { rankByUsage, recordVisit, useUsage } from "@/lib/usage";
import { useSession } from "@/session/SessionContext";
import { hrefFor, iconOf, useAccess } from "@/shared/frontend";

type Item = { key: string; label: string; group: string; icon: string; open: () => void };

export default function HomeScreen() {
  useThemeColors();
  const router = useRouter();
  const { me, can, hasModule } = useAccess();
  const { storeName, allowed } = useSession();
  const scan = useProductScan();
  const usage = useUsage();

  const items: Item[] = [
    ...(allowed("catalog.view") ? [{ key: "scan", label: "Consultar produto", group: "Leitor de código", icon: "pi pi-qrcode",
                                     open: () => { recordVisit("scan"); scan.open(); } }] : []),
    ...buildNavigation(can, hasModule).flatMap((group) => group.items.map((item) => ({
      key: item.to, label: item.to === "/pdv" ? "PDV móvel" : item.label, group: group.label, icon: item.icon,
      open: () => router.push(item.children ? "/relatorios" : hrefFor(item.to)),
    }))).filter((item) => item.key !== "/"),
  ];
  const ranked = rankByUsage(items, (i) => i.key, usage);
  const top = new Set(ranked.slice(0, 3).filter((i) => (usage.counts[i.key] ?? 0) > 0).map((i) => i.key));

  return (
    <Screen>
      {scan.scanner}
      <PageHeader title="Olá, seja bem-vindo" icon="grid" subtitle={`${me?.name ?? "Usuário"} · ${storeName}`} />
      <View className="gap-2.5">
        {ranked.map((item) => (
          <Pressable key={item.key} onPress={item.open}
                     className="min-h-[78px] flex-row items-center gap-3 rounded-[11px] border border-border bg-card p-3.5 active:border-border-strong active:bg-hover">
            <View className="size-[42px] items-center justify-center rounded-[10px] bg-brand-subtle">
              <Feather name={iconOf(item.icon, "circle")} size={17} color={tokens.brand} />
            </View>
            <View className="min-w-0 flex-1 gap-1">
              <Text numberOfLines={1} className="font-sans-bold text-[13px] text-strong">{item.label}</Text>
              <View className="flex-row items-center gap-1.5">
                <Text className="font-sans text-[10.5px] text-muted">{item.group}</Text>
                {top.has(item.key) ? <Tag label="Mais usado" /> : usage.last === item.key ? <Tag label="Último acesso" /> : null}
              </View>
            </View>
            <Feather name="arrow-right" size={11} color={tokens.subtle} />
          </Pressable>
        ))}
        {!items.length && (
          <View className="rounded-[10px] border border-dashed border-border p-7">
            <Text className="text-center font-sans text-[12px] text-muted">
              Seu administrador ainda não liberou atalhos para este perfil.
            </Text>
          </View>
        )}
      </View>
    </Screen>
  );
}

/** `.update-new` da retaguarda: etiqueta pequena em caixa alta. */
function Tag({ label }: { label: string }) {
  return (
    <View className="rounded-full bg-brand-subtle px-[7px] py-[2px]">
      <Text className="font-sans-bold text-[9.5px] uppercase text-brand-text">{label}</Text>
    </View>
  );
}
