/**
 * Vocabulário dos cadastros declarativos.
 *
 * Um cadastro novo = um objeto `ResourceDef` num arquivo de `resources/`.
 * As telas genéricas (lista e formulário) desenham qualquer um deles. Regra de
 * negócio NÃO mora aqui: o que é regra está no backend; aqui é só "como mostrar".
 */
import type { Component } from "vue";

export type Option = { label: string; value: string | number | boolean };

export type Relation = {
  endpoint: string;
  labelKey?: string; // padrão: "name"
  valueKey?: string; // padrão: "id"
  params?: Record<string, string>;
};

export type FieldType =
  | "text" | "textarea" | "email" | "phone" | "password" | "color"
  | "number" | "money" | "percent" | "quantity" | "measure"
  | "boolean" | "select" | "relation" | "multirelation"
  // Escolha visível de poucas opções (botões lado a lado), várias de uma lista fixa, e tags livres (Tagify).
  | "segmented" | "multiselect" | "tags"
  | "date" | "datetime" | "document" | "barcodes"
  // CEP com máscara que preenche o endereço; texto rico (editor); prévia do Google (SEO).
  | "cep" | "richtext" | "seo-preview"
  // Produto: variantes (SKU/preço/códigos), caixas da variante e eixos da grade.
  | "variants" | "volumes" | "grid"
  // Estoque: itens do documento. Financeiro: parcelas do título (com baixa).
  | "stock-items" | "installments"
  // Fotos (galeria ordenada; a 1ª é a capa).
  | "images"
  // Endereços de entrega do cliente; faixas de CEP da tabela de frete; metacampos (padrão do StarHub).
  | "addresses" | "zip-ranges" | "metafields"
  // Regras da tabela de desconto (dentro da própria tabela).
  | "promotion-rules";

export type FieldDef = {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  section?: string;
  full?: boolean;
  hint?: string;
  options?: Option[];
  relation?: Relation;
  default?: unknown;
  maxLength?: number;
  /** Mostra "45/70" enquanto digita (título e resumo do Google, por exemplo). */
  counter?: boolean;
  /** Máscara de digitação (InputMask): `9` = dígito, `?` = o resto é opcional. Ex.: NCM "9999.99.99".
   *  Documento, telefone e CEP já vêm com a máscara certa. O valor é guardado só com os dígitos. */
  mask?: string;
  placeholder?: string;
  /** Colunas que o campo ocupa na grade de 6 (padrão 2; `full` = 6). */
  span?: 1 | 2 | 3 | 4 | 6;
  /** Relação: permite criar o registro digitado sem sair do formulário. */
  creatable?: boolean;
  /** Tags: de onde vêm as sugestões (ex.: { endpoint: "/tags/", params: { scope: "product" } }). */
  tagSource?: Relation;
  /** Mostra o campo só quando a condição vale (ex.: dados de PJ). */
  visible?: (values: Record<string, unknown>) => boolean;
  /** Só na criação (ex.: senha inicial, username). */
  createOnly?: boolean;
  /** Só o suporte (superusuário) edita: para a conta aparece travado (ex.: permissões do cargo fixo). */
  readOnly?: boolean;
  /** Metacampos: de quem são as definições (Configurações → Campos personalizados). */
  owner?: "product" | "customer" | "sale";
};

export type Tone = "success" | "warning" | "danger" | "info" | "neutral" | "brand";

export type ColumnType = "text" | "money" | "quantity" | "percent" | "date" | "datetime" | "boolean" | "tag" | "image"
  | "stars";

