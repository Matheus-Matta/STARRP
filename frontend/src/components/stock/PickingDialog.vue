<script setup lang="ts">
/**
 * Lista de separação: ONDE pegar cada item (endereço e lote), na ordem do
 * caminho do depósito, e a carga (caixas, peso, m³) para o frete.
 * "Imprimir" abre a impressão do navegador só com a lista.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";

import { stockApi } from "@/api/operations";
import { openPrint } from "@/utils/print";
import type { FormActionContext } from "@/resources/types";
import { date, quantity } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const printList = () => openPrint("separacao", props.ctx.id);
const picking = useQuery({ queryKey: ["picking", props.ctx.id], queryFn: () => stockApi.picking(props.ctx.id) });
</script>

<template>
  <div class="picking">
    <div v-if="picking.isPending.value" class="stack"><Skeleton v-for="n in 5" :key="n" height="1.6rem" /></div>
    <p v-else-if="picking.error.value" class="muted">{{ (picking.error.value as Error).message }}</p>
    <template v-else-if="picking.data.value">
      <p class="muted">Documento {{ picking.data.value.document }} · {{ picking.data.value.warehouse }}</p>
      <table class="list">
        <thead><tr><th>Endereço</th><th>Produto</th><th>Lote</th><th class="right">Qtd.</th></tr></thead>
        <tbody>
          <tr v-for="(line, i) in picking.data.value.lines" :key="i">
            <td class="bin">{{ line.bin || "—" }}</td>
            <td><strong>{{ line.description }}</strong> <small class="muted">{{ line.sku }}</small></td>
            <td>{{ line.lot || "—" }} <small v-if="line.expires_at" class="muted">val. {{ date(line.expires_at) }}</small></td>
            <td class="right"><strong>{{ quantity(line.quantity) }}</strong></td>
          </tr>
        </tbody>
      </table>
      <div v-if="picking.data.value.shortages.length" class="shortage">
        <i class="pi pi-exclamation-triangle" />
        Falta saldo: {{ picking.data.value.shortages.map((s) => `${s.description} (${quantity(s.missing_quantity)})`).join(", ") }}
      </div>
      <div class="load">
        <span><i class="pi pi-box" /> {{ picking.data.value.load.box_count }} caixas</span>
        <span><i class="pi pi-arrow-down" /> {{ quantity(picking.data.value.load.gross_weight) }} kg</span>
        <span><i class="pi pi-th-large" /> {{ Number(picking.data.value.load.cubic_meters).toLocaleString("pt-BR") }} m³</span>
        <Button label="Imprimir" icon="pi pi-print" size="small" severity="secondary" outlined class="print" @click="printList" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 8px; }
.list { width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 13.5px; }
.list th { text-align: left; padding: 8px; font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em;
           color: var(--text-muted); background: var(--surface-sunken); }
.list td { padding: 8px; border-top: 1px solid var(--border-subtle); }
.right { text-align: right; }
.bin { font: 700 14px/1 var(--font-mono); color: var(--text-strong); }
.shortage { margin-top: 0.75rem; padding: 8px 10px; border-radius: 8px; background: var(--warning-subtle); color: var(--warning-text); font-size: 13px; }
.load { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-top: 0.75rem; font-size: 13px; color: var(--text-muted); }
.load i { margin-right: 4px; }
.print { margin-left: auto; }
</style>
