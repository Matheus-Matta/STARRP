<script setup lang="ts">
import ConfirmDialog from "primevue/confirmdialog";
import Toast from "primevue/toast";
import { RouterView } from "vue-router";

import ApprovalDialog from "@/components/common/ApprovalDialog.vue";
</script>

<template>
  <RouterView />
  <Toast position="top-right" />
  <ConfirmDialog />
  <ApprovalDialog />
</template>