export type ColumnDef = {
  key: string;
  label: string;
  type?: ColumnType;
  map?: Record<string, string>;
  /** Toda coluna ordena (asc/desc); `false` desliga para coluna sem ordem natural. */
  sortable?: boolean;
  /** Coluna-título da linha (em negrito). Sem marcar, vale a coluna `name` ou a primeira. */
  title?: boolean;
  /** Somar esta coluna na linha de totais da impressão (valor de venda, saldo... não preço unitário). */
  total?: boolean;
  /** Cor da etiqueta por valor (`tag`): "pendente" em amarelo, "recebida" em verde... Sem cor, a da marca. */
  tones?: Record<string, Tone>;
  /** Largura mínima na lista (ex.: "90px" para Nº); sem ela, a do tipo da coluna. */
  width?: string;
  /** No celular a lista vira cartões: `false` tira a coluna do cartão (sobra espaço para o que importa). */
  mobile?: boolean;
};

export type FilterDef = {
  name: string;
  label: string;
  /** `daterange`: vira `<name>__gte` / `<name>__lte` (ex.: vencimento entre duas datas). */
  type: "select" | "boolean" | "relation" | "daterange";
  options?: Option[];
  relation?: Relation;
};

/** Contexto que um botão do formulário recebe. */
export type FormActionContext = {
  id: string;
  values: Record<string, unknown>;
  /** Recarrega o registro (depois de confirmar, baixar, estornar...). */
  reload: () => Promise<void>;
};

type Values = Record<string, unknown>;

/**
 * Lista em árvore (TreeTable): a linha abre e mostra o que está "dentro" dela.
 *
 * - `parent`: hierarquia do PRÓPRIO cadastro (categoria › subcategoria). A lista
 *   mostra o topo; abrir a linha busca os filhos (`?parent=<id>`), em quantos
 *   níveis houver. Com busca ou filtro, a lista volta a ser plana.
 * - `children`: filhos de OUTRO tipo (variantes do produto, itens da venda),
 *   buscados ao abrir e já escritos nas colunas da lista:
 *     children: async (row) => (await api(...)).map((v) => ({ name: v.display_name, sku: v.sku }))
 */
export type TreeDef = {
  parent?: string;
  children?: (row: Values) => Promise<Values[]>;
  /** A linha tem filhos (mostra a seta)? Padrão: `children_count > 0`. */
  hasChildren?: (row: Values) => boolean;
  /** Para onde a linha filha leva ao clicar (padrão: o registro pai). */
  childLink?: (child: Values, parent: Values) => string | null | undefined;
};

/** Selo ao lado do título do registro ("Confirmado", "Conferido", "Entrada"...). */
export type DisplayBadge = { label: string; tone?: Tone; icon?: string };

/** Número de destaque no topo da visualização (Total, Itens, Diferença...). */
export type DisplayStat = {
  label: string;
  value: (v: Values) => unknown;
  type?: ColumnType;
  icon?: string;
  /** Cor do número: diferença negativa em vermelho, por exemplo. */
  tone?: (v: Values) => Tone | undefined;
  hint?: (v: Values) => string | undefined;
  /** Só aparece quando vale (ex.: "Custo total" só em entrada). */
  visible?: (v: Values) => boolean;
};

/** Tabela dentro da visualização (itens do documento, pagamentos da venda...). */
export type DisplayTable = {
  title: string;
  icon?: string;
  description?: string;
  /** Colunas fixas ou conforme o registro (inventário mostra "Sistema" e "Diferença"). */
  columns: ColumnDef[] | ((v: Values) => ColumnDef[]);
  rows: (v: Values) => Values[];
  empty?: string;
};

/** Um "rótulo: valor" da visualização. O valor vem de um campo (`key`) ou de uma conta (`value`). */
export type DisplayItem = {
  label: string;
  key?: string;
  value?: (v: Values) => unknown;
  /** Como formatar: os mesmos tipos dos campos, mais `tag` (etiqueta colorida pelo `map`/`tones`). */
  type?: FieldType | "tag";
  map?: Record<string, string>;
  tones?: Record<string, Tone>;
  /** Id de um relacionado sem `_name` no registro: busca o nome. */
  relation?: Relation;
  /** Leva ao registro relacionado (ex.: o fornecedor, a nota, o turno). */
  link?: (v: Values) => string | null | undefined | false;
  hint?: (v: Values) => string | null | undefined;
  /** Largura: metade/linha inteira da seção (padrão: uma coluna). */
  span?: "wide" | "full";
  /** Valor em destaque (o total, a diferença). */
  strong?: boolean;
  tone?: (v: Values) => Tone | undefined;
  visible?: (v: Values) => boolean;
};

