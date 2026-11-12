/**
 * Organização do estoque (Estoque): o que a Cosmos recomenda mudar nos endereços para a separação andar menos.
 * Aceitar cria a movimentação em rascunho; o estoque só muda quando a equipe confirmar o documento.
 */
import { stockAdviceApi } from "@/api/stockAdvice";

import { choices, defineResource, linkTo, rowsOf } from "./types";

const kind = choices({ dock: "Parado na doca", together: "Saem juntos", fast: "Sai muito", scattered: "Espalhado", idle: "Não sai" });
const status = choices({ open: "Para decidir", applied: "Aceita", dismissed: "Recusada", expired: "Não vale mais" });
const tones = { open: "warning", applied: "success", dismissed: "neutral", expired: "neutral" } as const;
const open = (v: Record<string, unknown>) => v.status === "open";
const canMove = (v: Record<string, unknown>) => open(v) && rowsOf(v, "moves").length > 0;

export const stockAdvices = defineResource({
  name: "organizacao-estoque",
  title: "Organização do estoque",
  singular: "recomendação",
  feminine: true,
  endpoint: "/stock/advices/",
  permission: "stock",
  module: "cosmos_stock",
  group: "Estoque",
  icon: "pi pi-sparkles",
  ordering: "-impact",
  creatable: false,
  editable: false,
  deletable: false,
  readOnly: true,
  searchable: true,
  columns: [
    { key: "title", label: "Recomendação", title: true },
    { key: "kind", label: "Tipo", type: "tag", map: kind.map },
    { key: "warehouse_name", label: "Depósito", mobile: false },
    { key: "status", label: "Situação", type: "tag", map: status.map, tones },
    { key: "checked_at", label: "Analisado em", type: "datetime", mobile: false },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: status.options },
    { name: "kind", label: "Tipo", type: "select", options: kind.options },
  ],
  fields: [],
  display: {
    badges: (v) => [
      { label: kind.map[String(v.kind)] ?? "", icon: "pi pi-sparkles" },
      { label: status.map[String(v.status)] ?? "", tone: tones[v.status as keyof typeof tones] },
    ],
    sections: [
      { title: "Por que mudar", icon: "pi pi-lightbulb", items: [
        { label: "O que a Cosmos viu", key: "detail", span: "full" },
        { label: "Depósito", key: "warehouse_name" },
        { label: "Analisado em", key: "checked_at", type: "datetime" },
        { label: "Movimentação criada", key: "document_number", link: (v) => linkTo("entradas-e-saidas", v.document), visible: (v) => Boolean(v.document) },
        { label: "Quem decidiu", key: "decided_by_name", visible: (v) => Boolean(v.decided_at) },
        { label: "Quando decidiu", key: "decided_at", type: "datetime", visible: (v) => Boolean(v.decided_at) },
      ] },
      { title: "O que mover", icon: "pi pi-arrow-right-arrow-left",
        description: "Só oferecemos endereço vazio. O sistema não sabe o tamanho das caixas: confira se cabe antes de confirmar a movimentação.",
        table: { rows: (v) => rowsOf(v, "moves"), empty: "Não há endereço livre para esta mudança: libere um e analise de novo.", columns: [
          { key: "description", label: "Produto", title: true },
          { key: "lot_label", label: "Lote" },
          { key: "from_code", label: "De" },
          { key: "to_code", label: "Para" },
          { key: "quantity", label: "Quantidade", type: "quantity" },
        ] } },
    ],
  },
  formActions: [
    { label: "Recusar", icon: "pi pi-times", severity: "danger", permission: "stock.manage", visible: open, success: "Recomendação recusada",
      run: ({ id }) => stockAdviceApi.dismiss(id) },
    { label: "Criar movimentação", icon: "pi pi-check", severity: "success", permission: "stock.manage", visible: canMove,
      success: "Movimentação criada em rascunho. Confira e confirme para o estoque mudar",
      run: async ({ id }) => {
        const advice = await stockAdviceApi.apply(id);
        const { router } = await import("@/router");
        await router.push(`/cadastros/entradas-e-saidas/${advice.document}`);
      } },
  ],
  listActions: [
    { label: "Analisar agora", icon: "pi pi-refresh", severity: "secondary", permission: "stock.manage", success: "Análise concluída",
      run: () => stockAdviceApi.run() },
  ],
});
