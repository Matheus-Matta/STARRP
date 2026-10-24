# Melhorias: StarChef → Starrp

Tudo o que mudou ao reconstruir o backend do StarChef (restaurante) como Starrp (varejo). O detalhe de cada
inconsistência está em [ANALISE_STARCHEF.md](ANALISE_STARCHEF.md).

## 1. Organização do código

- **Um app Django só (`starrp`)** no lugar de 22 apps que importavam uns dos
  outros em círculo. As migrations não dependem mais umas das outras entre apps.
- **Pastas separadas por tipo de arquivo (MVC):** `models/`, `serializers/`,
  `views/`, `services/` e `urls/`. Dentro de cada pasta há um arquivo por assunto.
- **Regra de negócio só em `services/`.** Antes ela ficava espalhada entre views,
  serializers, signals e models.
- **Rotas organizadas por domínio,** com prefixos coerentes. Exemplo:
  `/cash-register/`, `/cash-stations/` e `/cash-discrepancy-report/` viraram
  `/cash/sessions/`, `/cash/registers/` e `/cash/discrepancies/`.
- **Admin com registro automático** de todas as models. Antes eram cerca de 20
  arquivos `admin.py` repetidos.
- **Arquivos com no máximo ~200 linhas,** quebrados por assunto.
- **Nomes padronizados:** identificadores em inglês, textos para o usuário em
  português. Os status usam `TextChoices` em vez de constante + lista repetida.

## 2. Models sem redundância

| StarChef | Starrp |
| --- | --- |
| `Restaurant` + `Branch` com campos espelhados | `Store` (a loja é o emitente fiscal) |
| Dados do emitente copiados no `FiscalConfig` | lidos da `Store` |
| Plano e status da assinatura em `Account` **e** em `Subscription` | só em `Subscription` |
| `Account.status` + `Account.is_active` | só `status` |
| Uma tabela por integração (`FocusNfeConfig`, `CosmosConfig`) | `Integration` |
| `GlobalSystemConfig` + `DFeGlobalConfig` | `SystemSetting` |
| Dois mecanismos de exclusão lógica | só `deleted_at` |
| 10 models sobrescrevendo o FK herdado `restaurant` | `StoreModel` ou `optional_store_fk()` explícito |
| `Product` + `Ingredient` paralelos | `Product` (cabeçalho) + `ProductVariant` (o que vende e estoca) |
| 4 classificações de produto sobrepostas | `type` (como se monta) + `purpose` (SPED) + `sale_method` + `category` + `brand` |
| `image` + `logo_image` + `ProductImage` | `Image` + `ProductImage` |
| `ean` + `gtin` | `ProductBarcode` (vários códigos por variante) |
| Margem e custo estimado gravados | custo médio e último custo; margem calculada no relatório |
| NCM no perfil fiscal | NCM/CEST/origem no produto |
| `ProductUnitConversion` + `SupplierItemMapping` | `SupplierProduct` |
| `StockLot` × `InventoryLot` | só `StockLot` |
| `StockEntry`/`StockExit` × `GoodsReceipt` | só `StockDocument` |
| Movimento de estoque com `product` **e** `ingredient`, mais tipos "legado" | só `variant`, quantidade com sinal e saldo após cada movimento (kardex) |
| `CashStation` (o caixa) × `CashRegister` (que era a sessão) | `CashRegister` (o caixa) + `CashSession` (o turno) |
| Três jeitos de identificar o terminal | `Terminal` |
| 8 status de caixa | 4 status |
| `Payment.card_subtype` obrigatório "às vezes" | débito e crédito como formas distintas, já com o código `tPag` |
| `Invoice` OneToOne com o pedido (impedia reemitir) | FK + "uma nota viva por venda" |
| Numeração fiscal em campos soltos | `FiscalSeries` |
| Status da NF-e de entrada derivável, mas gravado | propriedade `stage` |
| `NFeEvent` × `NFeManifestation` | `NFeEvent` com `direction` |
| Três campos de garantia que podiam discordar | `warranty_until` |