/** Seção da visualização: título e explicação em cima, cartão com valores ou uma tabela embaixo. */
export type DisplaySection = {
  title: string;
  icon?: string;
  description?: string | ((v: Values) => string);
  items?: DisplayItem[];
  /** Reaproveita campos do formulário pelo nome (formatação e relação já declaradas lá). */
  fields?: string[];
  table?: Omit<DisplayTable, "title" | "icon" | "description">;
  visible?: (v: Values) => boolean;
};

/**
 * Como o registro aparece quando NÃO se edita (confirmado, só leitura, sem permissão):
 * em vez de campos desabilitados, uma página de leitura — selos ao lado do título,
 * números de destaque, seções com título e explicação (como no formulário) e, na
 * coluna da direita, o resumo. O histórico (feed) fica no fim de TODA página de
 * registro, vindo do servidor (`HistoryFeed`). Sem `display`, valem as seções do formulário.
 */
export type DisplayDef = {
  badges?: (v: Values) => (DisplayBadge | false | null | undefined)[];
  stats?: DisplayStat[];
  /** Coluna principal. Sem isto, valem as seções do formulário. */
  sections?: DisplaySection[];
  /** Coluna da direita (resumo de valores, dados de apoio). */
  aside?: DisplaySection[];
  /** Só no modo "seções do formulário": campos que já aparecem nos selos/números. */
  hide?: string[];
  /** Visualização inteira própria (props `{ ctx }`), no lugar da genérica. */
  component?: Component;
};

/** Lista de linhas de um campo do registro (itens, pagamentos...). */
export const rowsOf = (v: Values, key: string) => (Array.isArray(v[key]) ? v[key] : []) as Values[];
/** Soma de uma coluna das linhas. */
export const sumOf = (rows: Values[], key: string) => rows.reduce((total, row) => total + Number(row[key] ?? 0), 0);
/** Link para um cadastro, só quando o id existe: `linkTo("fornecedores", v.supplier)`. */
export const linkTo = (resource: string, id: unknown) => (id ? `/cadastros/${resource}/${id}` : null);

/** Botão extra no formulário: chama a API (`run`) ou abre um diálogo próprio (`dialog`). */
export type FormAction = {
  label: string;
  icon: string;
  severity?: "secondary" | "danger" | "success" | "contrast";
  /** Só aparece quando vale (ex.: "Confirmar" só em rascunho). */
  visible?: (values: Record<string, unknown>) => boolean;
  /** Código de permissão exigido (ex.: "logistics.manage"): sem ele a ação nem aparece. */
  permission?: string;
  confirm?: string;
  success?: string;
  run?: (ctx: FormActionContext) => Promise<unknown>;
  /** Componente com props `{ ctx }` aberto num diálogo; emite `done` ao terminar. */
  dialog?: Component;
};

export type SectionDef = { description?: string; icon?: string };

type Row = Record<string, unknown>;

/** Lista de outro cadastro filtrada por este registro (ex.: kardex do produto). */
export type ListViewDef = {
  endpoint: string;
  /** Filtros da lista a partir do registro aberto: (id) => ({ variant__product: id }). */
  params: (id: string, values: Row) => Record<string, string>;
  columns: ColumnDef[];
  ordering?: string;
  rowLink?: (row: Row) => string;
  searchable?: boolean;
};

/**
 * Consulta do registro: vira aba no formulário, item no menu "⋯" da lista e página
 * própria em `/cadastros/<cadastro>/<id>/<name>`. É uma lista declarada (`list`)
 * ou um componente com props `{ id, values }` (extrato do caixa, da conta...).
 */
