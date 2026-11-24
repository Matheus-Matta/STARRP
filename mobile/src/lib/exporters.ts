/**
 * O que cada tela oferece em "Exportar ou compartilhar" — o mesmo que a retaguarda tem no computador:
 *  - relatório: PDF / imprimir (o documento `relatorio` da retaguarda), Excel e CSV (gerados pelo backend);
 *  - lista de qualquer cadastro: PDF / imprimir (o documento `lista`, com os filtros da tela) e CSV (todos os registros);
 *  - registro: o documento do cadastro na retaguarda (venda, título, turno, lançamento, DANFE) ou a ficha do registro.
 * PDF e impressão abrem o painel de impressão (`PrintHost`), que usa os modelos copiados da retaguarda (`src/print`).
 */
import type { Me, ReportBook } from "@/api/types";
import type { ExportOption } from "@/components/Filters";
import { fileName, shareDownload } from "@/lib/share";
import { openPrint } from "@/print/bus";
import type { ResourceDef } from "@/shared/types";

type Row = Record<string, unknown>;
type Params = Record<string, string | number | boolean | null | undefined>;

/** Título e subtítulo da tela (usados no nome dos arquivos). */
export type DocMeta = { title: string; subtitle?: string };
export function docMeta(_me: Me | null, _storeName: string, title: string, subtitle?: string): DocMeta {
  return { title, subtitle };
}

const asQuery = (params: Params) => Object.fromEntries(Object.entries(params)
  .filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));

const printOption = (run: () => void, hint = "O documento da retaguarda: escolha o papel e compartilhe ou imprima"): ExportOption => ({
  key: "pdf", label: "PDF ou imprimir", hint, icon: "printer", run: async () => run(),
});

export function reportExports(slug: string, params: Params, _data: ReportBook | null, meta: DocMeta): ExportOption[] {
  const name = `${meta.title} ${meta.subtitle ?? ""}`;
  return [
    printOption(() => openPrint("relatorio", slug, asQuery(params)), "Folha do relatório (A4), com gráficos e tabelas completas"),
    { key: "xlsx", label: "Excel", hint: "Planilha com o resumo e uma aba para cada gráfico e tabela", icon: "grid",
      run: () => shareDownload("GET", `/reports/book/${slug}/export/`, { params: { ...params, formato: "xlsx" } },
                               fileName(name, "xlsx"), meta.title) },
    { key: "csv", label: "CSV", hint: "A tabela principal do relatório", icon: "file",
      run: () => shareDownload("GET", `/reports/book/${slug}/export/`, { params: { ...params, formato: "csv" } },
                               fileName(name, "csv"), meta.title) },
  ];
}

export function listExports(resource: ResourceDef, params: Params, _filterText: string, _meta: DocMeta): ExportOption[] {
  const { page: _p, page_size: _s, ...filters } = params;
  return [
    printOption(() => openPrint("lista", resource.name, asQuery(filters)), "A lista com as colunas e os filtros da tela (até 2.000 linhas)"),
    { key: "csv", label: "CSV", hint: "Todos os registros com os filtros da tela (abre no Excel)", icon: "file",
      run: () => shareDownload("POST", `${resource.endpoint}bulk/`, {
        params: filters,
        body: { action: "export", all: true,
                params: { columns: resource.columns.map((c) => ({ key: c.key, label: c.label, map: c.map })) } },
      }, fileName(resource.title, "csv"), resource.title) },
  ];
}

/** Documento próprio da retaguarda para o registro (o mesmo do botão "Imprimir" do cadastro). */
function documentOf(resource: ResourceDef, values: Row): [string, string, Record<string, string>] | null {
  const id = String(values.id ?? "");
  if (resource.endpoint === "/sales/") return ["venda", id, {}];
  if (resource.endpoint === "/stock/documents/") return ["estoque", id, {}];
  if (resource.endpoint === "/finance/titles/") return ["titulo", id, {}];
  if (resource.endpoint === "/cash/sessions/") return ["turno", id, { formato: "a4" }];
  if (resource.endpoint === "/fiscal/invoices/") return ["danfe", id, { formato: values.document_model === "65" ? "80mm" : "a4" }];
  return null;
}

export function recordExports(resource: ResourceDef, values: Row, _meta: DocMeta): ExportOption[] {
  const own = documentOf(resource, values);
  return [own
    ? printOption(() => openPrint(own[0], own[1], own[2]))
    : printOption(() => openPrint("registro", String(values.id ?? ""), { cadastro: resource.name }),
                  "A ficha do registro, no papel da retaguarda")];
}
