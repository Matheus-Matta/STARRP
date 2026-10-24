# Análise do backend StarChef e o que mudou no Starrp

Base analisada: `d:\projetos\starchef\backend` (22 apps, ~67 mil linhas fora
de testes e migrations, ~60 models). Resultado: 1 app, 85 models em 23
arquivos, 167 rotas, ~7,9 mil linhas.

> A diferença de tamanho NÃO é só limpeza: parte dos serviços do StarChef
> ainda não foi portada (ver "O que falta" no fim). Os números servem para
> mostrar a estrutura, não para comparar funcionalidade.

## 1. Inconsistências encontradas e como foram resolvidas

### Estrutura

| No StarChef | Problema | No Starrp |
| --- | --- | --- |
| 22 apps com imports cruzados (`orders` ↔ `kitchen` ↔ `restaurants`) | migrations dependentes entre apps; difícil saber onde mora a regra | 1 app, pastas por tipo (`models/`, `views/`, `services/`…) |
| Regra de negócio em views, serializers, signals e models | a mesma regra em vários lugares | regra só em `services/` |
| `urls.py` raiz com 60+ imports e rotas soltas (`/cash-register/`, `/cash-stations/`, `/cash-discrepancy-report/`) | nomes inconsistentes e duplicados | `urls/` por domínio, prefixos coerentes (`/cash/sessions/`, `/cash/registers/`) |
| Uma classe de permissão por caso (`CanManageCashRegister`, `CanOperateScale`…) | regra diferente em cada uma | um esquema: `permission_code` + `<área>.view/.manage` |
| Isolamento por conta feito 3 vezes (manager, mixin que ignorava o manager, middleware que re-parseava TODO JSON de resposta) | custo em toda resposta e regras divergentes | manager por contexto + validação no serializer |

### Models

| No StarChef | Problema | No Starrp |
| --- | --- | --- |
| `Restaurant` + `Branch`, ambos com CNPJ, endereço, taxa, tolerância de caixa ("campos espelhados") | duas fontes da mesma verdade | `Store` (a loja É o emitente) |
| `FiscalConfig` copiava CNPJ/IE/endereço do emitente | 3ª cópia dos dados da loja | lidos de `Store` |
| `Account.plan` + `Account.subscription_status` + `Subscription.plan/status` | assinatura em dois lugares | só `Subscription` |
| `Account.status` + `Account.is_active` | dois "ativo" | só `status` (`is_active` é propriedade) |
| `FocusNfeConfig` e `CosmosConfig` (uma tabela por integração) | cresce uma tabela por fornecedor | `Integration(provider, credentials, settings)` |
| `GlobalSystemConfig` + singleton `DFeGlobalConfig` | duas tabelas de config global | `SystemSetting(key, value)` |
| Dois soft-deletes (`SoftDeleteModel` e `TenantBaseModel.delete`) | comportamentos diferentes | só `deleted_at` em `TenantModel` |
| 10 models sobrescreviam o FK `restaurant` herdado para torná-lo opcional | herança que mentia | `StoreModel` (obrigatório) ou `optional_store_fk()` explícito |
| `Product` + `Ingredient` paralelos, e `Product.item_type=INGREDIENT` | o mesmo item em duas tabelas | só `Product` com `kind` |
| `product_type` + `item_type` + `production_sector` + `sector` | 4 classificações sobrepostas | `kind` + `category` + `brand` |
| `image` + `logo_image` + `ProductImage` | 3 jeitos de guardar foto | `Image` + `ProductImage` |
| `ean` + `gtin` (um único por conta, outro por filial) | dois códigos com regras diferentes | `ProductBarcode` (N códigos, únicos na conta) |
| `estimated_cost` + `current_average_cost` + `last_purchase_cost` + `margin_percent` | margem gravada desatualiza | `average_cost` + `last_cost`; margem calculada no relatório |
| NCM no `FiscalProfile` | no varejo cada produto tem NCM: exigiria um perfil por NCM | NCM/CEST/origem no produto; perfil só com CFOP/CST/alíquotas |
| `ProductUnitConversion` e `SupplierItemMapping` | mesma informação em duas tabelas | `SupplierProduct` |
| `StockLot` × `InventoryLot` | dois sistemas de lote | só `StockLot` |
| `StockEntry`/`StockExit` × `GoodsReceipt` | dois documentos de entrada | só `StockDocument` (com `kind`) |
| `StockMovement` com FK `product` e `ingredient`, 6 tipos "legado" | ambiguidade do que moveu | só `product`, tipos únicos, quantidade com sinal, `balance_after` (kardex) |
| `StockEntry.supplier` texto + `StockEntryItem.supplier` FK | fornecedor em dois formatos | FK `supplier` no documento |
| `CashStation` (caixa) + `CashRegister` (que era a SESSÃO) | nome trocado | `CashRegister` (caixa) + `CashSession` (turno) |
| `CashRegister.station` texto + `device_identifier` texto + `PdvTerminal` | 3 jeitos de dizer "de onde" | `Terminal` |
| Abertura/fechamento como movimentos E como campos da sessão | valor duplicado | só campos da sessão |
| 8 status de caixa (`blocked`, `pending_opening`, `closed_with_difference`…) | estados que só existiam no código de uma tela | 4: aberto, aguardando aprovação, fechado, cancelado |
| `Payment.card_subtype` obrigatório "às vezes" | regra escondida | débito e crédito são formas distintas, com `tPag` fiscal |
| `Invoice` OneToOne com o pedido | impedia reemitir nota rejeitada | FK + constraint de "uma nota viva por venda" |
| `FiscalConfig.series/next_number/cloud_series/cloud_next_number` | numeração solta | `FiscalSeries` (modelo + série + origem) |
| `certificate_ref` + `certificate_file`; `provider_token` + tokens Focus | campos duplicados | um de cada |
| `InboundNFe.status` derivável de outros 4 status | coluna que divergia | propriedade `stage` |
| `NFeEvent` × `NFeManifestation` | eventos em duas tabelas | `NFeEvent` com `direction` |
| `Asset.warranty_start/months/end` | três campos que discordavam | `warranty_until` |
| `SyncDiscard` com campos em português (`origem`, `motivo`, `dados`) | idioma misturado | inglês, como o resto |
| `STATUS_X = "x"` + `STATUS_CHOICES = [...]` | constante e lista repetidas | `models.TextChoices` |

