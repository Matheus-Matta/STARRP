# Frontend (retaguarda web + PDV web)

Vue 3 + **TypeScript** + PrimeVue 4 + Pinia + TanStack Query + Zod, com Vite.

## Por que esta stack

| Escolha | Motivo |
| --- | --- |
| Vue 3 (mantido) | o time já conhece; trocar para React custaria reaprender sem ganho para um ERP |
| **TypeScript + tipos gerados do OpenAPI** | o backend muda um campo → o front **não compila** até ser ajustado. No StarChef (JS puro) nada avisava |
| PrimeVue 4 | componentes de tabela/formulário prontos; tema por *tokens* (cores num arquivo só) |
| TanStack Query | cache e recarga dos dados da API, com a loja ativa na chave (trocar de loja recarrega sozinho) |
| Zod | validação dos formulários gerada da própria descrição do cadastro |

## Estrutura (por tipo, como o backend)

```
frontend/src/
├── api/          cliente HTTP, erros, tipos gerados (schema.d.ts) e 1 módulo por domínio
├── resources/    DESCRIÇÃO de cada cadastro (colunas, filtros, campos) — 1 arquivo por domínio
├── components/
│   ├── resource/ tabela e formulário genéricos (CellValue, FormField, RelationSelect, BarcodeListField)
│   ├── layout/   menu lateral, barra superior (seletor de loja), navegação por permissão
│   ├── pdv/      carrinho, totais, pagamento, caixa
│   └── common/   autorização de gerente, pergunta rápida
├── pages/        telas: login, painel, lista, formulário, PDV
├── composables/  lógica reutilizável: useResourceList, useResourceForm, usePdv, useApproval, useNotify
├── stores/       sessão (usuário, conta, lojas, loja ativa)
├── router/       rotas + guarda de login/permissão
├── utils/        formatação pt-BR, CPF/CNPJ, validação
├── styles/       tema (cores), CSS base, tradução do PrimeVue
└── tests/
```

No StarChef, poucas telas gigantes desenhavam tudo (`ResourceListViewPro.vue` com
6.985 linhas). Aqui o maior arquivo tem ~180 linhas.

## Criar um cadastro novo (exemplo)

Um objeto num arquivo de `resources/` e uma linha em `resources/index.ts`. Menu,
rotas, lista, formulário, validação e permissão saem sozinhos.

```ts
export const brands = defineResource({
  name: "marcas", title: "Marcas", singular: "marca",
  endpoint: "/catalog/brands/", permission: "catalog", icon: "pi pi-tag", group: "Catálogo",
  columns: [{ key: "name", label: "Nome" }],
  fields: [{ name: "name", label: "Nome", type: "text", required: true }],
});
```

## Loja ativa e isolamento

- O seletor no topo grava a loja ativa; toda chamada leva `X-Store-ID`.
- "Todas as minhas lojas" envia `X-Store-ID: *` (visão consolidada das lojas permitidas).
- O PDV exige uma loja concreta.
- O front só **esconde** o que o cargo não pode; quem **barra** é o backend.

## Autorização de gerente

Qualquer ação pode ser envolvida em `withApproval`. Se o backend responder
`*approval_required`, abre o diálogo, pede usuário/senha do gerente (ou a senha
do caixa) e repete a mesma chamada:

```ts
await withApproval((approval) => salesApi.discount(id, { percent: "10", approval }));
```

## PDV web

Tela cheia em `/pdv`: leitor de código (aceita `3*789...` para 3 unidades),
carrinho com quantidade editável, CPF na nota, vendedor, desconto (F6), cupom
(F7), pagamento dividido em várias formas com troco (F10), abrir/fechar caixa,
sangria e suprimento. A venda aberta sobrevive a recarregar a página (e, com a aba
fechada, volta pelo `GET /sales/?status=open&created_by=<eu>`), e o checkout usa
chave de idempotência: clicar de novo após queda de rede não cobra duas vezes.

- **Catálogo** (`usePdvCatalog` + `PdvCatalog`): 20 produtos por página, mais ao rolar
  (observador no fim da grade + `watch` que continua pedindo enquanto o fim estiver à
  vista), busca no servidor com 250 ms de espera e chips de categoria em dois níveis
  (a categoria traz as de dentro). Sem foto, o cartão mostra as iniciais num quadrado
  de 76 px na cor do tema (`--brand-subtle`). Variações só são buscadas no clique.
