/**
 * Histórico do registro (quem fez o quê e quando), no fim de toda página de registro, como na retaguarda.
 * Fonte: GET <cadastro>/<id>/history/ (backend `services/history.py`), 10 por vez.
 */
import Feather from "@expo/vector-icons/Feather";
import { dateTime } from "@front/utils/format";
import { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { Button } from "@/components/ui";
import { type Tone, toneColors } from "@/lib/theme";
import { tokens, useThemeColors } from "@/lib/tokens";
import { iconOf } from "@/shared/frontend";
import { resourceApi } from "@/shared/resource";
import type { ResourceDef } from "@/shared/types";

type Change = { field: string; from: string; to: string };
type Event = { id: string; kind: string; label: string; tone: string; icon: string; at: string; by: string; note: string;
               changes: Change[] };

const PAGE = 10;

export function HistoryFeed({ resource, id, version }: { resource: ResourceDef; id: string; version?: unknown }) {
  useThemeColors();
  const [rows, setRows] = useState<Event[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function load(next: number) {
    setLoading(true);
    setFailed(false);
    try {
      const data = await resourceApi.list(`${resource.endpoint}${id}/history/`, { page: next, page_size: PAGE });
      const results = data.results as unknown as Event[];
      setRows((prev) => (next === 1 ? results : [...prev, ...results]));
      setTotal(data.count);
      setPage(next);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(1);
  }, [resource.endpoint, id, version]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    // `.hf`: cabeçalho como o das seções e a linha do tempo direto no fundo (sem cartão).
    <View className="gap-[8.8px] pt-4">
      <View className="flex-row flex-wrap items-baseline gap-x-3 px-0.5">
        <View className="flex-row items-center gap-[7px]">
          <Feather name="clock" size={13} color={tokens.brand} />
          <Text className="fsec-title">Histórico</Text>
          {total ? <Text className="font-sans-semibold text-[12px] text-muted">{total}</Text> : null}
        </View>
        <Text className="fsec-desc">Quem fez o quê e quando: criação, alterações (com o que mudou) e cada etapa do registro.</Text>
      </View>
      <View className="px-1 pb-1 pt-2.5">
        {(failed || (!loading && !rows.length)) && (
          <Text className="pb-4 pt-3 font-sans text-[13px] text-muted">
            {failed ? "Não foi possível carregar o histórico." : "Nada registrado ainda."}
          </Text>
        )}
        {rows.map((e, i) => {
          const tone = toneOf(e.tone);
          return (
            <View key={e.id} className="flex-row">
              <View className="items-center">
                <View className="size-[30px] items-center justify-center rounded-full"
                      style={{ backgroundColor: tone.bg, boxShadow: `0 0 0 4px ${tokens.ground}` }}>
                  <Feather name={iconOf(e.icon, "circle")} size={12} color={tone.fg} />
                </View>
                {i < rows.length - 1 && <View className="w-0.5 flex-1 bg-border-subtle" />}
              </View>
              <View className="min-w-0 flex-1 pb-[18px] pl-3 pt-1">
                <View className="flex-row flex-wrap items-baseline gap-x-2.5">
                  <Text className="font-sans-bold text-[14px] text-strong">{e.label}</Text>
                  {e.by ? (
                    <View className="flex-row items-center gap-1">
                      <Feather name="user" size={10} color={tokens.subtle} />
                      <Text className="font-sans text-[12.5px] text-body">{e.by}</Text>
                    </View>
                  ) : null}
                  <Text className="w-full font-sans text-[12px] text-muted">{ago(e.at)}</Text>
                </View>
                {e.note ? <Text className="mt-1 font-sans text-[13px] text-body">{e.note}</Text> : null}
                {e.changes?.length ? (
                  <View className="mt-2 gap-[5px] rounded-md bg-sunken px-3 py-2">
                    {e.changes.map((c, ci) => (
                      <View key={`${c.field}-${ci}`} className="flex-row flex-wrap items-center gap-2">
                        <Text className="min-w-[120px] font-sans-semibold text-[13px] text-muted">{c.field}</Text>
                        <Text className="font-sans text-[13px] text-muted line-through">{c.from || "—"}</Text>
                        <Feather name="arrow-right" size={10} color={tokens.subtle} />
                        <Text className="font-sans-semibold text-[13px] text-strong">{c.to || "—"}</Text>
                      </View>
                    ))}
                  </View>
                ) : null}
              </View>
            </View>
          );
        })}
        {loading && <ActivityIndicator color={tokens.brand} className="my-2" />}
        {!loading && page > 0 && rows.length < total && (
          <View className="items-center pb-2.5 pt-1">
            <Button label="Ver mais" variant="ghost" compact onPress={() => void load(page + 1)} />
          </View>
        )}
      </View>
    </View>
  );
}

/** `.tone-*` do marcador: o tom do evento sobre o fundo suave do tom (segue o tema). */
function toneOf(tone: string) {
  if (tone === "neutral") return { fg: tokens.muted, bg: tokens.hover };
  const known = ["success", "warning", "danger", "info"].includes(tone) ? (tone as Tone) : "brand";
  return toneColors(known);
}

/** "há 5 min", "há 2 h", "há 3 dias" (igual à retaguarda). */
function ago(at: string) {
  const minutes = Math.round((Date.now() - new Date(at).getTime()) / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.round(hours / 24);
  return days < 31 ? `há ${days} ${days === 1 ? "dia" : "dias"}` : dateTime(at);
}
