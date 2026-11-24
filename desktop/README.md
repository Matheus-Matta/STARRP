# Starrp PDV (desktop)

PDV de balcão em **Electron + React + Tailwind**, recriado a partir do PDV web (`frontend/src/pages/pdv`).
Fala com a mesma API do backend (`/api/v1`).

## Rodar

```bash
cd desktop
npm install          # baixa também o binário do Electron (postinstall)
npm run dev          # janela com recarga automática
```

O backend precisa estar no ar (`npm run backend` na raiz → `http://localhost:8001`). Outro endereço:
engrenagem na tela de login, ou `STARRP_SERVER_URL=http://192.168.0.10:8001 npm run dev` (http só em
desenvolvimento; o app instalado exige https).

| Comando             | O que faz                                      |
| ------------------- | ---------------------------------------------- |
| `npm run typecheck` | confere os tipos (processo principal e tela)   |
| `npm run build`     | typecheck + build em `out/`                    |
| `npm run preview`   | abre o build de `out/`                         |
| `npm run dist`      | instalador Windows (NSIS) em `dist/`           |

## Login e tokens

- O login vai em `POST /auth/login/`; o **access** e o **refresh** token ficam só no **processo
  principal**, criptografados no disco com o cofre do Windows (`safeStorage`/DPAPI) em
  `%APPDATA%\Starrp PDV\session.bin`. A tela (React) nunca vê os tokens: toda chamada à API passa
  por IPC (`window.starrp.api`) e o processo principal põe o `Authorization: Bearer`.
- 401 → renova com o refresh (`POST /auth/refresh/`, que gira o refresh) e repete a chamada.
  Refresh recusado → apaga os tokens e volta ao login. Sem rede, a sessão é mantida.
- Reabrir o app entra direto enquanto o refresh valer (7 dias). **F8 (Sair)** invalida o refresh no
  servidor (blacklist) e apaga o arquivo.
- Configuração (servidor, filial, nome do terminal, tema) em `%APPDATA%\Starrp PDV\config.json`.
  O terminal é registrado no `/pdv/bootstrap/` como `device_type: "desktop"`, um por filial.

## Produção (instalador)

`npm run dist` gera `dist/Starrp PDV-Setup-<versão>.exe` (roda typecheck, testes de regras e de segurança).

- **HTTPS sempre** no app instalado: o endereço do servidor tem que ser `https://` (só `localhost` aceita
  http). Configuração antiga com `http://` não manda nada até ser corrigida (`src/shared/serverUrl.ts`).
- **Trocar de servidor apaga o login**: o token de um servidor nunca vai para outro.
- **Token só cifrado**: sem o cofre do Windows (DPAPI), o token fica só na memória (fechou, pede login).
- **Janela travada**: a tela não navega para fora do app, links só abrem `http(s)` no navegador,
  permissões do navegador (câmera, microfone...) negadas e sem DevTools.
- **Fuses do Electron** (`electron-builder.yml`): sem `ELECTRON_RUN_AS_NODE`, `NODE_OPTIONS` e
  `--inspect`; `app.asar` com integridade conferida (alterado, não abre).
- **Autorização offline** do gerente/senha do caixa vale 30 dias desde a última conferência com o
  servidor no ar (gerente desligado deixa de autorizar).
- **Assinatura**: defina `CSC_LINK` (certificado .pfx) e `CSC_KEY_PASSWORD` antes do `npm run dist`;
  sem isso o Windows avisa "editor desconhecido" ao instalar.
- Desinstalar mantém `%APPDATA%\Starrp PDV` (fila offline, notas e configuração).

## Estrutura

```
src/main/       processo principal: janela, IPC, tokens, cliente da API, impressão 80 mm
src/preload/    ponte segura (`window.starrp`)
src/shared/     contrato IPC (tipos)
src/renderer/   React: login, PDV (pdv/), estado (state/), peças de UI (ui/)
```