- **Sem janelas por cima**: Pedidos (F2), Cliente (F3) e Caixa (F4) trocam a área
  principal (`PdvOrders`, `PdvCustomers`, `PdvCashPanel`) e usam o mesmo
  `EmbeddedList` das telas (`pick` + `compact`). Só pagamento, variação e valores de
  caixa continuam em diálogo.
- **Modos** (`boot.mode`, pela permissão `cash.manage`): vendedor e caixa entram
  direto no PDV (`session.pdvFirst` no roteador). Vendedor não vê caixa nem cobra —
  "Enviar ao caixa" (F10) guarda o pedido; o caixa retoma em Pedidos → Guardados.
- **Guardar pedido** (F9): `POST /sales/{id}/park/` → status `draft`. Pedido vazio ou já
  com pagamento não é guardado. Retomar com uma venda pela metade guarda ela antes.
- **Bloqueio** (só caixa): F12, cadeado na barra ou sozinho após
  `store.settings.pdv_lock_minutes` (padrão 5) parado. Volta com a senha do operador
  ou a senha de ações do caixa (`POST /pdv/unlock/`); recarregar não desbloqueia.
- **Vitrine do produto** (`PdvProductDialog`, `GET /pdv/products/{id}/`): modal grande no formato
  de página de produto — galeria (fotos do produto + da variante escolhida), preço com o "de",
  saldo, um botão por valor de cada eixo (combinação inexistente esmaecida, sem saldo
  tracejada), quantidade (kg na balança), serviços para marcar e abas Detalhes / Ficha
  técnica / Serviços. Abre no clique do cartão quando o produto tem grade, balança ou
  serviço; produto simples sem serviço entra direto. O olho no cartão abre sempre. Enter
  adiciona de qualquer lugar (o foco sai da busca do catálogo ao abrir).
- **Serviços no pedido**: aparecem logo abaixo do item, recuados e com a chave inglesa.
  Remover o item remove os serviços (o motivo avisa); mudar a quantidade do item muda a deles.
- **Entrega** (F11 ou a linha "Retirada/Entrega" no pedido → `PdvDelivery`): escolhe o endereço
  do cliente (ou cadastra um novo, que fica no cliente) e uma das cotações de todas as tabelas de
  frete ativas para o CEP; as que não atendem dizem por quê. O frete aparece nos totais.
- **Ficha técnica**: a aba da vitrine mostra primeiro os campos personalizados do produto.
- **Motivos fixos** (`utils/reasons.ts` + `PromptDialog` com `options`): cancelar venda,
  remover item e guardar pedido são um toque num botão; "Outro motivo" abre o campo.
- **Pagamento**: cartão/PIX exigem NSU/autorização (o backend recusa sem, código
  `reference_required`); crediário/vale-troca ficam travados sem cliente; atalhos de
  valor recebido (exato, próxima nota de 5/10/20/50/100) no dinheiro.

## Design e tema (claro / escuro)

Inspirado no sistema de design do StarChef, com a identidade do Starrp.

- **Tokens semânticos** em `src/styles/tokens.css`: `--surface-*`, `--text-*`,
  `--border*`, `--brand*`, `--success/warning/danger/info`, sombras, raios e
  movimento — cada um com valor no tema claro (ardósia) e no escuro (zinco).
  Componente usa SÓ os semânticos; cor fixa no componente quebra o modo escuro.
- **Tema**: `useTheme()` alterna claro/escuro/automático (segue o sistema),
  grava a escolha e marca o `<html>` com `data-theme` (nossos tokens) e a classe
  `.dark` (PrimeVue). Um script no `index.html` aplica o tema antes de pintar,
  para a tela não piscar clara no modo escuro.
- **PrimeVue** usa o mesmo preset (`src/styles/theme.ts`) nas duas versões e
  fica numa camada CSS abaixo dos nossos estilos; ajustes finos em
  `src/styles/primevue.css`, sem `!important`.
- **Interação**: hover com fundo e borda (transições de 120–180 ms), anel de
  foco visível no teclado, botão "afunda" ao clicar, cartões clicáveis sobem
  1 px, entrada das páginas com fade. Quem pede menos movimento no sistema
  (`prefers-reduced-motion`) não recebe animação.
