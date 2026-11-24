/**
 * Valor para LER, igual à retaguarda (`CellValue.vue` e `FieldValue.vue`): dinheiro formatado, rótulo da
 * opção (não o código), nome do relacionado (não o id), "Sim/Não", máscara de documento/telefone/CEP.
 * Campos compostos (itens, parcelas, variantes...) viram tabela (`compositeTable`).
 */
import { formatDocument } from "@front/utils/documents";
import { date, dateTime, money, percent, quantity } from "@front/utils/format";
import { formatOf } from "@front/utils/formats";
import { applyMask, formatPhone, MASKS } from "@front/utils/masks";

import type { ColumnDef, FieldDef, Tone } from "@/shared/types";

type Row = Record<string, any>;

export const isEmpty = (v: unknown) => v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length);

/** Coluna da lista. */
export function cellText(column: ColumnDef, value: unknown): string {
  switch (column.type) {
    case "money": return money(value);
    case "quantity": return quantity(value);
    case "percent": return percent(value);
    case "date": return date(value);
    case "datetime": return dateTime(value);
    case "tag": return column.map?.[String(value)] ?? (isEmpty(value) ? "—" : String(value));
    case "boolean": {
      const active = column.key.startsWith("is_active");
      return value ? (active ? "Ativo" : "Sim") : active ? "Inativo" : "Não";
    }
    case "stars": return isEmpty(value) ? "—" : `${"★".repeat(Math.round(Number(value)))} ${Number(value).toLocaleString("pt-BR")}`;
    default: return isEmpty(value) ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
  }
}

export const isNumericColumn = (type?: string) => ["money", "quantity", "percent"].includes(type ?? "");

/** Tom da etiqueta (`tag`/`boolean`) de uma coluna ou item. */
export function toneOf(spec: { type?: string; key?: string; name?: string; tones?: Record<string, Tone> }, value: unknown): Tone {
  if (spec.type === "boolean") return value ? "success" : "neutral";
  return spec.tones?.[String(value)] ?? "brand";
}

/** Campo do formulário (ou item da visualização) para leitura. */
export type ViewField = Omit<FieldDef, "type"> & {
  type: FieldDef["type"] | "tag"; map?: Record<string, string>; tones?: Record<string, Tone>;
};

/** Nome do relacionado que o serializer já manda (`warehouse_name`, `supplier_name`). */
export function relationName(field: ViewField, values: Row): string | undefined {
  const name = values[`${field.name}_name`] ?? values[`${field.name.replace(/^financial_/, "")}_name`];
  return name === null || name === undefined ? undefined : String(name);
}

export function fieldText(field: ViewField, values: Row): string {
  const v = values[field.name];
  if (isEmpty(v)) return "—";
  const option = field.options?.find((o) => String(o.value) === String(v))?.label;
  switch (field.type) {
    case "money": return money(v);
    case "percent": return percent(v);
    case "quantity": case "measure": return quantity(v);
    case "number": return Number(v).toLocaleString("pt-BR");
    case "date": return date(v);
    case "datetime": return dateTime(v);
    case "document": return formatDocument(String(v));
    case "phone": return formatPhone(v);
    case "cep": return applyMask(v, MASKS.cep);
    case "boolean": return v ? "Sim" : "Não";
    case "select": case "segmented": return option ?? String(v);
    case "tag": return field.map?.[String(v)] ?? option ?? String(v);
    case "multiselect":
      return (v as unknown[]).map((x) => field.options?.find((o) => o.value === x)?.label ?? String(x)).join(", ");
    case "tags": return (v as unknown[]).map(String).join(", ");
    case "relation": return relationName(field, values) ?? String(v);
    case "multirelation": {
      const names = values[`${field.name}_names`] ?? values[`${field.name}_detail`];
      if (Array.isArray(names)) return names.map((n) => (typeof n === "string" ? n : n?.name ?? "")).join(", ");
      return `${(v as unknown[]).length} selecionado(s)`;
    }
    case "barcodes": return (v as Row[]).map((b) => (typeof b === "string" ? b : b.code)).join(", ");
    case "richtext": return stripHtml(String(v));
    case "password": return "••••••";
    default: {
      const mask = field.mask ?? formatOf(field)?.mask;
      return mask ? applyMask(v, mask) : typeof v === "object" ? JSON.stringify(v) : String(v);
    }
  }
}

export function stripHtml(html: string) {
  return html.replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>/gi, "\n").replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").trim();
}