## 3. Segurança e consistência

- **Isolamento entre contas feito uma vez só,** no manager, pelo contexto da
  requisição. Antes era feito três vezes, uma delas reprocessando todo JSON de
  resposta. Sem conta no contexto, a consulta devolve **vazio**, nunca a base
  inteira.
- **Isolamento por loja/filial abaixo da conta.** O usuário tem lojas
  permitidas (N:N, ou "todas"), e o mesmo manager corta dados de outra loja,
  inclusive nas tabelas-filhas (itens, saldos, lotes, parcelas). No StarChef o
  usuário tinha uma loja ou todas, e o recorte só existia na view quando o
  header era enviado.
- **Referência a outra conta ou outra loja é recusada** no serializer (→ 400).
- **Sem escalada de acesso:** gerente de filial não concede "todas as lojas",
  não dá acesso a loja que não tem e não cria administrador.
- **Campo de FK resolvido na hora da validação** (`TenantPrimaryKeyField`).
  Isso evita um queryset vazio "congelado" no momento da importação do módulo.
- **Permissões num esquema único:** `área.view` / `área.manage` mais códigos para
  ações sensíveis. Antes havia uma classe de permissão por caso.
- **Autorização de gerente no próprio PDV:** usuário e senha do superior, ou a
  senha de caixa da loja.
- **Limite de desconto por cargo:** o que passar do limite pede autorização.
- **Segredos só de entrada:** senha de caixa, CSC, senha do certificado e tokens
  aparecem na saída apenas como `has_*`.
- **Uma só chave decide o DEBUG** (`DJANGO_ENV`). Antes, a divergência com
  `DJANGO_DEBUG` quebrava o login.
- **Envelope de erro único** em toda a API, com códigos estáveis (400 entrada,
  409 conflito, 422 regra, 403 autorização).

## 4. Regras que custam dinheiro

- **Valores monetários** sempre em `Decimal` (`MoneyField`), nunca em float.
- **Venda travada** (`select_for_update`) em toda escrita, relendo o estado
  depois do lock.
- **Proteções garantidas pelo banco:** um turno aberto por caixa, uma baixa de
  estoque por origem (`source_key`), um depósito padrão por loja e uma nota
  viva por venda.
- **Numeração sequencial única e travada** (`NumberSequence`) para venda,
  devolução e documento de estoque.
- **Checkout numa transação só** com `Idempotency-Key`: o reenvio do PDV nunca
  cobra nem baixa o estoque duas vezes.
- **Cancelar venda concluída não reescreve turno fechado:** o dinheiro sai do
  turno atual como devolução.
- **Base da comissão e da devolução é o valor pago,** com os descontos do total
  rateados entre os itens.
- **Cupom reavaliado a cada alteração:** sai sozinho se a venda deixar de se
  qualificar.

## 5. Novos recursos de varejo

- **Grade de variações:** tamanho/cor com SKU, código de barras, preço e estoque
  próprios, e geração automática das combinações.
- **Troca e devolução:** parcial, várias por venda, com vale-troca, dinheiro ou
  estorno na forma original.
- **Vale-troca** como extrato (saldo = soma das linhas) e como forma de pagamento.
- **Financeiro:** contas, plano de contas, títulos a pagar/receber, parcelas e
  baixas. Crediário, boleto e cartão D+N geram título automaticamente.
- **Limite de crediário** por cliente.
- **Vendedor e comissão:** por venda e por item, percentual no vendedor ou no
  produto, estorno proporcional na devolução.
- **Kit:** vender o kit baixa os componentes.
- **Leitura de código no PDV:** EAN/GTIN (com dígito verificador), SKU e
  etiqueta de balança (prefixo 2 + PLU + preço/peso).
- **Lotes com FEFO/FIFO,** bloqueio de vencidos e inventário que move só a
  diferença.
- **Etiqueta de gôndola** configurável por lista de campos.
- **Bootstrap do PDV:** uma chamada entrega terminal, loja, formas de pagamento,
  caixas, turno aberto, vendedores, impressoras e balanças.