As regras do PDV são as mesmas da web (`pdv/usePdv.ts` ≈ `frontend/src/composables/usePdv.ts`):
vendedor × caixa, abertura/fechamento cegos, sangria/suprimento, autorização do gerente,
bloqueio de tela, guardar/retomar pedido, entrega com cotação de frete e pagamento dividido.
Teclas: F1 venda · F2 pedidos · F3 cliente · F4 caixa · F5 preço (⇧F5 frete) · F6 desconto ·
F7 cupom · F8 sair · F9 guardar · F10 pagar/concluir · F11 tela cheia · Shift+F11 entrega · F12 bloquear.

## Configurações deste PC (⚙ Config. no trilho)

- **Impressão**: imprimir direto ou perguntar antes; impressora dos recibos e a da nota, cada uma
  do Windows (pelo nome) ou térmica de **rede** por IP:porta (ESC/POS raster, corte e gaveta);
  papel 58/80 mm ou A4; cópias; página de teste.
- **Nota fiscal**: emissão NFC-e/NF-e pelo **Comunicador Fiscal desktop** (app-fiscal-acbr, modo
  `local`, `http://127.0.0.1:8030`). Só o token (tela Acesso do comunicador) fica aqui, criptografado
  no processo principal; no modo local não há cifra. O emitente (A1, CSC) fica no comunicador.
  O PDV baixa o **kit fiscal** (`/pdv/fiscal-kit/`: emitente, perfis, série própria do terminal),
  monta o INI e registra a nota no servidor (`/sales/{id}/invoices/register/`).
  SEFAZ fora: NFC-e em contingência (tpEmis 9), transmitida depois. Exige nos dados fiscais da
  filial o provedor ACBrLib e "emissão no terminal". O fiscal é do módulo Base: todo PDV emite.
- **Offline**: servidor fora (rede ou erro 5xx) → a venda nova é local (`pdv/offline.ts`) com o
  catálogo guardado (`/pdv/catalog-snapshot/`); concluída, vai para a fila (`outbox.json`) e sobe
  por `/pdv/offline-sales/` quando o servidor volta (`src/main/sync.ts`). Offline não há desconto,
  cupom, entrega, crediário/vale-troca nem abrir/fechar caixa.

No pedido (F2): emitir nota, imprimir a nota na impressora configurada ou em outra, recibo,
endereços, alterar entrega, trocar pagamento e cancelar — conforme a permissão do cargo.

## Local-first (o caixa trabalha no PC)

No modo caixa a venda inteira é montada e calculada **neste PC** (`pdv/offline.ts`), com o
catálogo guardado, e vai **pronta** ao servidor no fim (`POST /pdv/offline-sales/`), junto com a
nota emitida pelo ACBr local:

1. Cobrar: com o servidor no ar, a venda é validada antes (`?dry_run=1`: crediário, limite,
   cupom e frete); se ele recusar, a venda continua aberta para corrigir.
2. A venda conclui no PC e entra na fila **segurada**; a NFC-e sai pelo ACBr local.
3. `flush`: a venda vai com a nota; o recibo/DANFE sai com o número real do servidor
   (ou OFF-n se ele estiver fora, e ela vai quando ele voltar).

- Desconto/preço/cancelamento acima do limite: `/pdv/authorize/` no ar; fora do ar, a senha do
  gerente que já autorizou neste PC (resumo scrypt, `main/local.ts`).
- Guardar: no ar vira pedido guardado da loja; fora, fica "Guardado neste PC". Retomar um
  pedido do servidor e concluir conclui **o mesmo** pedido (mesmo número).
- Guardado no PC (criptografado): venda em andamento, pedidos guardados, histórico das vendas
  (reimprimir offline) e as senhas aprendidas. Desbloquear a tela offline usa a senha do login.
- Precisam do servidor: cupom, entrega/frete, crediário/vale-troca, abrir/fechar/sangria do caixa
  e o modo vendedor.

## Caixa e vendedor sem servidor (como no mercado)

**Turno de caixa é do terminal.** Abrir, sangria/suprimento, fechar e o comprovante funcionam
sem servidor. Cada evento entra na MESMA fila das vendas, em ordem (abertura → vendas →
sangrias → fechamento) e vai para `POST /pdv/offline-cash/` quando ele responder. O turno aberto
sem servidor (`off:...`) segue local até fechar, mesmo que o servidor volte.

