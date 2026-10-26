# Arquitetura do backend Starrp

ERP de varejo multi-loja (SaaS) com PDV desktop e PDV móvel. Django 5.1 + DRF.

## A estrutura em uma frase

**Um único app Django (`starrp`), com os arquivos separados por TIPO (MVC) e,
dentro de cada tipo, um arquivo por ASSUNTO.**

```
backend/
├── config/                  # settings (base/development/production/test), urls raiz, asgi, celery
└── starrp/
    ├── models/              # M — dados. Um arquivo por domínio (sales.py, stock.py, fiscal.py…)
    ├── serializers/         # entrada/saída da API (validação de formato)
    ├── views/               # C — HTTP: recebe, chama o serviço, responde. SEM regra de negócio
    ├── services/            # regras de negócio (venda, caixa, estoque, preço, financeiro…)
    ├── urls/                # rotas, um arquivo por domínio, todas num router só
    ├── core/                # infraestrutura: tenant, middleware, permissões, erros, viewset-base
    ├── admin/               # admin do Django (registro automático)
    ├── management/commands/ # create_account, sync_permissions
    ├── migrations/
    └── tests/
```

No StarChef eram 22 apps Django, cada um com seus `models/views/serializers`,
importando uns dos outros em círculo (`orders` ↔ `kitchen` ↔ `restaurants`).
Um app só elimina as dependências cruzadas entre migrations e deixa claro
**onde cada coisa mora**:

| Pergunta | Onde |
| --- | --- |
| Que campos uma venda tem? | `models/sales.py` |
| O que acontece ao concluir a venda? | `services/checkout.py` → `complete()` |
| Qual URL conclui a venda? | `urls/sales.py` + `views/sales.py` → `complete` |
| Que JSON o PDV manda para pagar? | `serializers/sales.py` → `PaymentInputSerializer` |

## Camadas e quem pode chamar quem

```
urls → views → serializers (formato)
          └──→ services (regra) → models
```

- **View** não decide nada de negócio. Exemplo: `SaleViewSet.cancel` só valida
  o corpo e chama `checkout.cancel(...)`.
- **Service** é o único lugar que grava estado com regra (estoque, caixa,
  totais). Exemplo: só `services/stock.py` cria `StockMovement`.
- **Model** guarda dados e regras *locais* triviais (ex.: `Coupon.discount_for`).

## Isolamento em dois níveis: conta e loja

**Nível 1 — conta (tenant).** Toda tabela de negócio herda `TenantModel`. O
`TenantMiddleware` lê o JWT, descobre a conta e a fixa num `ContextVar`; o
manager `Model.objects` filtra **sozinho** por ela.

**Nível 2 — loja/filial.** O perfil do usuário diz quais lojas ele acessa:

| Perfil | Enxerga |
| --- | --- |
| cargo administrador, ou `all_stores = True` | todas as lojas (inclusive as futuras) |
| `stores = [A, B]` | só as lojas A e B |
| nenhuma loja | nada (403 `no_store_access`) |

O middleware coloca essas **lojas permitidas** no mesmo contexto da conta, e o
mesmo manager corta tudo que for de outra loja. Cada model diz por onde chega
à loja (`store_lookup`):

```python
class Sale(StoreModel):          # store_lookup = "store" (herdado)
class SaleItem(TenantModel):
    store_lookup = "sale__store" # o item é da loja da venda
class Product(TenantModel):      # store_lookup = None -> cadastro da rede inteira (variantes idem)
class Coupon(TenantModel):
    store_lookup = "store"
    store_shared_when_null = True  # sem loja = vale para a rede
```

O que é **da rede** (compartilhado): produtos, categorias, marcas, clientes,
fornecedores, perfis fiscais, cargos. O que é **da loja** (isolado): vendas,
caixa, pagamentos, estoque, documentos, notas, financeiro, terminais,
dispositivos, patrimônio — e todos os filhos deles.

**Loja ativa** (`X-Store-ID`) é a seleção da tela dentro das permitidas:
pedir uma loja não permitida dá 403 `store_forbidden`. Sem o header, vale a
`default_store` do usuário ou a única loja que ele tem; quem tem várias vê a
soma delas (listas e relatórios).

Regras de escrita:
- registro relacionado de outra conta OU de outra loja é recusado (400);
- usuário de filial não cria cadastro "da rede" (grava na loja dele) e não
  altera um que já é da rede (403);
