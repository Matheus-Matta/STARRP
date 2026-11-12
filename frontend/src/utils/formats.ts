/**
 * Formatos brasileiros dos campos: a máscara de digitação (InputMask) e a conferência
 * que roda ANTES de enviar ao backend (só dígitos, tamanho certo, dígito verificador,
 * código de tabela fiscal que existe).
 *
 *   { name: "cfop", label: "CFOP", type: "text", format: "cfop" }
 *
 * O valor guardado é só com os dígitos; a máscara é desenho. Telefone, CEP e documento
 * já pegam o seu pelo tipo do campo (`formatOf`).
 */
import { MASKS } from "./masks";

type Format = {
  mask: string;
  /** Erro do valor completo (só dígitos), ou null. */
  check?: (digits: string) => string | null;
};

const oneOf = (codes: string, label: string) => {
  const list = codes.split(" ");
  // Tabela longa: só alguns exemplos na mensagem (a lista inteira não cabe embaixo do campo).
  const sample = list.length > 12 ? `${[list[0], list[9], list.at(-1)].join(", ")}…` : list.join(", ");
  return (d: string) => (list.includes(d) ? null : `${label} inexistente (ex.: ${sample}).`);
};

/** Chave da NF-e / NFC-e: 44 dígitos, o último confere os outros 43 (módulo 11, pesos 2 a 9). */
function accessKeyError(d: string) {
  let sum = 0;
  for (let i = 42, weight = 2; i >= 0; i--, weight = weight === 9 ? 2 : weight + 1) sum += Number(d[i]) * weight;
  const rest = sum % 11;
  return (rest < 2 ? 0 : 11 - rest) === Number(d[43]) ? null : "Chave de acesso inválida (dígito verificador não confere).";
}

/** DDD existe (11 a 99, sem zero) e celular (11 dígitos) começa com 9. */
function phoneError(d: string) {
  if (/0/.test(d.slice(0, 2))) return "DDD inválido.";
  if (d.length === 11 && d[2] !== "9") return "Celular começa com 9 depois do DDD.";
  return null;
}

export const FORMATS = {
  phone: { mask: MASKS.phone, check: phoneError },
  cep: { mask: MASKS.cep, check: (d) => (/^0+$/.test(d) ? "CEP inválido." : null) },
  ncm: { mask: MASKS.ncm, check: (d) => (/^0+$/.test(d) ? "NCM inválido." : null) },
  cest: { mask: MASKS.cest },
  ibge: { mask: MASKS.ibge, check: (d) => (/^[1-5]/.test(d) ? null : "Código IBGE começa com 1 a 5 (região do país).") },
  /** CFOP de saída: 5 = mesma UF, 6 = outra UF, 7 = exterior. */
  cfop: { mask: "9.999", check: (d) => (/^[567]/.test(d) ? null : "CFOP de venda começa com 5, 6 ou 7.") },
  "cfop-interstate": { mask: "9.999", check: (d) => (d.startsWith("6") ? null : "CFOP para outra UF começa com 6.") },
  "cst-pis": {
    mask: "99",
    check: oneOf("01 02 03 04 05 06 07 08 09 49 50 51 52 53 54 55 56 60 61 62 63 64 65 66 67 70 71 72 73 74 75 98 99", "CST"),
  },
  "access-key": { mask: "9999 9999 9999 9999 9999 9999 9999 9999 9999 9999 9999", check: accessKeyError },
  /** Código COMPE do banco (001 Banco do Brasil, 341 Itaú, 260 Nubank...). */
  bank: { mask: "999" },
  /** PLU da balança, ID do CSC: só número, até 6 dígitos. */
  digits6: { mask: "9?99999" },
  digits2: { mask: "9?9" },
} satisfies Record<string, Format>;

export type FormatName = keyof typeof FORMATS;

/** Formato do campo: o declarado ou o do tipo (telefone, CEP). Documento fica com `documents.ts`. */
export function formatOf(field: { type?: string; format?: FormatName }): Format | undefined {
  if (field.format) return FORMATS[field.format];
  if (field.type === "phone" || field.type === "cep") return FORMATS[field.type];
  return undefined;
}

/** Quantos dígitos a máscara pede: o mínimo (antes do `?`) e o máximo. */
function digitRange(mask: string) {
  const [required = "", optional = ""] = mask.split("?");
  const count = (s: string) => (s.match(/9/g) ?? []).length;
  return { min: count(required), max: count(required) + count(optional) };
}

/** Erro do valor na máscara: incompleto, ou não passa na conferência do formato. */
export function maskError(value: unknown, mask: string, format?: Format): string | null {
  const digits = String(value ?? "").replace(/\D/g, "");
  if (!digits) return null;
  const { min, max } = digitRange(mask);
  if (digits.length < min || digits.length > max) {
    return `Incompleto: ${min === max ? `${min} dígitos` : `${min} a ${max} dígitos`} (${mask.replace("?", "").replace(/9/g, "0")}).`;
  }
  return format?.check?.(digits) ?? null;
}