- Conferência cega: o operador informa o contado; o servidor compara ao receber. Abertura ou
  fechamento feitos sem servidor não travam o caixa: a diferença fica gravada no turno para o
  gerente conferir.
- Sangria/suprimento sem servidor: o gerente ou a senha de ações do caixa aprovam na hora,
  conferidos pela senha que o PC aprendeu.
- "Dinheiro na gaveta" (quem aprova vê): troco ou o último esperado do servidor, mais as vendas
  em dinheiro e os movimentos feitos neste PC.

**Vendedor.** O pedido é montado no PC. "Enviar ao caixa" com o servidor no ar vira pedido
guardado da loja. Sem servidor, o pedido vai pela fila **e** vira uma **pré-venda com QR** (na
tela e no ticket). O caixa lê o QR com o leitor e cobra na hora, sem rede entre os PCs. Chegue a
pré-venda antes ou depois da venda, o servidor junta as duas (`presale`), sem duplicar.

## Regras alinhadas com o servidor (contrato)

O que o PDV faz sem servidor passa pelas **mesmas regras** do backend antes de acontecer
(`pdv/rules.ts`: abrir/fechar caixa, sangria/suprimento, checkout). Cada recusa usa o **mesmo
código de erro** do backend (`movements_pending`, `seller_required`...).

- Os dados das regras vêm sempre do servidor (bootstrap/catálogo guardados): limites, caixas,
  formas de pagamento, "exige vendedor/NSU/caixa aberto". Nada é fixo no desktop.
- `shared/pdv-rules.cases.json` é o caderno de casos. O backend roda esses casos contra os
  services de verdade (`starrp/tests/test_pdv_rules_parity.py`) e o desktop contra
  `rules.ts` (`npm run test:rules`, que também roda no `npm run build`). Se uma regra mudar só
  de um lado, o teste quebra. Ao mudar uma regra: mude o caderno e os dois lados.
- O que já aconteceu no PC sem servidor o backend aceita como fato: produto inativado depois,
  fechamento com sangria pendente, sangria além do esperado, diferença na abertura/fechamento.
  Tudo fica registrado para o gerente conferir.
- Só o servidor sabe algumas coisas (outro PC abriu o mesmo caixa, o gerente fechou o turno pela
  web). Nesses casos o envio pode ser recusado e fica em Pedidos/Config. → Offline, com o motivo,
  para tentar de novo ou descartar.

## Nota fiscal: o mesmo núcleo no desktop e na web, comunicadores diferentes

Os dois PDVs montam a nota com o **mesmo código**, `shared/fiscal/` (INI, numeração pela série do
terminal, contingência, registro no servidor), e emitem pelo Comunicador Fiscal ACBr
(<https://github.com/Matheus-Matta/app-fiscal-acbr>), cada um pelo seu transporte
(`shared/fiscal/transport.ts`):

| | PDV desktop | PDV web (nuvem) |
|---|---|---|
| Comunicador | **desktop** (`.exe`), modo `local`, no PC do caixa | **Docker**, modo `nuvem` (`deploy/acbr/`) |
| Quem chama | o processo principal do Electron (`src/main/fiscal.ts`) | só o backend (`POST /pdv/acbr/`, `services/acbr_cloud.py`) |
| Segredos | o token, cifrado pelo Windows | token + `ACBR_E2E_KEY` no `.env` do backend |
| Certificado A1 + CSC | guardados no comunicador (tela Emitente, ou "Gravar certificado no comunicador": `GET /pdv/fiscal-emitter/` → `/v1/config/emitente`, só do próprio PC) | nos dados fiscais da filial; o backend manda em cada chamada, cifrado |
| Sem internet | vende e emite em contingência offline | não emite |

O navegador não fala com comunicador nenhum e não guarda segredo. O kit (`/pdv/fiscal-kit/`)
também não. O **cancelamento** de qualquer nota ACBrLib (desktop ou web) sai do backend pela
nuvem (`/v1/nfe/cancelar`), com o certificado dos dados fiscais.