export type DetailView = {
  name: string;
  label: string;
  icon: string;
  description?: string;
  permission?: string;
  module?: string;
  list?: ListViewDef;
  component?: Component;
};

/** Ação extra no menu "⋯" da linha: abre uma página (`to`) ou chama a API (`run`). */
export type RowAction = {
  label: string;
  icon: string;
  to?: (row: Row) => string;
  run?: (row: Row) => Promise<unknown>;
  confirm?: string;
  success?: string;
  danger?: boolean;
  permission?: string;
  visible?: (row: Row) => boolean;
};

export type ResourceDef = {
  /** Slug da rota: /cadastros/<name>. */
  name: string;
  title: string;
  singular: string;
  endpoint: string;
  /** Área de permissão do backend: lista exige `<area>.view`, gravar `<area>.manage`. */
  permission: string;
  module?: string;
  icon: string;
  group: string;
  columns: ColumnDef[];
  fields: FieldDef[];
  /** Texto de apoio de cada seção do formulário (coluna da esquerda). */
  sections?: Record<string, SectionDef>;
  filters?: FilterDef[];
  searchable?: boolean;
  ordering?: string;
  readOnly?: boolean;
  deletable?: boolean;
  /** "Nova conta", "Nova loja" (o padrão é "Novo <singular>"). */
  feminine?: boolean;
  /** `false`: a lista não tem "Novo" (registro nasce em outro lugar: saldo, movimento, turno). */
  creatable?: boolean;
  /** `false`: registro salvo não se edita (lançamento financeiro se corrige com estorno). */
  editable?: boolean;
  /** Trava o formulário conforme o estado (ex.: documento confirmado não se edita mais). */
  lockedWhen?: (values: Record<string, unknown>) => boolean;
  /** Parâmetros fixos da lista e valores fixos do cadastro (ex.: { kind: "payable" }). */
  params?: Record<string, string>;
  /** Para onde a linha leva (padrão: o formulário do próprio cadastro). */
  rowLink?: (row: Record<string, unknown>) => string;
  /** Botões extras no formulário (confirmar, cancelar, imprimir...). */
  formActions?: FormAction[];
  /** Consultas do registro (movimentos, vendas, extrato...). */
  views?: DetailView[];
  /** Ações extras do menu "⋯" da linha. */
  rowActions?: RowAction[];
  /** Botões no topo da lista (ex.: "Buscar na SEFAZ", "Importar XML"): mesmo formato
   *  das ações do formulário, com `ctx.id` vazio e `reload` recarregando a lista. */
  listActions?: FormAction[];
  /** Painel do registro, acima dos campos e fora do formulário (props `{ ctx }`):
   *  para telas com interação própria, como o vínculo dos itens da NF-e. */
  summary?: Component;
  /** Visualização de leitura (ver `DisplayDef`). */
  display?: DisplayDef;
  /** Lista em árvore (ver `TreeDef`). */
  tree?: TreeDef;
  /** Cadastro FIXO do sistema (formas de pagamento, perfis fiscais): nasce com a conta; a loja
   *  ajusta, mas só o superusuário cria ou exclui (no admin). */
  systemData?: boolean;
  /** Texto do aviso de cadastro fixo (o que a conta pode ajustar neste). */
  systemNote?: string;
};

/** "Novo produto" / "Nova conta a pagar". */
export const newLabel = (r: ResourceDef) => `${r.feminine ? "Nova" : "Novo"} ${r.singular}`;

export const defineResource = (def: ResourceDef) => def;

export const yesNo: Option[] = [
  { label: "Sim", value: true },
  { label: "Não", value: false },
];

/** Converte TextChoices do backend ({valor: rótulo}) em opções e mapa de rótulos. */
export function choices(map: Record<string, string>): { options: Option[]; map: Record<string, string> } {
  return { options: Object.entries(map).map(([value, label]) => ({ value, label })), map };
}

/** Unidades da federação (filtro de loja, endereço). */
export const UFS: Option[] = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
  "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"].map((uf) => ({ label: uf, value: uf }));
