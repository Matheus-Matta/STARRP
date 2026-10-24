/**
 * Motivos fixos do PDV (botões no PromptDialog). Fixos de propósito: o relatório de
 * cancelamentos agrupa pelo texto, e um toque é mais rápido (e menos sujeito a erro)
 * que digitar. "Outro motivo" continua aberto para o caso raro.
 */
export const CANCEL_SALE_REASONS = [
  "Cliente desistiu da compra",
  "Venda lançada por engano",
  "Pagamento recusado",
  "Preço divergente",
  "Produto sem estoque",
  "Venda duplicada",
];

export const REMOVE_ITEM_REASONS = [
  "Lançado por engano",
  "Cliente desistiu do item",
  "Quantidade errada",
  "Produto com defeito",
  "Trocou por outro produto",
  "Preço divergente",
];

export const PARK_REASONS = [
  "Enviado ao caixa",
  "Cliente volta depois",
  "Aguardando produto do estoque",
  "Aguardando aprovação de crédito",
];
