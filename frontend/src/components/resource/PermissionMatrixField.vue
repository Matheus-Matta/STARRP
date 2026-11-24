<script setup lang="ts">
/** Matriz CRUD; Gerenciar marca/desmarca Criar + Editar + Excluir em conjunto. */
import { useQuery } from "@tanstack/vue-query";
import Checkbox from "primevue/checkbox";
import { computed } from "vue";

import { resourceApi } from "@/api/resource";

type Permission = { code: string; name: string; group: string; module: string; sort_order: number };
type Crud = "view" | "create" | "update" | "delete";

const props = defineProps<{ context?: Record<string, unknown>; disabled?: boolean }>();
const model = defineModel<string[]>({ default: () => [] });
const query = useQuery({
  queryKey: ["permission-matrix"],
  queryFn: () => resourceApi.list<Permission>("/permissions/", { page_size: 500, ordering: "sort_order" }),
});
const CRUD: { key: Crud; label: string }[] = [
  { key: "view", label: "Ver" }, { key: "create", label: "Criar" },
  { key: "update", label: "Editar" }, { key: "delete", label: "Excluir" },
];
const SPECIAL_LEVELS: Record<string, { access: string; full: string }> = Object.fromEntries(
  ["cosmos", "pricing", "seo"].map((area) => [area, { access: `${area}.access`, full: `${area}.full` }]),
);
const selected = computed(() => new Set(model.value ?? []));
const isAdmin = computed(() => Boolean(props.context?.is_account_admin));

const areas = computed(() => {
  const rows = new Map<string, { code: string; label: string; order: number; permissions: Partial<Record<Crud, Permission>> }>();
  for (const permission of query.data.value?.results ?? []) {
    const key = permission.code.slice(permission.code.lastIndexOf(".") + 1) as Crud;
    if (!CRUD.some((column) => column.key === key)) continue;
    const row = rows.get(permission.group) ?? {
      code: permission.group,
      label: permission.name.split(":")[0] || permission.group,
      order: permission.sort_order,
      permissions: {},
    };
    row.permissions[key] = permission;
    row.order = Math.min(row.order, permission.sort_order);
    rows.set(permission.group, row);
  }
  return [...rows.values()].sort((a, b) => a.order - b.order);
});

const specials = computed(() => (query.data.value?.results ?? []).filter((permission) => {
  const operation = permission.code.slice(permission.code.lastIndexOf(".") + 1);
  if ([...CRUD.map((column) => column.key), "manage"].includes(operation)) return false;
  // Crédito avulso continua exclusivo do Administrador/Diretor.
  return permission.code !== "partners.credit" || props.context?.code === "director";
}));

function checked(code: string | undefined) {
  return isAdmin.value || Boolean(code && selected.value.has(code));
}

function writeCodes(area: (typeof areas.value)[number]) {
  return (["create", "update", "delete"] as Crud[])
    .map((key) => area.permissions[key]?.code)
    .filter((code): code is string => Boolean(code));
}

function managed(area: (typeof areas.value)[number]) {
  const codes = writeCodes(area);
  return isAdmin.value || (codes.length === 3 && codes.every((code) => selected.value.has(code)));
}

function syncManage(next: Set<string>, areaCode: string) {
  const writes = [`${areaCode}.create`, `${areaCode}.update`, `${areaCode}.delete`];
  const manage = `${areaCode}.manage`;
  if (writes.every((code) => next.has(code))) next.add(manage);
  else next.delete(manage);
}

function toggle(code: string | undefined, enabled: boolean) {
  if (!code || props.disabled || isAdmin.value) return;
  const next = new Set(model.value ?? []);
  if (enabled) next.add(code); else next.delete(code);
  const levels = SPECIAL_LEVELS[code.slice(0, code.lastIndexOf("."))];
  if (levels && code === levels.full && enabled) next.add(levels.access);
  if (levels && code === levels.access && !enabled) next.delete(levels.full);
  syncManage(next, code.slice(0, code.lastIndexOf(".")));
  model.value = [...next];
}

function toggleManage(area: (typeof areas.value)[number], enabled: boolean) {
  if (props.disabled || isAdmin.value) return;
  const next = new Set(model.value ?? []);
  for (const code of writeCodes(area)) {
    if (enabled) next.add(code); else next.delete(code);
  }
  syncManage(next, area.code);
  model.value = [...next];
}
</script>

<template>
  <div class="pm">
    <div v-if="isAdmin" class="pm__note"><i class="pi pi-shield" /> Administrador possui acesso total automaticamente.</div>
    <div v-if="query.isPending.value" class="pm__loading"><i class="pi pi-spin pi-spinner" /> Carregando permissões…</div>
    <div v-else class="pm__scroll">
      <table>
        <thead><tr><th>Permissão</th><th v-for="column in CRUD" :key="column.key">{{ column.label }}</th>
          <th title="Marca Criar, Editar e Excluir juntos">Gerenciar</th></tr></thead>
        <tbody>
          <tr v-for="area in areas" :key="area.code">
            <th scope="row">{{ area.label }}</th>
            <td v-for="column in CRUD" :key="column.key">
              <Checkbox :model-value="checked(area.permissions[column.key]?.code)" binary
                        :disabled="disabled || isAdmin || !area.permissions[column.key]"
                        :aria-label="`${area.label}: ${column.label}`"
                        @update:model-value="toggle(area.permissions[column.key]?.code, Boolean($event))" />
            </td>
            <td class="manage">
              <Checkbox :model-value="managed(area)" binary
                        :disabled="disabled || isAdmin || writeCodes(area).length !== 3"
                        :aria-label="`${area.label}: Gerenciar`"
                        @update:model-value="toggleManage(area, Boolean($event))" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section v-if="specials.length" class="pm__special">
      <h3>Ações especiais</h3>
      <p>Autorizações que não correspondem diretamente a criar, editar ou excluir um cadastro.</p>
      <label v-for="permission in specials" :key="permission.code">
        <Checkbox :model-value="checked(permission.code)" binary :disabled="disabled || isAdmin"
                  @update:model-value="toggle(permission.code, Boolean($event))" />
        <span>{{ permission.name }}</span>
      </label>
    </section>
  </div>
</template>

<style scoped>
.pm { display: flex; min-width: 0; flex-direction: column; gap: 16px; }
.pm__note, .pm__loading { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 8px;
  background: var(--brand-subtle); color: var(--text-brand); font-size: 13px; }
.pm__scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }
table { width: 100%; min-width: 720px; border-collapse: collapse; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); }
thead th { background: var(--surface-sunken); color: var(--text-muted); font-size: 12px; text-align: center; }
thead th:first-child, tbody th { text-align: left; }
tbody th { color: var(--text-strong); font-size: 13px; font-weight: 600; }
tbody td { width: 92px; text-align: center; }
tbody td.manage, thead th:last-child { border-left: 1px solid var(--border); background: var(--surface-sunken); }
tbody tr:last-child th, tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: var(--surface-hover); }
.pm__special { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; }
.pm__special h3, .pm__special p { grid-column: 1 / -1; margin: 0; }
.pm__special h3 { color: var(--text-strong); font-size: 14px; }
.pm__special p { color: var(--text-muted); font-size: 12px; }
.pm__special label { display: flex; align-items: flex-start; gap: 8px; color: var(--text-body); font-size: 12.5px; }
@media (max-width: 680px) { .pm__special { grid-template-columns: 1fr; } }
</style>