- sem escalada: quem é de filial não concede `all_stores`, não dá acesso a loja
  que não tem, não atribui cargo administrador nem cargo acima do seu.

Três managers, cada um com um papel:

| Manager | Filtra conta? | Esconde excluídos? | Uso |
| --- | --- | --- | --- |
| `objects` | sim (contexto) | sim | views e consultas na requisição |
| `alive_objects` | não | sim | padrão do Django: relações reversas (`venda.items`) |
| `all_objects` | não | não | serviços, tarefas, sincronização (sempre passando `account_id`) |

> Fora de requisição (tarefa, comando), `objects` devolve **vazio** de propósito.
> Use `all_objects.filter(account_id=...)` ou `tenant_context(conta)`.

## Permissões

Cada view declara `permission_code`; leitura exige `<código>.view`, escrita
`<código>.manage`. Ações sensíveis têm código próprio (`sales.cancel`,
`sales.discount`, `cash.approve`, `logistics.manage` para andar a entrega…). O catálogo está em
`services/access_catalog.py`.

**Cargos são fixos do sistema** (19, por área e nível): Direção (Administrador, Diretor, Gerente
de loja, Supervisor), Vendas (Líder de vendas, Operador de caixa, Vendedor), Estoque e compras
(Coordenador de estoque, Comprador, Estoquista), Logística (Coordenador, Auxiliar), Financeiro
(Coordenador, Assistente), Fiscal, Marketing, Patrimônio, Suporte de TI e Auditor. Nascem com a
conta e são sincronizados por `ensure_system_data` (o deploy roda): nome, nível e permissões
vêm do catálogo; a conta só ajusta o desconto máximo e o "ativo". Criar/excluir cargo e mudar
permissão é do suporte (admin do Django).

**Um usuário soma cargos**: `UserProfile.role` (principal) + `extra_roles`. As permissões se
somam; vale o maior nível (`rank`, quem aprova quem) e o maior desconto; é admin se algum
cargo for. Ninguém atribui cargo (principal ou somado) acima do próprio nível.

Perfis fiscais: a conta cria os seus; os pré-prontos (`is_system`) se ajustam, mas não se excluem.

Quando o operador não tem a permissão, o PDV pode mandar a autorização de um
superior no corpo:

```json
{"reason": "cliente desistiu", "approval": {"username": "gerente", "password": "..."}}
```

## Erros

Todo erro sai no mesmo envelope:

```json
{"success": false, "status_code": 409, "error": {"code": "cash_session_required", "message": "Abra o caixa..."}}
```

- `400` entrada errada (o PDV corrige e reenvia);
- `409` conflito de estado (reenviar o mesmo corpo nunca resolve);
- `422` regra de negócio recusou;
- `403` com `approval_required` quando falta autorização.

## Regras que custam dinheiro (herdadas do StarChef, mantidas)

1. Dinheiro é `Decimal` (`MoneyField`), nunca `float`.
2. Escrita concorrente: `transaction.atomic` + `select_for_update` e **reler o estado depois do lock**.
3. A defesa contra dois operadores é do BANCO (constraint única/parcial), não um `if`.
   Exemplos: um turno aberto por caixa; uma baixa de estoque por `source_key`.
4. Escritas do PDV aceitam `Idempotency-Key`: o reenvio recebe a mesma resposta.

## Fluxo de venda no PDV (exemplo)

```
POST /api/v1/pdv/bootstrap/                 {"installation_id": "pc-01"}
POST /api/v1/cash/sessions/                 {"register": "<id>", "opening_amount": "100.00"}
POST /api/v1/sales/                         {}
POST /api/v1/sales/{id}/items/              {"code": "7891000315507", "quantity": "2"}
POST /api/v1/sales/{id}/checkout/           {"payments": [{"method": "<id>", "amount": "91.80", "tendered": "100"}]}
```

Pedido do vendedor (sem caixa): monta a venda e guarda; o caixa da MESMA loja retoma e cobra.

```
POST /api/v1/sales/{id}/park/               {"note": "Enviado ao caixa"}   → status "draft"
GET  /api/v1/sales/?status=draft            (recortado pela loja ativa)
POST /api/v1/sales/{id}/resume/             → "open", operador = quem retomou, turno dele
POST /api/v1/sales/{id}/checkout/           {"payments": [{"method": "<pix>", "amount": "60.00", "nsu": "889911"}]}
```

