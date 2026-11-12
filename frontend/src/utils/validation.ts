/**
 * Validação de formulário gerada da descrição do cadastro (`FieldDef`).
 *
 * É a validação de CONVENIÊNCIA (avisar antes de enviar). A que vale é a do
 * backend: os erros por campo que ele devolve aparecem no mesmo lugar.
 */
import { z, type ZodTypeAny } from "zod";

import type { FieldDef } from "@/resources/types";

import { documentError } from "./documents";
import { boundsOf } from "./fieldHints";
import { formatOf, maskError } from "./formats";

const NUMERIC = new Set(["number", "money", "percent", "quantity", "measure"]);

/** Toda variante precisa de preço (zero vale: brinde, item de kit). */
const variants = z.array(z.record(z.any())).optional().refine(
  (rows) => !rows || rows.every((row) => row.price !== null && row.price !== undefined && row.price !== ""),
  "Informe o preço de todas as variantes.",
);

function fieldSchema(field: FieldDef): ZodTypeAny {
  if (field.type === "boolean") return z.boolean().optional();
  if (field.type === "variants") return variants;
  if (field.type === "grid" || field.type === "seo-preview") return z.any();  // prévia não é dado
  if (field.type === "metafields") return z.record(z.any()).optional().nullable();  // conferido no backend (definições)
  if (["multirelation", "barcodes", "volumes", "tags", "multiselect", "stock-items", "installments", "images",
       "addresses", "zip-ranges", "promotion-rules"]
    .includes(field.type)) {
    return z.array(z.any()).optional().nullable();
  }
  if (field.type === "segmented") return z.any();
  if (NUMERIC.has(field.type)) {
    const { min, max } = boundsOf(field);
    return z.union([z.number(), z.string(), z.null()]).optional().superRefine((v, ctx) => {
      const fail = (message: string) => ctx.addIssue({ code: z.ZodIssueCode.custom, message });
      if (v === null || v === undefined || v === "") return field.required ? fail("Campo obrigatório.") : undefined;
      const n = Number(v);
      if (Number.isNaN(n)) return fail("Número inválido.");
      if (min !== undefined && n < min) return fail(min === 0 ? "Não pode ser negativo." : `Mínimo ${min}.`);
      if (max !== undefined && n > max) fail(`Máximo ${max.toLocaleString("pt-BR")}${field.type === "percent" ? " %" : ""}.`);
    });
  }
  let text = z.string({ invalid_type_error: "Valor inválido." });
  if (field.maxLength) text = text.max(field.maxLength, `Máximo de ${field.maxLength} caracteres.`);
  if (field.type === "email") return text.email("E-mail inválido.").or(z.literal("")).optional();
  const schema = field.required ? text.min(1, "Campo obrigatório.") : text.optional().nullable();
  if (field.type === "document") {
    return schema.refine((v) => !v || documentError(String(v)) === null, (v) => ({
      message: documentError(String(v)) ?? "Documento inválido.",
    }));
  }
  // Máscara (CEP, telefone, NCM, CFOP...): incompleto ou código que não confere não sai daqui.
  const format = formatOf(field);
  const mask = field.mask ?? format?.mask;
  if (mask) {
    return schema.refine((v) => !maskError(v, mask, format), (v) => ({ message: maskError(v, mask, format) ?? "" }));
  }
  return schema;
}

/** Mapa de erros com `key` trocado: com mensagem, põe; sem, tira. */
export function withError(errors: Record<string, string>, key: string, message?: string) {
  const next = { ...errors };
  if (message) next[key] = message;
  else delete next[key];
  return next;
}

/** Erro de UM campo agora (ao sair dele, ao corrigir), sem esperar o "Salvar". */
export function validateField(field: FieldDef, values: Record<string, unknown>): string | undefined {
  return validate([field], values)[field.name];
}

export function validate(fields: FieldDef[], values: Record<string, unknown>): Record<string, string> {
  const visible = fields.filter((f) => !f.visible || f.visible(values));
  const shape = Object.fromEntries(visible.map((f) => [f.name, fieldSchema(f)]));
  const result = z.object(shape).safeParse(values);
  if (result.success) return {};
  const errors: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const key = String(issue.path[0]);
    errors[key] ??= issue.message;
  }
  return errors;
}
