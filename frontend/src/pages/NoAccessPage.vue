<script setup lang="ts">
import Button from "primevue/button";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/common/EmptyState.vue";

const route = useRoute();
const router = useRouter();
</script>

<template>
  <section class="page">
    <div class="card">
      <EmptyState v-if="route.meta.notFound" icon="pi pi-compass" title="Página não encontrada"
                  description="Este endereço não existe ou foi movido.">
        <Button label="Ir para o início" icon="pi pi-home" @click="router.push('/')" />
      </EmptyState>
      <EmptyState v-else icon="pi pi-lock" title="Sem acesso"
                  description="Seu cargo não permite abrir esta tela, ou o módulo não está no plano da conta.">
        <Button label="Ir para o início" icon="pi pi-home" @click="router.push('/')" />
      </EmptyState>
    </div>
  </section>
</template>
