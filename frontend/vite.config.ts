/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig, loadEnv } from "vite";

// O .env fica na RAIZ do projeto (compartilhado com o backend).
const envDir = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, "VITE_");
  return {
    envDir,
    plugins: [vue()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      port: 5173,
      // Proxy da API: app e API na MESMA origem, como os cookies httpOnly (SameSite=Lax) exigem.
      proxy: {
        "/api": { target: env.VITE_API_TARGET || "http://localhost:8000", changeOrigin: true },
        // Fotos enviadas (produto, variante): o Django serve em desenvolvimento.
        "/media": { target: env.VITE_API_TARGET || "http://localhost:8000", changeOrigin: true },
      },
    },
    build: {
      rollupOptions: {
        // Bibliotecas em pedaços próprios: mudam pouco e ficam no cache do navegador entre versões do app.
        output: {
          manualChunks: {
            primevue: ["primevue/config", "@primeuix/themes", "@primeuix/themes/aura"],
            vendor: ["vue", "vue-router", "pinia", "@tanstack/vue-query", "axios", "zod"],
          },
        },
      },
    },
    test: { environment: "jsdom", globals: false },
  };
});