### Removido por ser específico de restaurante

Mesas e setores, comandas e seus itens/rodadas, cozinha/KDS, SLA de preparo,
entregadores e zonas de entrega, adicionais, ficha técnica (receita),
carência de envio à cozinha, conta agrupada, fila de numeração de comanda,
taxa de serviço. Menus do site (storefront) ficaram de fora por decisão.

### Novo para varejo

- **Grade**: produto pai (`variant_attributes`) + variações (`variant_options`),
  cada uma com SKU, código de barras, preço e estoque próprios.
  `POST /catalog/products/{id}/generate-variants/` cria as combinações.
- **Troca e devolução** (`SaleReturn`) com vale-troca (`CustomerCredit`),
  devolução em dinheiro ou estorno na forma original; valor rateado pelo
  desconto que o cliente teve.
- **Financeiro**: contas, plano de contas, títulos a pagar/receber, parcelas e
  baixas. Crediário/boleto/cartão D+N viram títulos automaticamente.
- **Vendedor e comissão**: vendedor por venda e por item, % no vendedor ou no
  produto, estorno proporcional na devolução.
- **Kit**: vender o kit baixa os componentes (`ProductComponent`).
- **Etiqueta de balança** (EAN-13 prefixo 2, PLU + preço/peso).
- **Etiqueta de gôndola** (`LabelTemplate` com lista de campos).

## 2. O que já funciona (com teste)

Venda completa pela API (leitura de código, troco, baixa de estoque, gaveta),
promoção (regra de disputa preservada), cupom (mínimo, limite por CPF),
desconto com autorização de gerente, cancelamento com estorno, devolução com
vale-troca reutilizado, crediário com limite e parcelas, idempotência do
checkout, lotes FEFO, inventário, etiqueta de balança, fechamento de caixa com
aprovação, isolamento entre contas, login/`me`/bootstrap do PDV e permissões.

## 3. O que falta portar (próximas fases)

| Fase | Do StarChef | Tamanho lá |
| --- | --- | --- |
| Fiscal | emissão NFC-e/NF-e (Focus NFe e ACBrLib), contingência, cancelamento, DANFE | `apps/invoices` ~7 mil linhas |
| NF-e de entrada | busca automática na SEFAZ (DF-e) e manifestação do destinatário. **Já feito:** importação do XML, casamento automático, recebimento, contas a pagar | `apps/inbound_nfe` ~7 mil linhas |
| Sincronização | outbox/inbox, worker WSS, matrícula, triggers PostgreSQL, bootstrap | `apps/synchronization` ~12,7 mil linhas |
| Impressão | renderização ESC/POS e HTML de recibo, fechamento, etiquetas | `apps/printers` ~3,7 mil linhas |
| Tempo real | WebSocket (Channels) para avisos ao PDV | `apps/realtime` |
| Importação/exportação | CSV de produtos/clientes | `apps/imports`, `apps/data_exchange` |

As **models** dessas fases já estão prontas no Starrp; falta a camada de
serviços. Ordem sugerida: fiscal → impressão → NF-e de entrada → sincronização.
