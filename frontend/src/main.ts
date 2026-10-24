import "primeicons/primeicons.css";
import "@/styles/tokens.css";
import "@/styles/base.css";
import "@/styles/primevue.css";

import { VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ConfirmationService from "primevue/confirmationservice";
import ToastService from "primevue/toastservice";
import { createApp } from "vue";

import App from "./App.vue";
import { router } from "./router";
import { bindHttpToSession } from "./stores/session";
import { ptBR } from "./styles/locale";
import { StarrpPreset } from "./styles/theme";
import "./composables/useTheme";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin, {
  queryClientConfig: { defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } } },
});
// `cssLayer`: os estilos do PrimeVue ficam numa camada abaixo dos nossos, para
// os ajustes de `primevue.css` (sem camada) valerem sem `!important`.
app.use(PrimeVue, {
  theme: { preset: StarrpPreset, options: { darkModeSelector: ".dark", cssLayer: { name: "primevue", order: "primevue" } } },
  ripple: true,
  locale: ptBR,
});
app.use(ToastService);
app.use(ConfirmationService);

bindHttpToSession(() => {
  if (router.currentRoute.value.path !== "/login") router.push({ path: "/login" });
});

app.mount("#app");