Vendedor não tem `cash.manage`: checkout/pagamentos dão 403. Forma com `requires_reference`
(PIX e cartões, fixo pelo `ensure_system_data`) sem `nsu`/`authorization_code` dá 422.

## Status do pedido: geral, pagamento e entrega (padrão do StarHub)

`Sale.status` é só o documento no caixa (aberta → guardada → concluída | cancelada); "concluída"
ali é "fechada e paga". O pedido tem mais três, derivados em `Sale.save()` (`derive_statuses`),
então nenhum fluxo esquece de atualizar:

| Campo | Valores | De onde sai |
|---|---|---|
| `payment_status` | aguardando, pago em parte, pago, estorno parcial, estornado, cancelado | `paid_amount`, `total`, `refunded_amount` (devoluções concluídas) |
| `fulfillment_status` | pendente → separado → saiu para entrega → entregue; retirado na loja; devolvido; cancelado | balcão vira "retirado" ao concluir; entrega anda pela ação abaixo; devolução total = "devolvido" |
| `overall_status` | em atendimento, pagamento em andamento, aguardando separação, pronto para entrega, em rota, **concluído**, devolvido, cancelado | o reflexo de tudo: só é "concluído" quando o produto chegou no cliente (entregue ou retirado) |

```
POST /api/v1/sales/{id}/fulfillment/  {"status": "ready"|"shipped"|"delivered", "note": ""}
```

Pular etapa preenche as do meio; voltar é uma etapa por vez e com motivo (vai para o histórico).
Cada etapa grava `<etapa>_at`/`<etapa>_by` ("Separado · Ana", "Saiu para entrega", "Entregue" no feed).

## Serviços oferecidos com o produto (padrão do StarHub)

O serviço (montagem, garantia estendida, embalagem) é um **produto do tipo Serviço** — tem
SKU, preço padrão e fiscal próprios. `ServiceRule` diz a quais produtos ele vale:

- **por categoria**: as categorias escolhidas (e as de dentro, até 3 níveis) E a faixa de
  preço opcional (`price_min`/`price_max`, pelo preço da variante padrão);
- **por produto**: os produtos escolhidos.

Para cada serviço vale a primeira regra ativa que casa, pela `position` (menor primeiro);
o preço é o da regra ou, vazio, o padrão do serviço. Regra sem critério é recusada (valeria
para o catálogo inteiro). Código: `services/service_rules.py`; cadastro em
*Catálogo → Serviços oferecidos* (`/catalog/service-rules/`).

Na venda o serviço é um `SaleItem` com `parent_item` (o item a que pertence):

```
POST /api/v1/sales/{id}/items/   {"variant": "<guarda-roupa>", "quantity": "2", "services": ["<montagem>"]}
POST /api/v1/sales/{id}/items/   {"variant": "<montagem>", "service_for": "<id do item>"}
```

O preço vem da regra (não é "alterar preço", não pede gerente); serviço não oferecido para
aquele produto dá 422 `service_not_offered`, repetido no mesmo item dá 409. Produto e
serviços entram numa transação só. Cancelar o item cancela os serviços dele; mudar a
quantidade do item muda a deles.

## Entrega: endereços do cliente e tabelas de frete (padrão do StarHub)

O cliente tem uma lista de endereços (`CustomerAddress`), editada no próprio cadastro:
`addresses` vai inteira no salvar do cliente (o que sai da lista é apagado; um só é o padrão).

`FreightTable` (`models/logistics.py`) é uma forma de cobrar:

- **por faixa de CEP** (`FreightZipRange`): valor e prazo da faixa que contém o CEP; faixa
  dentro de faixa vale e a mais estreita ganha;
- **por distância**: taxa fixa + km × preço por km, nunca abaixo do mínimo, sem entrega acima
  da distância máxima. Km por estrada (OSRM público) a partir do CEP de origem; coordenada do
  CEP pela AwesomeAPI/BrasilAPI. Os dois ficam em cache (`ZipCoordinate`, `ZipDistance`); sem a
  rota, estimativa em linha reta × 1,3 (e a cotação avisa).