- **Relatórios** a partir de um único recorte de vendas: resumo, por dia,
  produtos com margem, formas de pagamento e vendedores com comissão.
- **Conta pronta para vender** com um comando (`create_account`): loja,
  depósito, caixa, série fiscal, formas de pagamento, cargos e admin.

## 6. Estoque: WMS simples, etiquetas e entrada por NF-e

- **Endereçamento (WMS simples):** depósito com `uses_bins` passa a controlar
  rua/prateleira/nível (`StorageBin`) e o saldo por endereço e lote
  (`BinBalance`). Gera a grade de endereços de uma vez.
- **Regra que não quebra:** num depósito endereçado, a soma dos endereços é
  sempre o saldo do depósito — porque o único serviço que grava estoque
  (`services/stock.py`) atualiza os dois juntos, inclusive na venda do PDV e no
  estorno (que devolve ao mesmo endereço).
- **Guarda, separação, movimentação e inventário por endereço:** entrada vai
  para o endereço informado (ou a doca de recebimento); saída sem endereço segue
  o plano de separação (lote que vence antes, depois o caminho físico); lista de
  separação imprimível; movimentação entre endereços; contagem por endereço.
- **Etiquetas:** gôndola/produto (preço VIGENTE, com o "de/por" da promoção),
  lote (validade) e endereço; EAN-13, Code 128 ou QR em SVG; HTML no tamanho
  exato da etiqueta (térmica em rolo ou folha). Etiquetas da entrada saem com
  uma por unidade recebida.
- **Entrada por NF-e (XML):** importa o XML, confere que a nota é da loja,
  recusa nota repetida e XML com entidade externa (XXE), cadastra o fornecedor,
  casa os itens sozinho (código aprendido do fornecedor, EAN, ou "caixa com 12"
  pelo EAN da unidade), aprende cada vínculo confirmado, cadastra produto a
  partir do item, gera a entrada com custo real (frete + IPI + ST rateados por
  unidade de estoque) e lotes da nota, conferência com divergência e contas a
  pagar das duplicatas.

## 7. Financeiro integrado à operação

- **Padrões prontos na conta nova:** plano de contas básico (com chave fixa
  para os lançamentos automáticos — renomear não quebra), banco, adquirente e
  um cofre por loja; PIX no banco e cartões na adquirente.
- **Caixa → cofre:** abertura (troco sai do cofre), sangria (volta), suprimento
  e fechamento (o CONTADO entra; com diferença, só após aprovação do gerente).
  Saldo do cofre = vendas em dinheiro − devoluções ± diferença.
- **Venda → conta:** PIX/débito/vale entram na conta da forma de pagamento na
  hora, com a taxa da adquirente como despesa; crediário, boleto e cartão a
  prazo viram contas a receber (líquidas da taxa), na categoria Vendas.
  Cancelamento e devolução "na forma original" estornam; nada se apaga.
- **Lançamentos idempotentes e imutáveis:** `source_key` impede lançar duas
  vezes o mesmo evento; correção é por estorno (o extrato conta a história).
- **CMV:** custo médio congelado no item vendido; kit custa a soma dos
  componentes (antes saía com custo zero); devolução que volta ao estoque estorna.
- **Relatórios:** DRE gerencial (receita, descontos, devoluções, CMV, lucro
  bruto, taxas, comissões, quebras de caixa, despesas por categoria e
  resultado), fluxo de caixa realizado + previsto, saldos e extrato com saldo
  corrido por conta, vencimentos (atrasado/7/30/+30 dias) e relatório de
  fechamento de caixa (vendas, formas de pagamento, gaveta, esperado × contado,
  quem abriu/fechou/aprovou, custo e margem do turno).
- **Comissões:** pagamento das pendentes por vendedor até uma data, com saída
  no financeiro; estornos de devolução já descontados.
- **Transferência entre contas** (ex.: depósito do cofre no banco).

