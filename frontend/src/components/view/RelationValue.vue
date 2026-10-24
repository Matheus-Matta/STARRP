<script setup lang="ts">
/** Nome de um registro relacionado a partir do id (cache do TanStack: cada id busca uma vez só). */
import { useQuery } from "@tanstack/vue-query";
import Skeleton from "primevue/skeleton";
import { computed } from "vue";

import { resourceApi } from "@/api/resource";
import type { Relation } from "@/resources/types";

const props = defineProps<{ relation: Relation; id: unknown }>();
const query = useQuery({
  queryKey: computed(() => ["relation-label", props.relation.endpoint, String(props.id)]),
  queryFn: () => resourceApi.get(props.relation.endpoint, String(props.id)),
  staleTime: 5 * 60_000,
  retry: false,
});
const label = computed(() => {
  const row = query.data.value as Record<string, unknown> | undefined;
  return row ? String(row[props.relation.labelKey ?? "name"] ?? row.display_name ?? row.name ?? "—") : "";
});
</script>

<template>
  <Skeleton v-if="query.isPending.value" width="8rem" height="0.9rem" />
  <span v-else-if="query.isError.value" class="muted">—</span>
  <span v-else>{{ label }}</span>
</template>