```
GET  /api/v1/logistics/freight-tables/estimate/?zip=01310100           → conferir frete (PDV, Shift+F5)
GET  /api/v1/logistics/freight-tables/estimate/?street=..&number=..&district=..&city=..&state=SP
     (endereço completo: CEP pela ViaCEP para as tabelas por faixa; lat/long pelo OpenStreetMap
      para as por distância, medidas até o endereço exato)
GET  /api/v1/logistics/freight-tables/quote/?zip=01310100   → cotação de todas as tabelas ativas
POST /api/v1/sales/{id}/delivery/  {"address": "<id>", "table": "<id>"}   → frete no total
DELETE /api/v1/sales/{id}/delivery/                                       → retirada na loja
```

A entrega fica em `sale.shipping_address`, `sale.freight` e no metacampo do sistema
`_entrega` (tabela, prazo, km, detalhe). Código: `services/freight.py`.

## Metacampos e ficha técnica personalizada

Produto, cliente e pedido (e o item da venda) têm `metafields` ({chave: valor}), como os
metadados do StarHub. `MetafieldDefinition` dá nome, tipo (texto, número, sim/não, lista,
data), unidade e ordem a uma chave; no produto pode valer só para categorias (e as de
dentro). Chave definida é convertida e validada; chave sem definição é guardada como texto
(metacampo livre). Chaves com `_` no começo são do sistema (`_entrega`).

As definições do produto com `show_in_specs` formam a **ficha técnica** (`services/metafields.specs`),
que vai no `GET /pdv/products/{id}/` (`specs`) e aparece na vitrine do PDV:
"Tempo de montagem: 1,5 h", "Garantia: 12 meses". Metacampos do pedido:
`POST /sales/{id}/metafields/ {"metafields": {...}}` (os do sistema ficam).

## Dados fiscais e notas de entrada (NF-e pela SEFAZ)

**Dados fiscais** (`FiscalConfig`) é o emitente: CNPJ, IE, regime, endereço, certificado A1
e CSC. É um cadastro da conta; cada loja aponta para um (`Store.fiscal_config`), e lojas
com o mesmo CNPJ dividem o mesmo. "Criar a partir das lojas" copia o que a loja já tem
(`services/fiscal_data.from_store`). O mesmo cadastro serve a emissão (`Invoice.fiscal_config`)
e a busca de notas de entrada.

Caminho de uma nota que o fornecedor emitiu contra a loja:

```
1. busca DF-e (services/dfe.sync, a cada 65 min no Celery ou "Buscar na SEFAZ")
   → chega o RESUMO (resNFe): InboundNFe "só resumo", sem itens
2. ciência da operação 210210 (assinada, services/sefaz.sign) → baixa o XML completo
3. inbound_nfe.import_xml: itens casados pelo EAN (cEAN → fator 1; cEANTrib → qTrib/qCom)
   e pelo que o operador já vinculou antes para o fornecedor (SupplierProduct)
4. todos os itens vinculados → entrada de estoque em RASCUNHO (nfe_receiving.auto_entry)
5. CONFERÊNCIA: POST /stock/documents/{id}/check/
   {"codes": [...]}  leitura (leitor ou câmera do navegador) grava o contado, ou
   {"lines": [...]}  manual item a item (só na filial com "Permitir conferência manual" em
                     Logística › Configurações de logística — `LogisticsSettings`, uma por filial):
                     correto, ou incorreto com motivo + quantos chegaram + quantos entram
6. APROVAÇÃO: POST /stock/documents/{id}/post/ (sem conferência devolve conference_required)
   → estoque entra AJUSTADO, duplicatas viram contas a pagar, nota "recebida" ou "com
     divergência", e cada diferença vira um erro de entrada (ReceivingDivergence)
```

- **Voltar passos** (`services/inbound_nfe`): desvincular item (`items/{id}/unmap/`, esquece
  o vínculo aprendido), voltar a usar item ignorado (`unignore/`), restaurar nota ignorada
  (`restore/`), "Voltar para os vínculos" (`discard-entry/`: cancela a entrada em rascunho)
  e "Desfazer recebimento" (`undo-receipt/` com motivo, permissão `stock.manage`: estorna o
  estoque e cancela as contas a pagar; duplicata já paga barra). Mexer num item com a
  conferência aberta descarta o rascunho e a entrada nasce de novo.
- **Erros de entrada** (`/stock/divergences/`, menu Logística): nota × chegou × entrou,
  motivo (faltou, a mais, avariado, produto errado, vencido, outro), quem conferiu e como.
  Cancelar a entrada aprovada tira os erros dela (a nova aprovação registra de novo).