- **Peças comuns** (`components/common/`): `PageHeader`, `SectionCard`,
  `StatCard`, `EmptyState`, `BarChart`, `RankList`.
- **Cores da marca**: escala `--brand-50…950` escolhida por `data-brand` no <html>. Azul é o padrão
  (o mais comum em ERP); índigo, violeta e verde-petróleo são alternativas. Cada usuário troca em
  *menu do usuário → Cor do sistema*. O PrimeVue lê a mesma escala (`theme.ts`), então tudo muda junto.
  Nova paleta = um bloco `[data-brand="..."]` em `tokens.css` + uma linha em `BRANDS` (`useTheme.ts`).
  Âmbar continua como destaque de promoção; verde/vermelho só para sucesso/erro.

Verificação visual: capturas automáticas das telas nos dois temas (Edge
headless via `puppeteer-core`) — login, painel, lista com hover, formulário,
PDV com carrinho e pagamento, menu recolhido e celular.

## Layout e velocidade (inspirado no PrimeBlocks)

- **Celular (até 640px, `composables/useViewport`):**
  - listas viram cartões (`components/list/MobileCards`): título, etiquetas e até 6 campos;
    tocar abre, segurar marca para as ações em massa; `mobile: false` na coluna tira do cartão;
  - filtros atrás do botão "Filtros (n)" e paginação só com anterior/próxima;
  - cabeçalho do registro: ações numa linha que rola para o lado; trilha mostra só a página;
  - tabelas de leitura (`ViewTable`) viram blocos "rótulo  valor"; itens de entrada/saída e da
    NF-e viram cartões com rótulos; `segmented` com mais de 3 opções vira lista de seleção;
  - tabelas pequenas escondem colunas com `hide-sm-N` (base.css); diálogos quase tela cheia e
    campos com 16px (o iPhone não dá zoom); grades usam `minmax(min(Npx, 100%), 1fr)`.

- **Casca:** menu lateral escuro e compacto nos dois temas (diferente do StarChef),
  usuário no rodapé do menu e barra superior fina.
- **Busca rápida (`Ctrl+K`):** vai para qualquer tela, cria um cadastro
  ("nov prod" → Novo produto) ou abre um produto/cliente pelo nome ou código.
- **Pré-carregamento:** passar o mouse num item do menu baixa a tela e a 1ª
  página da lista; passar o mouse numa linha baixa o registro. Ao clicar, a tela
  abre sem esperar. O código das telas principais baixa quando o navegador fica ocioso.
- **Skeletons no formato real:** a lista mostra a tabela com as colunas de
  verdade; o formulário mostra as seções e campos. Recarregar com dados na tela
  só esmaece a tabela (sem spinner).
- **Atalhos:** `/` busca na lista, `N` novo registro, `Ctrl+S` salva,
  `Ctrl+Enter` salva e abre outro, `Esc` volta para a lista.

### Listas

- Toda coluna ordena (A→Z, Z→A, padrão); `sortable: false` desliga.
- Checkbox no cabeçalho em ciclo: 1º clique marca a página, 2º marca **todos** os registros
  da lista (com os filtros da tela), 3º desmarca. Com itens marcados, a barra de filtros vira
  a barra de ações (as que o backend libera para o cargo), e exportar baixa um CSV com as
  colunas da tela.
- Paginação separada (`Paginator`, 10/20/30), tabela ocupando a altura da tela.

### Estoque e financeiro

- **Painel de estoque** (`/estoque`): abaixo do mínimo, lotes vencendo, rascunhos e atalhos
  (entrada, saída, transferência, inventário).
- **Documentos de estoque**: itens por leitura de código (ou volume/SKU), custo na entrada,
  lote/validade e endereços opcionais. Botões: Confirmar, Separação (onde pegar + carga),
  Conferência por leitura, Etiquetas e Cancelar. Confirmado fica travado (`lockedWhen`).
- **Saldos** levam ao kardex já filtrado; **Lotes**, **Endereços**, **Modelos de etiqueta**,
  **Configurações**.
- **Painel financeiro** (`/financeiro`): saldo por conta (com transferência), vencimentos por
  faixa, fluxo de caixa e DRE do período.
- **Contas a receber/pagar** com parcelas e baixa na linha; **Vencimentos**; **Lançamentos**
  (só criação, correção por estorno); **Categorias**; **Turnos de caixa** com o fechamento.

