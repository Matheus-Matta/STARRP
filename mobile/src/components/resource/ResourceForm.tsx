/**
 * Formulário de QUALQUER cadastro (criar e editar), como o `ResourceFormPage` da retaguarda: seções com
 * título e explicação, os mesmos campos e condições, a mesma conferência antes de enviar
 * (`frontend/src/utils/validation`) e os erros do backend em cada campo. Sair com alterações pergunta antes.
 */
import { validate } from "@front/utils/validation";
import * as Haptics from "expo-haptics";
import { Stack, usePreventRemove, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError, setScopedStore } from "@/api/client";
import { FormField } from "@/components/resource/FormField";
import { Screen } from "@/components/Screen";
import { Button, ErrorBox, FormSection, Loading, Note } from "@/components/ui";
import { confirmAction, notify } from "@/lib/dialog";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";
import { iconOf, useAccess } from "@/shared/frontend";
import {
  accessOf, defaultsOf, formSections, newLabel, payloadOf, recordHref, resourceApi,
} from "@/shared/resource";
import type { ResourceDef } from "@/shared/types";
import { recordTitle } from "@/shared/values";

type Values = Record<string, unknown>;

export function ResourceForm({ resource, id, query = {} }: {
  resource: ResourceDef; id: string | null; query?: Record<string, string>;
}) {
  useThemeColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { me, can, hasModule } = useAccess();
  const isNew = !id;
  const access = accessOf(resource, can, me);
  const [values, setValues] = useState<Values>(() => (isNew ? initial(resource, query) : {}));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(!isNew);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [snapshot, setSnapshot] = useState(() => JSON.stringify(values));
  const allowLeave = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (isNew) return;
    let alive = true;
    resourceApi.get(resource.endpoint, id)
      .then((row) => {
        if (!alive) return;
        setValues(row);
        setSnapshot(JSON.stringify(row));
      })
      .catch((e) => alive && setLoadError(errorMessage(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [resource.endpoint, id, isNew]);

  // Sair com alterações não salvas: pergunta antes (como o aviso de rascunho da retaguarda).
  const [leaving, setLeaving] = useState(false);
  const dirty = !leaving && !loading && JSON.stringify(values) !== snapshot;
  const disablePrevention = usePreventRemove(dirty, ({ repeat }) => {
    confirmAction("Descartar alterações?", "O que você mudou ainda não foi salvo.", "Descartar", () => {
      setLeaving(true);
      allowLeave.current();
      repeat();
    }, true);
  });
  useEffect(() => {
    allowLeave.current = disablePrevention;
  }, [disablePrevention]);

  const canWrite = isNew ? access.canCreate : access.canEdit(values);
  const title = isNew ? newLabel(resource) : loading ? resource.singular : `Editar: ${recordTitle(values, resource)}`;
  const sections = formSections(resource, values, isNew, can, hasModule);

  function change(name: string, value: unknown) {
    setValues((v) => ({ ...v, [name]: value }));
    if (errors[name]) setErrors(({ [name]: _gone, ...rest }) => rest);
  }

  /** O CEP traz o endereço: só entram os campos que este cadastro tem. */
  function fill(patch: Record<string, string>) {
    const names = new Set(resource.fields.map((f) => f.name));
    setValues((v) => ({ ...v, ...Object.fromEntries(Object.entries(patch).filter(([k, x]) => names.has(k) && x)) }));
  }

  async function save() {
    const local = validate(resource.fields, values);
    setErrors(local);
    if (Object.keys(local).length) {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      notify("Confira os campos", Object.values(local)[0]);
      return;
    }
    setSaving(true);
    try {
      const body = payloadOf(resource, values, isNew);
      // Editar em "Todas as filiais": grava na filial do próprio registro (senão, a principal do usuário).
      const own = !isNew && typeof values.store === "string" && me?.stores.some((s) => s.id === values.store)
        ? values.store : null;
      if (own) setScopedStore(own);
      const saved = await (isNew ? resourceApi.create(resource.endpoint, body)
        : resourceApi.update(resource.endpoint, id, body)).finally(() => {
        if (own) setScopedStore(null);
      });
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setLeaving(true);
      allowLeave.current();
      if (isNew) router.replace(recordHref(resource, String(saved.id)));
      else router.back();
    } catch (e) {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      if (e instanceof ApiError && Object.keys(e.fields).length) setErrors(e.fields);
      notify("Não foi possível salvar", errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Loading />;
  if (loadError) return <Screen><ErrorBox message={loadError} /></Screen>;
  if (!canWrite) {
    return (
      <Screen>
        <Stack.Screen options={{ title }} />
        <ErrorBox message="Este registro não pode ser alterado (sem permissão ou já confirmado)." />
      </Screen>
    );
  }

  const orphanErrors = Object.entries(errors).filter(([k]) => !resource.fields.some((f) => f.name === k));

  return (
    <View className="flex-1 bg-ground">
      <Stack.Screen options={{ title }} />
      <ScrollView className="flex-1" contentContainerClassName="page pb-28" keyboardShouldPersistTaps="handled">
        {/* `.head`: título 18px (quebra linha no celular) e o que é o cadastro. */}
        <View>
          <Text className="h1">{isNew ? newLabel(resource) : recordTitle(values, resource)}</Text>
          <Text className="h1-sub">{isNew ? `Novo registro em ${resource.title.toLowerCase()}` : `Editando ${resource.singular}`}</Text>
        </View>
        {resource.systemNote && resource.systemData ? <Note icon="lock">{resource.systemNote}</Note> : null}
        {orphanErrors.map(([k, m]) => <ErrorBox key={k} message={m} />)}
        <View>
          {sections.map(([name, fields], i) => {
            const info = resource.sections?.[name];
            return (
              <FormSection key={name} title={name} description={info?.description} first={i === 0}
                           icon={info?.icon ? iconOf(info.icon) : undefined}>
                {fields.map((field) => (
                  <FormField key={field.name} field={field} values={values} value={values[field.name]}
                             onChange={(v) => change(field.name, v)} error={errors[field.name]} onFill={fill}
                             disabled={field.readOnly && !me?.is_superuser} />
                ))}
              </FormSection>
            );
          })}
        </View>
      </ScrollView>
      {/* `.actionbar` (≤560px): fixa embaixo, situação à esquerda, botões à direita. */}
      <View className="absolute left-4 right-4" style={{ bottom: 12 + insets.bottom }}>
        <View className={dirty ? "actionbar border-brand-border" : "actionbar"}>
          <View className="flex-row items-center gap-2 pl-1.5">
            <View className="size-[9px] rounded-full" style={{ backgroundColor: dirty ? tokens.accent : tokens.success }} />
          </View>
          <View className="flex-1 flex-row justify-end gap-[6.4px]">
            <Button label="Cancelar" variant="text" compact disabled={saving} onPress={() => router.back()} />
            <Button label={isNew ? "Criar" : "Salvar"} icon="check" compact loading={saving} onPress={() => void save()} />
          </View>
        </View>
      </View>
    </View>
  );
}

/** Cadastro novo: padrões, valores fixos e o que veio pela URL (".../novo?kind=exit"). */
function initial(resource: ResourceDef, query: Record<string, string>) {
  const values = defaultsOf(resource);
  const names = new Set(resource.fields.map((f) => f.name));
  for (const [key, value] of Object.entries(query)) if (names.has(key) && typeof value === "string") values[key] = value;
  return values;
}