- Regras da SEFAZ: cStat 137 (nada novo) e 656 (consumo indevido) bloqueiam nova busca
  por 1 hora (`DFeSyncState.next_allowed_at`); o NSU é por CNPJ, nunca volta a zero.
- Cancelamento do fornecedor (evento 110111): rascunho de entrada é cancelado; se a nota
  já entrou no estoque, abre uma pendência (`NFeIssue`) para alguém decidir.
- Sem Celery: `python manage.py sync_dfe` (cron).

## Auditoria e histórico (quem mudou o quê)

Duas camadas, como no StarHub:

- **Histórico em todas as models** (django-simple-history, `models/history.py`): toda
  subclasse concreta de `TimeStampedModel` é registrada sozinha (model nova também), e cada
  `save()` — API, serviços (venda, estoque, caixa), admin, tarefa, shell — grava o retrato do
  registro em `Historical<Model>` com `history_user` (o usuário da requisição; fora dela, o
  `updated_by`). Ficam de fora (`SKIP`) os logs e razões imutáveis (`AuditLog`,
  `StockMovement`...), os saldos/contadores que mudam a cada venda (`StockBalance`,
  `NumberSequence`), a fila de sincronização e o cache de CEP. `QuerySet.update()` e
  `bulk_create` não passam pelo histórico. No admin, o botão "Histórico" mostra as versões.
- **`AuditLog`** (API de cadastro, ações em massa): criado/alterado/excluído com o diff, o
  motivo e o IP.

O feed de cada registro (`GET .../{id}/history/`, `services/history.py`) junta as duas: a
alteração que só o histórico tem entra como "Alterado" com o que mudou; a mesma gravação
nas duas (mesmo usuário, mesmos campos e valores, até 5 s) aparece uma vez; e a mudança feita
junto de um acontecimento ("Confirmado", "Cancelado") vai dentro dele.

## Caixa: operadores vinculados e fechamento cego

O caixa (`CashRegister`) tem os seus `operators`: só eles abrem o turno, fazem sangria e
suprimento e fecham (`services/cash._require_operator`; quem abriu o turno também). Quem tem
`cash.approve` (gerente, supervisor) assume qualquer caixa. O PDV só lista os caixas do
usuário (`bootstrap.cash_registers`).

**Abertura com conferência cega** (padrão do StarChef): o operador conta a gaveta e informa
(`opening_amount`, com observação), sem ver o esperado. Bate com o que o último fechamento
daquele caixa deixou (`left_in_drawer`) → turno `open`. Não bate → `pending_opening`: o caixa
não vende até o gerente aprovar (`POST /cash/sessions/{id}/approve-opening/`, direto com
`cash.approve` ou com `approval` — usuário/senha do gerente ou senha de ações do caixa). 1ª
abertura do caixa vira o saldo inicial. Operador não abre dois turnos ao mesmo tempo. O PDV
imprime o comprovante de abertura (80 mm). Com "exige caixa aberto", venda do PDV só é cobrada
num turno ABERTO do operador, em qualquer forma (fora do PDV, só o dinheiro exige).

**Fechamento cego**: sem `cash.approve`, a API não devolve o esperado na gaveta nem a diferença
(`expected_now`, `expected_amount`, `difference` = `null`, `blind: true`), e o relatório e o
extrato do turno saem só com troco inicial e contado (`cash.blind`). O operador conta e informa;
a diferença fora da tolerância vai para o gerente aprovar.

Modo do PDV (`bootstrap.mode`): **caixa** só para quem tem `cash.manage` E um caixa vinculado na
loja (ou um turno dele ainda aberto); com acesso mas sem caixa vinculado, entra em modo **vendedor**
(cria e guarda pedidos, sem nada do caixa). Em "todas as lojas", o PDV entra na loja principal do
usuário (`me.default_store_id`, senão a 1ª dele).

## Configurações da conta, logo e etiquetas pré-prontas

`GET/PATCH /api/v1/account/settings/` (só admin da conta) junta numa página: empresa, PDV e caixa
(aplicado a TODAS as lojas no salvar), estoque e plano/módulos (leitura). Na tela: Configurações →
Configurações da conta (último item, só para o administrador).

Logo: `POST /api/v1/account/logo/` (multipart `file`) recorta o centro e salva 1080×1080 em PNG
(`media.square_logo`); `DELETE` tira. Vai em `me.account.logo_url` e no canto superior direito
das impressões (na bobina, no topo); sem logo, o do Starrp (`/logo.svg`).