Recursos genéricos que isso trouxe ao `ResourceDef`: `params` (lista e cadastro fixos, ex.
`{ kind: "payable" }`), `rowLink`, `creatable`/`editable`/`lockedWhen`, `formActions`
(botão que chama a API ou abre um diálogo), filtro `daterange` e filtros vindos da URL
(`?variant=<id>`), além de valores iniciais pela URL no cadastro novo (`/novo?kind=exit`).

### Consultas do registro (abas, menu ⋯ e páginas próprias)

Cada cadastro declara `views` (consultas) e `rowActions`. Uma consulta vira, ao mesmo tempo:
uma **aba** no formulário, um item do **menu "⋯"** da linha na lista e uma **página própria**
em `/cadastros/<cadastro>/<id>/<consulta>` (dá para abrir em outra aba ou mandar o link).

- `list`: lista de outro cadastro filtrada pelo registro, com ordenação, busca, paginação e
  exportação CSV (ex.: `{ endpoint: "/stock/movements/", params: (id) => ({ variant__product: id }) }`).
- `component`: tela própria com props `{ id, values }` (extrato do turno, extrato da conta).

Hoje: produto (estoque, movimentações, vendas, lotes), cliente (compras, itens comprados,
vale-troca, a receber), fornecedor (entradas, a pagar), depósito (saldos, movimentações,
endereços), conta financeira (extrato, lançamentos), turno de caixa (extrato completo, vendas,
gaveta), caixa (turnos), documento de estoque (movimentos gerados), categoria e marca
(produtos) e a nova tela **Vendas** (com os itens de cada venda).

### Campos com editor e máscara

- `type: "richtext"` — editor (PrimeVue Editor/Quill) com títulos, negrito, listas e link.
  O HTML é limpo NO SERVIDOR antes de salvar (`core/text.clean_html`, com `nh3`): script,
  `onclick` e `javascript:` somem. Usado na descrição de produto e de categoria.
- SEO (produto e categoria): `slug` (gerado pelo nome, sem repetir), `seo_title` (70) e
  `seo_description` (160) com contador (`counter: true`) e `type: "seo-preview"`, que mostra
  como fica no Google.
- Máscaras (InputMask, guarda só os dígitos; `utils/masks.ts`):
  - `document`: CPF ou CNPJ conforme o tipo de pessoa;
  - `phone`: fixo, e vira celular no 11º dígito;
  - `cep`: ao completar, busca o endereço no ViaCEP e preenche rua, bairro, cidade, UF e IBGE;
  - qualquer campo: `mask: "9999.99.99"` (NCM, CEST, IBGE...).

### Sair com alterações e rascunhos

- Sair do formulário (voltar, Esc, menu, outro registro) com alterações abre um diálogo:
  **Continuar editando**, **Descartar** ou **Guardar rascunho**. A barra de salvar também tem
  "Guardar rascunho".
- O rascunho fica NESTE navegador (`utils/drafts.ts`, por conta + usuário + cadastro +
  registro); fechar ou recarregar a aba no meio da edição guarda sozinho.
- Ao abrir o registro de novo aparece "Você tem um rascunho… — Continuar de onde parei /
  Descartar"; a lista do cadastro mostra "N rascunhos" para abrir cada um. Salvar apaga o rascunho.

### Fotos do produto e da variante

- `type: "images"` (`components/resource/ImageGallery.vue`): arraste arquivos ou clique; arraste
  as fotos para reordenar — a 1ª é a CAPA. O envio vai na hora para `/catalog/images/` (o
  servidor confere que é imagem, reduz acima de 2000 px e reaproveita o mesmo arquivo); o
  vínculo com o produto é gravado no Salvar, como no StarHub (`services/media.py`).
- Produto: seção "Imagens". Variante (com grade): "Fotos desta variação" nos detalhes da linha.
- A capa aparece na lista de produtos (coluna `type: "image"`) e no PDV; a variante usa a
  foto dela quando tem.
- Seção que é só um editor de texto vira o próprio cartão (sem caixa dentro de caixa).

### Listas em árvore (TreeTable)

Linha que tem "coisas dentro" abre na própria lista (`tree` no `ResourceDef`):

