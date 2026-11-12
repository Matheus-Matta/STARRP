/**
 * O que o campo mostra antes de ser preenchido: unidade (kg, cm, dias), limite (sem negativo,
 * % até 100) e o placeholder de exemplo. Vale para todo formulário declarativo, sem repetir
 * em cada cadastro: o declarado no `FieldDef` ganha; senão, pelo nome do campo; senão, pelo tipo.
 */
import type { FieldDef } from "@/resources/types";

/** Unidade escrita no rótulo: "Peso bruto (kg)", "Prazo (dias úteis)", "Bloquear depois de (min)". */
const LABEL_UNIT = /\((kg|g|cm|mm|m|km|pt|h|min|dias?)(?: [^)]*)?\)\s*$/i;

export function unitOf(field: Pick<FieldDef, "label" | "unit">) {
  return field.unit ?? field.label.match(LABEL_UNIT)?.[1]?.toLowerCase();
}

/** Mínimo e máximo do número: sem negativo, salvo `signed` (saldo, diferença); % até 100. */
export function boundsOf(field: Pick<FieldDef, "type" | "min" | "max" | "signed">) {
  return {
    min: field.min ?? (field.signed ? undefined : 0),
    max: field.max ?? (field.type === "percent" ? 100 : undefined),
  };
}

/** Exemplo pelo nome do campo (endereço, empresa, acesso...): o mesmo em todo cadastro. */
const BY_NAME: Record<string, string> = {
  street: "Rua, avenida, travessa…",
  number: "123 ou S/N",
  complement: "Apto, sala, bloco…",
  district: "Bairro",
  city: "Preenchida pelo CEP",
  legal_name: "Como está no cartão CNPJ",
  trade_name: "Como o cliente conhece",
  state_registration: "Só números ou ISENTO",
  municipal_registration: "Só números",
  contact_name: "Quem atende (ex.: Ana, compras)",
  email: "nome@empresa.com.br",
  username: "Ex.: maria.silva",
  first_name: "Ex.: Maria",
  last_name: "Ex.: Silva",
  agency: "Ex.: 0001",
  account_number: "Ex.: 12345-6",
  reference: "Ex.: CAM-001",
  slug: "Gerado pelo nome",
  seo_title: "Vazio = o nome do produto",
  external_number: "Nº da nota ou pedido do fornecedor",
  document_number: "Nº da nota, boleto ou pedido",
  lot_number: "Como está na embalagem",
  description: "Para que serve, em poucas palavras",
  notes: "Aparece para a equipe",
  seller_code: "Ex.: 012",
};

function numberExample(field: FieldDef) {
  const unit = unitOf(field);
  const suffix = unit ? ` ${unit}` : "";
  switch (field.type) {
    case "money": return "R$ 0,00";
    case "percent": return "0 %";
    case "quantity": return `0${suffix}`;
    case "measure": return `0,0${suffix}`;
    default: return `0${suffix}`;
  }
}

export function placeholderOf(field: FieldDef): string | undefined {
  if (field.placeholder) return field.placeholder;
  if (["number", "money", "percent", "quantity", "measure"].includes(field.type)) return numberExample(field);
  if (BY_NAME[field.name]) return BY_NAME[field.name];
  if (field.type === "email") return BY_NAME.email;
  if (field.type === "date") return "dd/mm/aaaa";
  if (field.type === "datetime") return "dd/mm/aaaa hh:mm";
  if (field.type === "select") return "Selecione";
  return undefined;
}