Modelos de etiqueta: 8 pré-prontos nascem com a conta (`system_data.LABEL_TEMPLATES`: gôndola,
oferta, tag de roupa, folha A4 3 colunas, lote, endereço e volume), marcados `is_system` — ajusta,
não exclui; a conta cria os seus. Um pré-pronto só vira padrão se a conta ainda não tem padrão
daquele tipo.

## Tabelas de desconto com as regras dentro

A tabela (`DiscountTable`: nome, período, loja) traz as regras (`Promotion`) no próprio corpo:
`rules` é a lista completa — o que sai dela é excluído e a ORDEM é a prioridade (a 1ª regra
que pega o produto vale). Cada regra: alvo (categorias — com as de dentro —, marcas, produtos
ou tudo), tipo (percentual, valor abatido, preço fixo), valor, período próprio opcional e, no
alvo "produtos", o "por" de cada produto (`PromotionProduct`, vence o tipo da regra).

```
POST /api/v1/promotions/tables/  {"name": "Liquida verão", "rules": [
  {"name": "Moda praia -20%", "target": "categories", "kind": "percent", "value": "20", "categories": ["<id>"]},
  {"name": "Boné por 39,90", "target": "products", "kind": "percent", "value": "0",
   "products": [{"product": "<id>", "promotional_price": "39.90"}]}]}
```

Na tela, a seção "Regras" fica no fim do formulário da tabela (`PromotionRulesField`); não
há mais cadastro separado de regras no menu (o endpoint `/promotions/rules/` continua na API).

## Listas: ordenação e ações em massa

- **Ordenação por qualquer coluna** (`core/ordering.py`): `?ordering=category_name` vira
  `category__name` pelo próprio serializer. Valor calculado ordena por anotação declarada
  na view (`ordering_annotations`, ex.: `"price": Min("variants__price")`). Coluna que não
  existe devolve 400, em vez de ser ignorada em silêncio.
- **Ações em massa** (`core/bulk.py`), como as "actions" do Django admin, em TODO `TenantViewSet`:
  `GET /<recurso>/bulk/` lista as ações liberadas para o cargo; `POST` executa com
  `{"action", "ids": [...]}` ou `{"action", "all": true}` + os filtros da tela na URL.
  - Padrão: exportar CSV (só pede `view`), ativar/desativar, ligar/desligar, excluir.
  - Excluir passa item a item pela mesma regra da exclusão unitária; o que não pode sair
    volta em `skipped` com o motivo (ex.: cargo do sistema).
  - Ação nova = método `bulk_<nome>` com `@bulk_action("Rótulo", params=[...])`; `params`
    usa o mesmo formato de campo do frontend e vira um diálogo na tela.
  - Exemplos: produtos (definir categoria/marca, adicionar tags), clientes (adicionar a grupo, tags).

## Convenções

- Identificadores em **inglês**; textos para o usuário em **português**.
- Choices com `models.TextChoices` dentro da model (`Sale.Status.OPEN`).
- Máximo de ~200 linhas por arquivo: passou disso, quebre **por assunto**.
- Comentário explica **por quê**, nunca **o quê**.

## Dados fixos e demonstração

- **Dados fixos do sistema** (`services/system_data.py`): formas de pagamento (uma por tipo) e
  10 perfis fiscais (Simples Nacional, regime normal, ST, isento, serviço, devolução...). Toda
  conta nova recebe pelo sinal `post_save` de `Account` (`signals.py`); `manage.py
  ensure_system_data` completa contas antigas sem mexer no que a loja ajustou.
  A loja lê e ajusta (ativar, taxa, prazo, conta de destino), mas **criar e excluir é só do
  superusuário** (`SystemDataViewSet`; no admin do Django ou pela API com `X-Account-ID`).
- **Demonstração** (`manage.py seed_demo [--account slug] [--dry-run]`, chamado por
  `npm run setup -- --demo`): pelo menos 10 registros por cadastro — 10 lojas com dados
  fiscais, usuários e cargos, clientes e fornecedores com CPF/CNPJ válidos, categorias em
  árvore, produtos simples/grade/kit/serviço/peso com EAN, estoque por documentos confirmados,
  promoções e cupons, 10 turnos de caixa com ~30 vendas, contas a pagar/receber com parcelas,
  lançamentos, notas de entrada (XML) e notas emitidas. Tudo pela MESMA API das telas; as vendas
  ficam espalhadas pelos últimos 30 dias. Rodar de novo não duplica.

