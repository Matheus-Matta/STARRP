/**
 * Motivos fixos do PDV (botões na pergunta). Fixos de propósito: o relatório de cancelamentos
 * agrupa pelo texto. "Outro motivo" continua aberto para o caso raro.
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

export const PARK_REASONS = ["Cliente volta depois", "Aguardando produto do estoque", "Aguardando aprovação de crédito"];
