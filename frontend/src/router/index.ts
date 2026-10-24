/**
 * Rotas. Toda rota fora de `/login` exige sessão; as de cadastro exigem
 * `<área>.view` do cadastro. A guarda só melhora a navegação — quem barra
 * de verdade é o backend.
 */
import { createRouter, createWebHistory } from "vue-router";

import AppLayout from "@/components/layout/AppLayout.vue";
import { buildNavigation } from "@/components/layout/navigation";
import { findResource } from "@/resources";
import { useSession } from "@/stores/session";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: () => import("@/pages/auth/LoginPage.vue"), meta: { public: true } },
    { path: "/pdv", component: () => import("@/pages/pdv/PdvPage.vue"), meta: { permission: "sales.manage" } },
    // Documentos para imprimir/salvar PDF: fora do layout (só o papel e a barrinha de ações).
    { path: "/imprimir/:doc/:id?", component: () => import("@/pages/PrintPage.vue") },
    {
      path: "/",
      component: AppLayout,
      children: [
        { path: "", component: () => import("@/pages/DashboardPage.vue"), meta: { title: "Painel" } },
        { path: "estoque", component: () => import("@/pages/StockOverviewPage.vue"),
          meta: { title: "Painel de estoque", permission: "stock.view", module: "stock" } },
        { path: "financeiro", component: () => import("@/pages/FinanceOverviewPage.vue"),
          meta: { title: "Painel financeiro", permission: "finance.view", module: "finance" } },
        { path: "configuracoes", component: () => import("@/pages/AccountSettingsPage.vue"),
          meta: { title: "Configurações da conta", permission: "account.admin" } },
        { path: "cadastros/:resource", component: () => import("@/pages/ResourceListPage.vue") },
        { path: "cadastros/:resource/:id", component: () => import("@/pages/ResourceFormPage.vue") },
        { path: "cadastros/:resource/:id/:view", component: () => import("@/pages/ResourceViewPage.vue") },
        { path: "sem-acesso", component: () => import("@/pages/NoAccessPage.vue"), meta: { title: "Sem acesso" } },
        { path: ":pathMatch(.*)*", component: () => import("@/pages/NoAccessPage.vue"), meta: { notFound: true, title: "Não encontrada" } },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  const session = useSession();
  if (to.meta.public) return true;
  if (!session.loaded || !session.isAuthenticated) await session.load();
  if (!session.isAuthenticated) return { path: "/login", query: { next: to.fullPath } };
  // Vendedor e caixa: o "início" deles é o PDV (não o painel da retaguarda).
  if (to.path === "/" && session.pdvFirst) return { path: "/pdv" };
  // Sem relatórios não há painel: o início é a primeira tela do menu que ele abre.
  if (to.path === "/" && !session.can("reports.view")) {
    const first = buildNavigation(session.can, session.hasModule).flatMap((g) => g.items).find((i) => i.to !== "/");
    return first ? { path: first.to } : { path: "/sem-acesso" };
  }

  const resourceName = to.params.resource as string | undefined;
  if (resourceName) {
    const resource = findResource(resourceName);
    if (!resource) return { path: "/sem-acesso" };
    if (!session.can(`${resource.permission}.view`) || !session.hasModule(resource.module)) return { path: "/sem-acesso" };
  }
  const permission = to.meta.permission as string | undefined;
  if (permission && !session.can(permission)) return { path: "/sem-acesso" };
  if (to.meta.module && !session.hasModule(to.meta.module as string)) return { path: "/sem-acesso" };
  return true;
});