## Comandos

Todos da raiz do projeto (detalhes no [README](../README.md)):

```bash
npm run setup                 # .venv + .env + dependências + banco
npm run dev                   # backend :8000 + frontend :5173
npm run account -- "Minha Loja" --admin admin --password senha123
npm run test                  # pytest + vitest
npm run lint                  # ruff + eslint + tipos
npm run manage -- shell       # qualquer comando do manage.py
```

Swagger: `http://localhost:8000/api/schema/swagger-ui/`


## Filiais (Store) e hierarquia

Na tela a "loja" se chama **filial** (no código e na API continua `Store` / `store`; "loja
virtual" e "retirada na loja" seguem com o nome). Cada filial tem um **tipo** (matriz,
regional, filial, centro de distribuição) e a quem **responde** (`Store.parent`): a lista de
Filiais abre em árvore (`?root=1` / `?parent=<id>`) e o cadastro recusa ciclo (a matriz não
pode responder a uma subordinada). Regras que mudam de filial para filial ficam em cadastros
por filial, como `LogisticsSettings` (nasce sozinha para cada filial).


## Livro de relatórios

`GET /reports/book/<slug>/?date_from=&date_to=` (`services/report_book.BOOK`): cada relatório
devolve o mesmo formato — `kpis` (com `delta` contra o período anterior de mesmo tamanho e
`good` = se subir é bom) e `blocks` (`line`, `bars`, `ranking`, `share`, `heatmap`,
`waterfall`, `table`) — e uma só tela (`ReportPage.vue`) desenha todos. Grupos no menu
"Relatórios" (item com submenu, em Operação): **Movimento** (vendas, horários de pico,
recebimentos, vendedores, comparativo de filiais), **Mercadorias** (curva ABC, categorias,
posição de estoque, entradas e saídas, erros de entrada), **Contábil** (DRE em cascata,
fluxo de caixa, vencimentos, saldos) e **Relacionamento** (clientes). Permissão e módulo
por relatório (contábil exige `finance.view` + módulo Financeiro; estoque, `stock.view`).

Cada relatório manda também os **filtros próprios** (`filters`, com as opções já prontas:
vendedor, forma de pagamento, canal, categoria, marca, grupo de clientes, depósito,
fornecedor, motivo, conta, tipo...) — o valor volta como parâmetro e fica no endereço da
página (dá para mandar o link filtrado). Séries no tempo agrupam sozinhas (`grain`): até 45
dias por dia, até ~7 meses por semana, além por mês. O texto "para que serve / como ler /
ajuda a decidir" de cada relatório fica em `frontend/src/reports/catalog.ts` (`about`).

**Impressão e exportação.** "Imprimir" abre a folha própria do relatório
(`/imprimir/relatorio/<slug>?<período e filtros>`, `print/docs/ReportBookPrint.vue`): cabeçalho
da empresa, filtros aplicados, indicadores, gráficos (sempre nas cores de papel) e as tabelas
completas, com a escolha do que sai (indicadores, gráficos, tabelas, "para que serve") e A4
retrato ou deitado — nunca a tela. `GET /reports/book/<slug>/export/?formato=xlsx|csv`
(`services/report_export.py`, openpyxl): Excel com a aba "Resumo" (período, filial, filtros,
indicadores e variação) e uma aba por bloco — moeda, % e data formatados, cabeçalho fixo e
filtro do Excel; tabela com abas (Curva ABC) ganha uma aba por classe. `bloco=<i>` exporta só
uma tabela e `aba=<valor>` só uma classe; CSV com ponto e vírgula, vírgula decimal e BOM.

Gráficos (`components/report/`): paleta categórica validada para daltonismo nos dois temas
(`--series-1..8` em tokens.css, ordem fixa, a 9ª fatia vira "Outros"), sequencial de um tom
no mapa de calor, divergente azul ↔ vermelho na cascata, uma escala só por gráfico, barras de
até 24px com ponta arredondada, balão em todo gráfico e tabela com exportação CSV em todo
relatório (os valores nunca dependem só da cor).


## Avaliações (padrão do StarHub)