- **Hierarquia do próprio cadastro** — `tree: { parent: "parent" }`: categorias,
  depósitos e categorias financeiras. A lista mostra só o topo (`?root=1`); abrir a linha
  busca os filhos (`?parent=<id>`), em quantos níveis houver. Com busca ou filtro a lista
  fica plana. No backend basta `tree_parent = "parent"` na view (devolve `children_count`).
- **Filhos de outro tipo** — `tree: { children: async (row) => [...] }`, já escritos nas
  colunas da lista: produto → variantes (SKU, variação, preço), venda → itens, documento de
  estoque → itens, conta a pagar/receber → parcelas, nota de entrada / nota emitida → itens.
- Filhos são buscados na 1ª vez que a linha abre; linha filha não tem caixa de marcar nem "⋯"
  e, clicada, abre o registro pai (ou `childLink`).

### Visualização (registro que não se edita)

Documento confirmado, venda, lançamento, turno de caixa, nota emitida, movimento, ou
qualquer cadastro aberto por quem não tem permissão de editar: em vez de campos
desabilitados, a página vira LEITURA (`components/resource/RecordView.vue`), com o mesmo
cuidado do formulário:

```
 selos ao lado do título: Entrada · Confirmado · Conferido · NF-e 1236
 [Itens 2] [Quantidade 24] [Custo total R$ 52,80] [Diferença -10]   ← números de destaque
 Movimento  (título + explicação)            │ Resumo      (rótulo ... valor)
 ┌ Tipo · Depósito ↗ · Data ┐                │ Histórico   ● Criado · admin
 Origem: Fornecedor ↗ · Nota · NF-e ↗        │             ● Conferido · ● Confirmado
 Itens (tabela na largura toda, com total; coluna vazia some)
```

Cada cadastro descreve a sua página no `display` do `ResourceDef`:

```ts
display: {
  badges: (v) => [{ label: "Confirmado", tone: "success" }, v.checked_at && { label: "Conferido", tone: "info" }],
  stats: [{ label: "Total", type: "money", value: (v) => v.total }],
  sections: [
    { title: "Origem", icon: "pi pi-truck", description: "De quem veio a mercadoria.", items: [
      { label: "Fornecedor", key: "supplier_name", link: (v) => linkTo("fornecedores", v.supplier) },
    ] },
    { title: "Itens", table: { columns: [...], rows: (v) => rowsOf(v, "items") } },
  ],
  aside: [{ title: "Resumo", items: [{ label: "Total", key: "total", type: "money", strong: true }] }],
}
```

- Sem `sections`, as seções do formulário viram a página.
- **Histórico** (`components/view/HistoryFeed.vue`): no fim de TODA página de registro já
  salvo (formulário ou leitura), na largura toda, com o Timeline do PrimeVue. Vem de
  `GET <cadastro>/<id>/history/` (paginado, 10 por vez): a auditoria (criado, alterado com
  "campo: antes → depois", excluído) mais as etapas que o próprio registro guarda
  (`posted_at` → "Confirmado", `checked_at` → "Conferido"...). O quadro tem rolagem
  própria e busca a próxima página quando ela chega ao fim.
- `display.component` troca a página inteira por uma própria.

### Notas de entrada e dados fiscais

- **Fiscal → Dados fiscais**: o emitente (CNPJ, certificado A1, CSC) e as lojas vinculadas.
  Botões: "Certificado A1" (envia o .pfx com a senha), "Buscar notas agora" e, na lista,
  "Criar a partir das lojas". Abas: notas de entrada e notas emitidas daquele CNPJ.
- **Estoque → Notas de entrada**: "Buscar na SEFAZ" e "Importar XML" no topo da lista. A
  nota abre num painel (`components/fiscal/NfeDetail.vue`) com as etapas, o próximo passo
  e a tabela de itens para vincular cada um a um produto (ou cadastrar a partir do item).
- **Documento de estoque da nota**: "Conferência" (leitor) → "Concluir conferência" →
  "Aprovar entrada". Sem leitor: "Conferido (digitado)" usa as quantidades dos itens.
- Peças genéricas novas do `ResourceDef`: `listActions` (botões do topo da lista, mesmo
  formato das `formActions`), `summary` (painel livre no registro, fora do formulário) e
  `tones` na coluna `tag` (cor por valor: pendente amarelo, recebida verde...).

### Formulário em duas colunas

