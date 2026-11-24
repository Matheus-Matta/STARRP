/**
 * `@/router` (vue-router) da retaguarda no celular: `router.push("/cadastros/entradas-e-saidas/12")` navega no app
 * (Expo Router), pela mesma tradução de rotas das outras telas (`hrefFor`). Usado pelas ações dos cadastros que
 * levam a outra tela depois de terminar (ex.: "Criar movimentação" na organização do estoque).
 */
import { router as appRouter } from "expo-router";

import { hrefFor } from "@/shared/frontend";

type To = string | { path?: string; query?: Record<string, string> };

const pathOf = (to: To) => {
  if (typeof to === "string") return to;
  const query = Object.entries(to.query ?? {}).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  return `${to.path ?? "/"}${query ? `?${query}` : ""}`;
};

export const router = {
  push: async (to: To) => appRouter.push(hrefFor(pathOf(to))),
  replace: async (to: To) => appRouter.replace(hrefFor(pathOf(to))),
  back: () => appRouter.back(),
  go: (n: number) => (n < 0 ? appRouter.back() : undefined),
};

export const useRouter = () => router;
export const useRoute = () => ({ params: {}, query: {}, path: "/" });
export const createRouter = () => router;
export const createWebHistory = () => undefined;
export const RouterLink = { __starrpWebOnly: true };
export const RouterView = { __starrpWebOnly: true };
export default router;
