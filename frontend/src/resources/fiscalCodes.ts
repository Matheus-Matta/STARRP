/**
 * Tabelas fiscais curtas que viram lista de escolha (o código com a descrição), em vez de
 * o usuário decorar o número. As longas (CST de PIS/COFINS) ficam no campo com máscara
 * conferido em `utils/formats.ts`.
 */
import type { Option } from "./types";

// Ordenado pelo código: "00" não é chave numérica e o JS a poria depois do "90".
const options = (map: Record<string, string>): Option[] => Object.entries(map)
  .sort(([a], [b]) => a.localeCompare(b)).map(([value, label]) => ({ value, label: `${value} - ${label}` }));

/** Origem da mercadoria (tabela A do ICMS). */
export const ORIGINS = options({
  0: "Nacional",
  1: "Estrangeira, importação direta",
  2: "Estrangeira, comprada no mercado interno",
  3: "Nacional, mais de 40% de conteúdo importado",
  4: "Nacional, processo produtivo básico",
  5: "Nacional, até 40% de conteúdo importado",
  6: "Estrangeira direta, sem similar nacional (CAMEX)",
  7: "Estrangeira interna, sem similar nacional (CAMEX)",
  8: "Nacional, mais de 70% de conteúdo importado",
});

/** CSOSN: situação do ICMS no Simples Nacional. */
export const CSOSN = options({
  101: "Tributada com permissão de crédito",
  102: "Tributada sem permissão de crédito",
  103: "Isenção por faixa de receita",
  201: "Com crédito e cobrança por ST",
  202: "Sem crédito e com cobrança por ST",
  203: "Isenção por faixa e cobrança por ST",
  300: "Imune",
  400: "Não tributada",
  500: "ICMS cobrado antes por ST",
  900: "Outros",
});

/** CST do ICMS: regime normal (lucro presumido / real). */
export const CST_ICMS = options({
  "00": "Tributada integralmente",
  10: "Tributada com cobrança por ST",
  20: "Com redução de base de cálculo",
  30: "Isenta / não tributada com ST",
  40: "Isenta",
  41: "Não tributada",
  50: "Suspensão",
  51: "Diferimento",
  60: "ICMS cobrado antes por ST",
  70: "Redução de base com ST",
  90: "Outras",
});
