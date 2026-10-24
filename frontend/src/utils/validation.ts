/**
 * Validação de formulário gerada da descrição do cadastro (`FieldDef`).
 *
 * É a validação de CONVENIÊNCIA (avisar antes de enviar). A que vale é a do
 * backend: os erros por campo que ele devolve aparecem no mesmo lugar.
 */
import { z, type ZodTypeAny } from "zod";

import type { FieldDef } from "@/resources/types";

import { documentError } from "./documents";

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
    const base = z.union([z.number(), z.string(), z.null()]).optional();
    return field.required
      ? base.refine((v) => v !== null && v !== undefined && v !== "", "Campo obrigatório.")
      : base;
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
  return schema;
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
