<script setup lang="ts">
/** Índice dos relatórios: os grupos do livro (Movimento, Mercadorias, Contábil, Relacionamento). */
import { computed } from "vue";

import PageHeader from "@/components/common/PageHeader.vue";
import { visibleGroups } from "@/reports/catalog";
import { useSession } from "@/stores/session";

const session = useSession();
const groups = computed(() => visibleGroups(session.can, session.hasModule));
</script>

<template>
  <section class="page">
    <PageHeader title="Relatórios" icon="pi pi-chart-pie"
                subtitle="O livro do negócio: escolha um relatório. Todos comparam com o período anterior e exportam a tabela." />
    <div v-for="(group, g) in groups" :key="group.label" class="group">
      <header class="group__head" :style="{ '--accent': `var(--series-${g + 1})` }">
        <span class="group__icon"><i :class="group.icon" /></span>
        <div><h2>{{ group.label }}</h2><p>{{ group.description }}</p></div>
      </header>
      <div class="cards">
        <RouterLink v-for="r in group.reports" :key="r.slug" :to="`/relatorios/${r.slug}`" class="card-link"
                    :style="{ '--accent': `var(--series-${g + 1})` }">
          <i :class="r.icon" class="card-link__icon" />
          <strong>{{ r.title }}</strong>
          <span>{{ r.description }}</span>
          <i class="pi pi-arrow-right card-link__go" />
        </RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.group { display: flex; flex-direction: column; gap: 10px; }
.group__head { display: flex; gap: 12px; align-items: center; }
.group__icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; color: #fff; background: var(--accent); }
.group__head h2 { margin: 0; font: 700 15px/1.2 var(--font-sans); color: var(--text-strong); }
.group__head p { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); gap: 10px; }
.card-link { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 14px 16px 14px 18px; border-radius: 12px;
             border: 1px solid var(--border); background: var(--surface-card); color: inherit; overflow: hidden;
             transition: border-color var(--dur-fast) ease, transform var(--dur-fast) ease, box-shadow var(--dur-fast) ease; }
.card-link::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--accent); }
.card-link:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.card-link__icon { font-size: 16px; color: var(--accent); margin-bottom: 4px; }
.card-link strong { font-size: 14px; color: var(--text-strong); }
.card-link span { font-size: 12.5px; color: var(--text-muted); line-height: 1.45; }
.card-link__go { position: absolute; top: 14px; right: 14px; font-size: 12px; color: var(--text-subtle); }
</style>