À esquerda o nome e a explicação da seção (`sections` no `ResourceDef`); à direita
os campos numa grade de 6 colunas (`span` no campo: 1, 2, 3, 4 ou 6). Campos práticos:

| Tipo | Para quê | Exemplo |
| --- | --- | --- |
| `segmented` | poucas opções sempre visíveis | Tipo do produto, Pessoa física/jurídica |
| `multiselect` | várias de uma lista fixa | — |
| `tags` | etiquetas livres (estilo Tagify), Enter/vírgula, colar "a, b, c", sugestões | Tags do produto e do cliente |
| `relation` + `creatable` | escolhe ou cria na hora ("Criar “Bebidas”") | Categoria, marca, grupos de cliente |

## Impressão e PDF

Cada documento tem uma página própria em `/imprimir/<doc>/<id>`, fora do layout do
sistema (sem menu), feita para papel. O PDF sai pelo diálogo do navegador
("Salvar como PDF"), e o nome do arquivo já vem preenchido pelo `document.title`.

| doc | o que imprime | formatos |
| --- | --- | --- |
| `venda` | recibo da venda ("sem valor fiscal") | 80mm, A4 |
| `turno` | fechamento do caixa (Z): resumo, vendas, itens, ocorrências | A4, 80mm |
| `estoque` | documento de estoque com itens e assinaturas | A4 |
| `separacao` | lista de separação com ☐, faltas e carga | A4 |
| `titulo` | conta a pagar/receber com parcelas | A4 |
| `conta` | extrato da conta financeira (`?de=&ate=`) | A4 |
| `dre` | DRE do período | A4 |
| `lista` | qualquer lista ou consulta (`/imprimir/lista/<cadastro>?view=&registro=&filtros`) | A4, A4 deitado |

- `PrintShell` monta o papel: `@page` por formato, "Página X de Y" no rodapé (exceto na
  bobina), cabeçalho com os dados da loja e "Emitido em … por …".
- `?formato=80mm` escolhe o formato e `?auto=1` abre a impressão sozinho (o PDV usa
  isso no recibo, F9 após concluir a venda).
- Sem `?formato=`: o último papel escolhido para aquele documento neste navegador
  (`print/format.ts`, localStorage) e, na primeira vez, **A4** — inclusive no recibo do PDV.
  O caixa que troca para "Bobina 80 mm" uma vez fica nela.
- A barra e o fundo seguem o tema (claro/escuro); a folha é sempre papel branco.
- PDV → Pedidos: clicar num pedido abre a página dele ali mesmo (`PdvOrderView`, o mesmo
  `RecordView` da retaguarda), com "Retomar" (guardado) ou "Imprimir" (concluído).
- Para abrir de qualquer tela: `openPrint("titulo", id)` (`src/utils/print.ts`), que
  abre em outra aba.
- Na impressão de listas só somam as colunas com `total: true` no `ColumnDef`
  (valor, saldo, quantidade), nunca o preço unitário.
- Documento novo: crie `src/print/docs/XPrint.vue` usando `PrintShell`, `PrintMeta` e
  `PrintTable`, e registre-o no mapa `DOCS` de `src/pages/PrintPage.vue`.

## Comandos

Da raiz do projeto: `npm run dev` (sobe junto com o backend), `npm run test`,
`npm run lint`, `npm run build` e `npm run api:types` (regera
`src/api/schema.d.ts` a partir do backend). Dentro de `frontend/` os scripts
próprios (`npm run dev`, `typecheck`, `test`) também funcionam isolados.

O `.env` é o da raiz: o Vite lê dele `VITE_API_TARGET` (destino do proxy `/api`).

## Campos de lista e metacampos

- `type: "addresses"` (`AddressListField`): endereços em cartões, CEP que preenche o resto,
  referência para o entregador e o padrão (★).
- `type: "zip-ranges"` (`ZipRangesField`): faixas de CEP da tabela de frete.
- `type: "metafields"` + `owner` (`MetafieldsField`): os campos personalizados da conta para
  aquele cadastro (no produto, só os da categoria dele e das de cima), com o tipo certo, e
  embaixo chave/valor livres. Chaves `_...` são do sistema: guardadas, não mostradas.
- Configurações → **Tabelas de frete** e **Campos personalizados** são os cadastros que alimentam
  a entrega e a ficha técnica.