/** Campos compostos: as mesmas tabelas da leitura da retaguarda. */
const TABLES: Record<string, { columns: ColumnDef[]; rows: (v: Row[]) => Row[] }> = {
  "stock-items": {
    columns: [
      { key: "variant_name", label: "Produto", title: true }, { key: "sku", label: "SKU" },
      { key: "quantity", label: "Qtd.", type: "quantity" }, { key: "unit_cost", label: "Custo unit.", type: "money" },
      { key: "total_cost", label: "Total", type: "money" }, { key: "lot_number", label: "Lote" },
      { key: "expires_at", label: "Validade", type: "date" },
    ],
    rows: (v) => v,
  },
  installments: {
    columns: [
      { key: "number", label: "Parcela", title: true }, { key: "due_date", label: "Vencimento", type: "date" },
      { key: "amount", label: "Valor", type: "money" }, { key: "paid_amount", label: "Pago", type: "money" },
      { key: "paid_at", label: "Pago em", type: "date" },
      { key: "status", label: "Situação", type: "tag",
        map: { open: "Em aberto", partial: "Parcial", paid: "Pago", cancelled: "Cancelado" },
        tones: { paid: "success", partial: "warning", cancelled: "neutral", open: "info" } },
    ],
    rows: (v) => v,
  },
  variants: {
    columns: [
      { key: "label", label: "Variante", title: true }, { key: "sku", label: "SKU" }, { key: "codes", label: "Códigos" },
      { key: "price", label: "Preço", type: "money" }, { key: "promotional_price", label: "Promoção", type: "money" },
      { key: "is_active", label: "Ativa", type: "boolean" },
    ],
    rows: (v) => v.map((row) => ({
      ...row, label: (row.options ?? []).map((o: Row) => o.value).join(" / ") || "Padrão",
      codes: (row.barcodes ?? []).map((b: Row) => b.code).join(", "),
    })),
  },
  addresses: {
    columns: [
      { key: "label", label: "Endereço", title: true }, { key: "line", label: "Logradouro" },
      { key: "place", label: "Bairro / cidade" }, { key: "zip", label: "CEP" }, { key: "star", label: "Padrão" },
    ],
    rows: (v) => v.map((a) => ({
      ...a, label: a.label || "Endereço", line: [a.street, a.number, a.complement].filter(Boolean).join(", "),
      place: [a.district, [a.city, a.state].filter(Boolean).join(" - ")].filter(Boolean).join(" · "),
      zip: applyMask(a.zip_code, MASKS.cep), star: a.is_default ? "★ Padrão" : "",
    })),
  },
  "promotion-rules": {
    columns: [
      { key: "name", label: "Regra", title: true }, { key: "what", label: "Desconto" }, { key: "where", label: "Vale para" },
      { key: "is_enabled", label: "Ligada", type: "boolean" },
    ],
    rows: (v) => v.map((r) => ({
      ...r,
      what: r.kind === "percent" ? `${Number(r.value).toLocaleString("pt-BR")}%`
        : r.kind === "amount" ? `${money(r.value)} off` : `por ${money(r.value)}`,
      where: r.target === "all" ? "Tudo" : r.target === "categories" ? `${(r.categories ?? []).length} categoria(s)`
        : r.target === "brands" ? `${(r.brands ?? []).length} marca(s)`
          : (r.products ?? []).map((p: Row) => p.product_name).filter(Boolean).join(", "),
    })),
  },
  "zip-ranges": {
    columns: [
      { key: "label", label: "Faixa", title: true }, { key: "start", label: "CEP inicial" }, { key: "end", label: "CEP final" },
      { key: "value", label: "Valor", type: "money" }, { key: "days", label: "Prazo" },
    ],
    rows: (v) => v.map((r) => ({
      ...r, label: r.label || "—", start: applyMask(r.zip_start, MASKS.cep), end: applyMask(r.zip_end, MASKS.cep),
      days: r.lead_days === null || r.lead_days === undefined ? "da tabela" : `${r.lead_days} dia(s)`,
    })),
  },
  volumes: {
    columns: [
      { key: "number", label: "Caixa", title: true }, { key: "description", label: "Conteúdo" },
      { key: "size", label: "C × L × A (cm)" }, { key: "gross_weight", label: "Peso (kg)", type: "quantity" },
      { key: "barcode", label: "Código" },
    ],
    rows: (v) => v.map((row, i) => ({
      ...row, number: `Vol ${i + 1}`,
      size: [row.length_cm, row.width_cm, row.height_cm].every(Boolean)
        ? `${row.length_cm} × ${row.width_cm} × ${row.height_cm}` : "",
    })),
  },
};

/** Tipos que viram tabela (sozinhos na seção, a seção é a tabela). */
export const TABLE_TYPES = ["stock-items", "installments", "variants", "volumes", "addresses", "zip-ranges", "metafields",
                            "promotion-rules"];

export function compositeTable(field: ViewField, values: Row): { columns: ColumnDef[]; rows: Row[] } | null {
  const v = values[field.name];
  if (field.type === "metafields") {
    return {
      columns: [{ key: "key", label: "Chave", title: true }, { key: "value", label: "Valor" }],
      rows: Object.entries((v ?? {}) as Row).filter(([k]) => !k.startsWith("_")).map(([key, x]) => ({
        key, value: typeof x === "boolean" ? (x ? "Sim" : "Não") : typeof x === "object" ? JSON.stringify(x) : String(x),
      })),
    };
  }
  const spec = TABLES[field.type];
  if (!spec) return null;
  return { columns: spec.columns, rows: spec.rows(Array.isArray(v) ? v : []) };
}

/** Título do registro: nome, descrição, código... ou "Documento 12". */
export function recordTitle(values: Row, resource: { singular: string; title: string }) {
  const named = values.name ?? values.display_name ?? values.description ?? values.code ?? values.username
    ?? values.register_name ?? values.variant_name;
  if (named) return String(named);
  const s = resource.singular;
  return values.number ? `${s[0]!.toUpperCase()}${s.slice(1)} ${values.number}` : resource.title;
}

/** Coluna-título da lista: a marcada, a `name` ou a primeira. */
export function titleKeyOf(columns: ColumnDef[]) {
  return (columns.find((c) => c.title) ?? columns.find((c) => c.key === "name") ?? columns[0])?.key;
}
