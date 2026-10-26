/**
 * Avaliações (padrão do StarHub): o cliente avalia os produtos e a entrega pelo link da venda
 * (botão "Link de avaliação" na venda). Toda avaliação nasce pendente: aqui se aprova ou
 * rejeita (com motivo). A loja também registra uma avaliação contada no balcão ou no telefone.
 */
import { defineAsyncComponent } from "vue";

import { reviewsApi } from "@/api/reviews";

import { choices, defineResource } from "./types";

const ReviewSummary = defineAsyncComponent(() => import("@/components/reviews/ReviewSummary.vue"));
const RejectReviewDialog = defineAsyncComponent(() => import("@/components/reviews/RejectReviewDialog.vue"));

export const reviewKind = choices({ product: "Produto", delivery: "Entrega" });
export const reviewStatus = choices({ pending: "Pendente", approved: "Aprovada", rejected: "Rejeitada" });
const stars = choices({ 5: "★★★★★ Ótimo", 4: "★★★★ Bom", 3: "★★★ Regular", 2: "★★ Ruim", 1: "★ Péssimo" });

export const reviews = defineResource({
  name: "avaliacoes",
  title: "Avaliações",
  singular: "avaliação",
  feminine: true,
  endpoint: "/reviews/",
  permission: "sales",
  icon: "pi pi-star",
  group: "Vendas",
  ordering: "-created_at",
  /** Depois de criada não se edita (só modera): o que o cliente escreveu fica como está. */
  lockedWhen: (v) => Boolean(v.id),
  summary: ReviewSummary,
  columns: [
    { key: "created_at", label: "Quando", type: "datetime" },
    { key: "public_name", label: "Cliente", title: true },
    { key: "rating", label: "Nota", type: "stars" },
    { key: "kind", label: "Tipo", type: "tag", map: reviewKind.map, tones: { product: "brand", delivery: "info" } },
    { key: "product_name", label: "Produto" },
    { key: "comment", label: "Comentário", mobile: false },
    { key: "status", label: "Situação", type: "tag", map: reviewStatus.map,
      tones: { pending: "warning", approved: "success", rejected: "danger" } },
    { key: "verified_purchase", label: "Compra verificada", type: "boolean" },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: reviewStatus.options },
    { name: "kind", label: "Tipo", type: "select", options: reviewKind.options },
    { name: "rating", label: "Nota", type: "select", options: stars.options },
    { name: "created_at", label: "Período", type: "daterange" },
  ],
  sections: {
    Avaliação: { icon: "pi pi-star", description: "Registre aqui o que o cliente contou no balcão ou no telefone. "
      + "Pelo link da venda, ele mesmo avalia (e manda fotos)." },
  },
  fields: [
    { name: "kind", label: "O que foi avaliado", type: "segmented", options: reviewKind.options, default: "product",
      section: "Avaliação", full: true },
    { name: "product", label: "Produto", type: "relation", relation: { endpoint: "/catalog/products/" }, section: "Avaliação",
      visible: (v) => v.kind !== "delivery" },
    { name: "sale", label: "Venda", type: "relation", relation: { endpoint: "/sales/", labelKey: "number" }, section: "Avaliação",
      hint: "Com a venda, a avaliação ganha o selo de compra verificada." },
    { name: "customer", label: "Cliente", type: "relation", relation: { endpoint: "/customers/" }, section: "Avaliação" },
    { name: "rating", label: "Nota", type: "segmented", options: stars.options.map((o) => ({ ...o, value: Number(o.value) })),
      required: true, section: "Avaliação", full: true },
    { name: "comment", label: "Comentário", type: "textarea", maxLength: 1500, section: "Avaliação", full: true },
  ],
  display: { sections: [] },
  formActions: [
    { label: "Aprovar", icon: "pi pi-check", severity: "success", visible: (v) => v.status !== "approved",
      success: "Avaliação aprovada", run: ({ id }) => reviewsApi.approve(id) },
    { label: "Rejeitar", icon: "pi pi-times", severity: "danger", visible: (v) => v.status !== "rejected",
      dialog: RejectReviewDialog },
  ],
});
