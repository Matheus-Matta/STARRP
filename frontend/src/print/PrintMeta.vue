<script setup lang="ts">
/** Grade de "rótulo: valor" do topo do documento (situação, datas, responsáveis...). */
defineProps<{ items: [string, unknown][]; columns?: number }>();
</script>

<template>
  <dl class="pm" :style="{ gridTemplateColumns: `repeat(${columns ?? 3}, minmax(0, 1fr))` }">
    <div v-for="[label, value] in items" :key="label">
      <dt>{{ label }}</dt>
      <dd>{{ value === null || value === undefined || value === "" ? "—" : value }}</dd>
    </div>
  </dl>
</template>

<style>
.pm { margin: 0; display: grid; border: 1px solid #bbb; border-radius: 4px; overflow: hidden; }
.pm > div { padding: 5px 8px; border-right: 1px solid #ddd; border-bottom: 1px solid #ddd; }
.pm dt { font-size: 7pt; text-transform: uppercase; letter-spacing: 0.04em; color: #555; }
.pm dd { margin: 1px 0 0; font-size: 9.5pt; font-weight: 600; color: #111; overflow-wrap: anywhere; }
.fmt-80mm .pm { grid-template-columns: 1fr !important; border: 0; }
.fmt-80mm .pm > div { display: flex; justify-content: space-between; gap: 6px; padding: 1px 0; border: 0; }
.fmt-80mm .pm dd { font-size: 8.5pt; text-align: right; }
</style>