`Review` (`models/reviews.py`, `services/reviews.py`): nota de 1 a 5, comentário (até 1500),
até 3 fotos, nome público abreviado ("Matheus S."), selo de compra verificada e moderação
(pendente → aprovada/rejeitada com motivo, quem e quando). Avalia-se o **produto** (uma por
cliente e produto) e a **entrega** de uma venda (uma por venda) — índices únicos no banco; a
rejeitada não conta. Na venda concluída, "Link de avaliação" gera um link assinado (120 dias,
sem banco) e a mensagem pronta para o WhatsApp; o cliente avalia pelo celular, sem login, em
`/avaliar/<token>` (`GET/POST /api/v1/public/reviews/<token>/`). A retaguarda modera em Vendas ›
Avaliações e também registra a avaliação contada no balcão. `manage.py seed_reviews` cria
avaliações e entregas de exemplo (o `seed_demo` chama no fim).

Relatórios ligados: **Avaliações** e **Curva ABC de clientes** (Relacionamento), **Entregas**
(Logística: prazo prometido = venda + dias úteis da tabela de frete × entregue, atrasos,
bairros, frete e a nota da entrega) e **Cancelamentos e devoluções** (Movimento).


## Cruzamentos (um assunto explicado por outro)

`services/report_cross.py`: agrupa as vendas por uma dimensão e mede, em cada grupo, o
resultado de outra. Relatórios do grupo **Cruzamentos**: clientes (classe ABC) × satisfação e
entrega; entrega (no prazo / com atraso / atrasada aberta) × nota e recompra; vendedores ×
desconto, margem, cancelamento e nota; produtos (classe ABC) × nota, margem e devolução, com
quadrantes (estrela, atenção, joia escondida, revisar); faixas de desconto × ticket, margem e
recompra. Dois blocos novos: `compare` (grupos × medidas, com o melhor ▲ e o pior ▼ de cada
coluna) e `insights` (conclusões escritas a partir dos números, só com dado nos dois lados, e
aviso de base pequena). Os mesmos cruzamentos aparecem dentro dos relatórios comuns (Curva ABC
de clientes e de produtos, Avaliações, Entregas). "Voltaram a comprar" = o cliente fez outra
compra depois daquela (até hoje). A regra de prazo da entrega fica em `report_book.delivery_state`.


## Promoções: o desconto se paga?

`services/report_promotions.py`, grupo **Promoções** do livro:
- **Descontos: visão geral** — quanto se abriu mão em promoção de produto ((preço cheio − cobrado) ×
  qtd. nos itens com promoção), cupom e desconto manual, e o resultado de cada tipo (ticket, margem,
  recompra, nota) contra as vendas sem desconto.
- **Promoções de produto** — por regra da tabela de desconto, nos mesmos produtos: unidades e lucro
  POR DIA com a promoção valendo (janela da regra e da tabela) × no resto do período. Veredito:
  compensou (lucro/dia subiu), vendeu mais e lucrou menos, não aumentou as vendas, prejuízo (abaixo
  do custo) ou sem base (não vendeu fora da promoção).
- **Cupons** — por cupom: usos, clientes novos (1ª compra com ele), margem, recompra contra quem
  compra sem cupom, gasto nos 60 dias seguintes (um cliente conta uma vez) e lucro por R$ 1 de
  desconto. Veredito: fideliza e dá lucro, dá lucro e não fideliza, fideliza no prejuízo, não se paga.

**Prejuízo** aparece de dois jeitos, sempre com KPI, conclusão e lista própria (com mensagem quando
a lista está vazia):
- venda abaixo do custo (lucro < 0): listas "Vendas que deram prejuízo" (visão geral) e "Vendas com
  cupom que deram prejuízo" (cupons), com nº da venda, cliente, vendedor, desconto e perda;
- promoção que lucrou menos do que sem ela: coluna `impact` = (lucro/dia com − lucro/dia sem) × dias da
  promoção (sem base, só conta se o lucro foi negativo); ranking "Deram prejuízo" e KPI "Perda com
  promoções". Os vereditos de perda começam com "Prejuízo:".

`manage.py seed_promotions` cria vendas de exemplo pela API (cupom, desconto manual, promoção e
recompras), tudo numa transação; o `seed_demo` chama no fim.
`seed_promotions --prejuizo` cria só 3 vendas de exemplo no prejuízo (desconto de 45–55%, nota
"Exemplo de venda no prejuízo (gerador da demo)"), uma vez por conta.