## 8. Frontend (retaguarda e PDV web)

- **TypeScript com tipos gerados do OpenAPI do backend.** O StarChef era em JS
  puro: campo renomeado no Django quebrava a tela em silêncio.
- **PrimeVue 4** (antes 3) e tema por tokens, com cores num único arquivo.
  Identidade própria: verde-petróleo no lugar do azul do StarChef.
- **Cadastros declarativos tipados** + telas genéricas pequenas. O StarChef
  tinha a mesma ideia, mas desenhada por arquivos de 2 a 7 mil linhas; aqui o
  maior tem ~180.
- **Cache por loja ativa** (TanStack Query): trocar de loja recarrega tudo e
  uma loja nunca mostra o cache da outra.
- **Autorização de gerente genérica** (`withApproval`): qualquer ação que o
  backend recuse por falta de autorização pede a senha do superior e repete.
- **PDV web** com venda retomada após recarregar a página e checkout idempotente.
- **Sistema de design com tema claro e escuro** (tokens semânticos, PrimeVue no
  mesmo tema, troca sem piscar, automático pelo sistema), hovers e foco
  consistentes, menu recolhível com seletor de loja, barra de ações fixa nos
  formulários com aviso de alterações não salvas, painel com gráfico e
  rankings, PDV redesenhado (formas de pagamento em blocos, total em destaque).

## 9. Produto no modelo do StarHub: tipos, variações e volumes

O cadastro antigo misturava pai e filho na mesma tabela (o "pai" da grade não
podia ser vendido) e guardava a grade em JSON. Agora segue o StarHub:

- **Produto** = o que o item É (nome, tipo, fiscal, categoria).
  **Variante** = o que se VENDE e se ESTOCA (SKU, código de barras, preço,
  custo, saldo). Todo produto tem ao menos uma; o simples tem só a padrão.
  Venda, estoque, lote, WMS, NF-e e etiqueta apontam sempre para a variante.
- **Tipos de produto** (`type`): simples, com variação (grade), kit (baixa as
  variantes componentes) e serviço (não estoca). Mais a **finalidade**
  (`purpose`, o "tipo do item" do SPED: revenda, insumo, uso e consumo...) e o
  **jeito de vender** (`sale_method`: unidade, balança ou fracionado).
- **Grade em tabelas**: `Attribute` (Cor) → `AttributeValue` (Azul), cadastrados
  uma vez na conta. "azul " e "Azul" são o mesmo valor; uma variante tem um
  valor por eixo e duas variantes não repetem a combinação (o banco garante).
  Gerar a grade é um salvar só: `{"grid": {"Tamanho": ["P","M"], "Cor": ["Azul"]}}`.
  O produto simples que ganha grade não perde SKU, códigos nem estoque.
- **Promoção por produto** vale para todas as variantes (desconto sobre o preço de cada uma).
- **Volumes** (`ProductVolume`): as caixas de UMA unidade — o guarda-roupa que
  vem em 3 caixas. Cada caixa tem código, peso e medidas. Servem para:
  - **etiqueta por caixa** ("Vol 2/3"), uma por caixa de cada unidade do documento;
  - **conferência por leitura** (`POST /stock/documents/{id}/conference/`): a
    unidade só conta quando todas as caixas foram lidas; caixas soltas e
    faltantes aparecem na resposta;
  - **carga da separação**: a lista de picking traz caixas, peso bruto e m³;
  - **PDV**: ler o código de uma caixa acha a variante (e diz qual caixa é).
- Excluir variante com saldo é proibido (zere por ajuste antes).

## 10. Qualidade

- **60 testes no backend e 16 no frontend** cobrindo os fluxos de dinheiro, acesso e isolamento entre contas.
- **Lint (ruff)** sem nenhum aviso.
- **Schema OpenAPI/Swagger** gerado de todas as rotas.
- **Documentação:** [ARQUITETURA.md](ARQUITETURA.md) e
  [ANALISE_STARCHEF.md](ANALISE_STARCHEF.md).
