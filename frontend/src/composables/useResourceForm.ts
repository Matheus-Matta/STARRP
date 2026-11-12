/**
 * Formulário de qualquer cadastro: carrega, valida, salva e mostra erros.
 *
 * Erro por campo vem de dois lugares e cai no MESMO mapa: a validação local
 * (aviso rápido) e a resposta do backend (a que vale).
 *
 * A conferência local roda ao sair do campo (`check`) e de novo a cada mudança de um
 * campo com erro: corrigiu, o aviso some na hora, sem precisar salvar para ver.
 */
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref, type Ref, watch } from "vue";

import { toApiError } from "@/api/errors";
import { resourceApi, type Row } from "@/api/resource";
import type { ResourceDef } from "@/resources/types";
import { validate, validateField, withError } from "@/utils/validation";

import { detailKey } from "./usePrefetch";

function defaults(resource: ResourceDef) {
  const values = Object.fromEntries(resource.fields.filter((f) => f.default !== undefined).map((f) => [f.name, f.default]));
  return { ...values, ...resource.params };
}

export function useResourceForm(resource: Ref<ResourceDef>, id: Ref<string | null>) {
  const queryClient = useQueryClient();
  const values = ref<Record<string, unknown>>({});
  const errors = ref<Record<string, string>>({});
  const loading = ref(false);
  const saving = ref(false);
  const isNew = computed(() => !id.value);

  /** `force`: ignora o cache (o registro acabou de mudar no servidor: baixa, confirmação...). */
  async function load(force = false) {
    setErrors({});
    if (isNew.value) {
      values.value = defaults(resource.value);
      return;
    }
    const key = detailKey(resource.value.endpoint, id.value!);
    // Já pré-carregado (mouse na linha da lista)? Abre sem esperar e sem skeleton.
    const cached = queryClient.getQueryData<Row>(key);
    const fresh = Date.now() - (queryClient.getQueryState(key)?.dataUpdatedAt ?? 0) < 15_000;
    if (cached && fresh && !force) {
      values.value = structuredClone(cached);
      return;
    }
    const fetchRow = () => queryClient.fetchQuery({ queryKey: key, staleTime: 0,
                                                    queryFn: () => resourceApi.get(resource.value.endpoint, id.value!) });
    // O registro já está na tela (uma ação mudou algo nele): relê por baixo, sem skeleton,
    // sem desmontar a tela nem perder a rolagem.
    if (force && String(values.value.id ?? "") === id.value) {
      values.value = structuredClone(await fetchRow());
      return;
    }
    loading.value = true;
    try {
      values.value = structuredClone(await fetchRow());
    } finally {
      loading.value = false;
    }
  }

  /** Só os campos do formulário vão para a API; senha vazia não troca a senha. */
  function payload() {
    // Valores fixos do cadastro (ex.: { kind: "payable" }) vão sempre na criação.
    const body: Record<string, unknown> = isNew.value ? { ...resource.value.params } : {};
    for (const field of resource.value.fields) {
      if (!(field.name in values.value)) continue;
      const value = values.value[field.name];
      if (field.type === "password" && !value) continue;
      body[field.name] = value === undefined ? null : value;
    }
    return body;
  }

  /** Saiu do campo: confere o que foi digitado. Vazio só acusa no "Salvar" (não grita "obrigatório" ao passar com Tab). */
  function check(name: string) {
    const field = resource.value.fields.find((f) => f.name === name);
    if (!field) return;
    const message = validateField(field, values.value);
    const value = values.value[name];
    if (message && value !== null && value !== undefined && value !== "") setError(name, message);
    else if (!message) clearError(name);
  }

  /* Valor de cada campo quando o erro apareceu: mudou, confere de novo (o erro do backend também sai). */
  const errorAt = new Map<string, string>();
  function setError(name: string, message: string) {
    errors.value = withError(errors.value, name, message);
    errorAt.set(name, JSON.stringify(values.value[name] ?? null));
  }
  function clearError(name: string) {
    if (!(name in errors.value)) return;
    errors.value = withError(errors.value, name);
    errorAt.delete(name);
  }
  function setErrors(next: Record<string, string>) {
    errors.value = next;
    errorAt.clear();
    for (const name of Object.keys(next)) errorAt.set(name, JSON.stringify(values.value[name] ?? null));
  }
  watch(values, () => {
    for (const [name, before] of errorAt) {
      if (JSON.stringify(values.value[name] ?? null) === before) continue;
      const field = resource.value.fields.find((f) => f.name === name);
      const message = field && validateField(field, values.value);
      if (message) setError(name, message);
      else clearError(name);
    }
  }, { deep: true });

  async function save(): Promise<Row | null> {
    setErrors(validate(resource.value.fields, values.value));
    if (Object.keys(errors.value).length) return null;
    saving.value = true;
    try {
      const saved = isNew.value
        ? await resourceApi.create(resource.value.endpoint, payload())
        : await resourceApi.update(resource.value.endpoint, id.value!, payload());
      queryClient.setQueryData(detailKey(resource.value.endpoint, String(saved.id)), saved);
      void queryClient.invalidateQueries({ queryKey: ["resource", resource.value.endpoint] });
      // O que voltou é a verdade: ids novos, SKUs gerados, variantes criadas pela grade.
      values.value = structuredClone(saved);
      return saved;
    } catch (error) {
      const apiError = toApiError(error);
      setErrors(apiError.fields);
      throw apiError;
    } finally {
      saving.value = false;
    }
  }

  return { values, errors, loading, saving, isNew, load, save, check };
}
