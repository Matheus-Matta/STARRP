# Starrp Mobile

App Android (Expo SDK 58 + Expo Router) para a operação do dia a dia: consultar e
movimentar estoque, acompanhar vendas, caixas e relatórios. Roda no **Expo Go**.
Usa a mesma API da retaguarda (`/api/v1`) com o token no header (como o PDV desktop).

## Rodar

```bash
npm run mobile:install   # uma vez (na raiz do monorepo)
npm run mobile           # só o Expo do app
npm run mobile:tunnel    # o mesmo, por túnel (ngrok): quando o celular não alcança o PC na rede
npm run mobile:check     # confere se o app monta (Android); "-- all" = Android e iOS. Log em mobile/logs/
```

Quando o app não abre no celular: o terminal do `npm run mobile` mostra as etapas da abertura
(`[starrp] +0.6s fontes carregadas`, `[starrp] sessão: ...`) e qualquer erro (`[starrp] ERRO FATAL ...`,
`[starrp] PROMESSA REJEITADA ...`). Erro de build (import quebrado, pacote que não existe) aparece no
`npm run mobile:check`.

1. Instale o **Expo Go** no celular (Play Store), no mesmo Wi-Fi do PC.
2. Leia o QR code que o `npm run mobile` mostra.
3. No login, informe o endereço do servidor da API, usuário e senha.

O app precisa alcançar um backend. Em produção é o mesmo endereço HTTPS da retaguarda.
Com o backend local, ele precisa escutar na rede (`runserver 0.0.0.0:8001`), ter o IP do
PC em `DJANGO_ALLOWED_HOSTS` e o Python liberado no firewall do Windows (rede privada);
no app, use `http://<IP-do-PC>:8001`.

## O que tem

O app tem a **mesma estrutura da retaguarda**: ele lê, em tempo de build, os arquivos do próprio
frontend — os cadastros (`frontend/src/resources`), o menu (`components/layout/navigation.ts`), o livro de
relatórios (`reports/catalog.ts`), a validação, as máscaras e os formatos. Cadastro novo na retaguarda
aparece no app sem código novo.

| Tela | Como funciona |
|---|---|
| Barra de atalhos (topo) | Menu · [atalho 1] · Início · [atalho 2] · Relatórios. Os atalhos 1 e 2 se adaptam ao cargo: 1 = Vendas → Produtos → Clientes → Caixas → Financeiro; 2 = Estoque → Financeiro → Clientes → Produtos → Caixas (vale o primeiro liberado). **Menu** abre o menu lateral da retaguarda. Nada no rodapé |
| Início | só os atalhos, ordenados pelo uso neste aparelho: os 3 mais acessados, o último acessado e depois a ordem do menu |
| Filtros e exportar | em relatórios, listas e registros: botão **Filtros** abre a gaveta da direita (período com atalhos e datas livres; seleções com busca, as de cadastro buscam no servidor) e **Exportar** gera PDF (no estilo da impressão da retaguarda), Excel/CSV e abre o compartilhar do celular |
| Aparência | Claro, Escuro ou Sistema, no menu lateral (tema escuro gerado do mesmo tokens.css) |
| Filial | criar/editar nunca pergunta a filial: em "Todas as filiais" usa a filial principal do usuário (`default_store_id`); editar usa a filial do próprio registro |
| PDV móvel (`/venda`) | vender pelo celular (canal `mobile`): cliente, itens pelo leitor ou busca, +/−, desconto, guardar pedido para o caixa ou receber (uma ou mais formas, troco, parcelas, NSU) e concluir; abre o caixa se a filial exigir. O item "PDV" do menu e o "Nova venda" da lista de vendas levam para cá |
| Lista de qualquer cadastro (`/cadastros/<nome>`) | busca, filtros declarados + ordenação, cartões como o celular da retaguarda, menu "⋯" da linha, ações da lista, botão "Novo" |
| Registro (`/cadastros/<nome>/<id>`) | a página de leitura (selos, números, seções, tabelas), ações (confirmar, cancelar, baixar...), consultas e histórico |
| Formulário (`.../novo`, `.../<id>/editar`) | as mesmas seções, campos, condições e conferências; erros do backend no campo |
| Relatórios | o livro da retaguarda, com "para que serve" de cada relatório |
| Painel financeiro, Início (painel), Estoque | painéis no formato do celular |
| Movimentar / lançamento | tela própria do app (leitor de código, +/−); a lista e a leitura são as da retaguarda |

O que é do computador fica marcado como tal: Configurações da conta, Integrações, impressão e os
diálogos próprios da retaguarda (ex.: conferência de NF-e). Campos compostos (variantes, parcelas, itens,
fotos) aparecem para leitura no formulário.

As permissões seguem o backend (`core/permissions.py`) — o app só **esconde** o que não dá para usar.

### Como o app usa o frontend

`metro.config.js` resolve `@front/...` para `frontend/src/...` e, dentro desses arquivos, troca o que só
existe no navegador por substitutos em `src/shared/shims`: o cliente HTTP (vai pelo cliente do app, com
token e filial), a impressão, as etiquetas e o Vue (diálogos `.vue` viram "só na retaguarda").
Os tipos vêm de `src/shared/types.ts`, gerado de `frontend/src/resources/types.ts`:

```bash
npm run front:types   # rode quando o types.ts da retaguarda mudar
```

Se uma definição da retaguarda passar a importar algo novo do navegador, inclua o substituto em
`metro.config.js` (`SHIMMED`).

### Estilo (Tailwind = CSS da retaguarda no celular)

O visual é feito com **Tailwind via [Uniwind](https://uniwind.dev)** (`className` nos componentes RN):

- `src/styles/theme.css` e `src/lib/tokens.ts` são **gerados** de `frontend/src/styles/tokens.css`
  (cores, raios, sombras do tema claro): `bg-card`, `text-strong`, `border-border`, `bg-brand-subtle`...
- `src/global.css` reproduz as classes da retaguarda (`card`, `pill`, `field-label`, `input`, `btn`,
  `m-card`, `fsec-card`, `rv-card`, `actionbar`, `nav-item`...) com os valores das regras
  `@media (max-width: 640px)` de `base.css`, `primevue.css` e de cada componente; os breakpoints são os da
  retaguarda (`xs` 560, `sm` 640, `md` 720, `lg` 900, `xl` 1100).
- Fonte: Plus Jakarta Sans, uma família por peso (`font-sans`, `font-sans-semibold`, `font-sans-bold`...).

```bash
npm run front:styles   # rode quando o tokens.css da retaguarda mudar
```

Evite utilitários negativos (`-mx-4`) e cores com alfa em `@utility`: use valores arbitrários (`mx-[-16px]`).

## Estrutura

```
src/app/                 rotas: login, (app)/(tabs), cadastros/[resource]/..., relatório, painéis
src/components/resource/ telas genéricas: cartão de linha, campo, seletores, leitura, ações, histórico
src/shared/              ponte com a retaguarda: ícones, rotas, permissões, valores, shims, tipos
src/api/                 cliente HTTP (token, refresh, X-Store-ID, envelope de erro)
src/session/             sessão (/me/, filial ativa) e regras de acesso
src/global.css           Tailwind: classes da retaguarda no celular (+ src/styles/theme.css gerado)
src/lib/                 tokens.ts (gerado), cores para ícones, formatação, hooks
```

## Checagens

```bash
npx tsc --noEmit && npx expo lint && npx expo-doctor
```

O contrato com a API está em `backend/starrp/tests/test_mobile_app.py`.

## Produção (APK)

A tag `mobile-vX.Y.Z` gera o `Starrp-X.Y.Z.apk` no GitHub Actions e o anexa à Release
(`.github/workflows/release-mobile.yml`). Não usa o EAS nem conta Expo: é `npm run build:apk` (`expo prebuild` +
Gradle), que também roda num PC com Java 17 e SDK do Android (no Windows, só com o repositório num caminho
curto, por causa do limite de 260 caracteres do C++ do React Native). O APK instala direto nos aparelhos da
loja ("instalar apps desconhecidos"); não vai para a Play Store.

- **Servidor padrão**: variável do repositório `MOBILE_API_URL=https://app.suaempresa.com.br` (sem ela, o
  endereço é digitado na ⚙ do login).
- **Assinatura**: sem segredos, o APK sai com a chave de debug do React Native (pública; serve para começar).
  Para a chave da empresa: `keytool -genkeypair -v -keystore starrp.jks -alias starrp -keyalg RSA -keysize 4096
  -validity 10000`, e os segredos `ANDROID_KEYSTORE_BASE64` (o .jks em base64), `ANDROID_KEYSTORE_PASSWORD`,
  `ANDROID_KEY_ALIAS` e `ANDROID_KEY_PASSWORD`. Trocar de chave obriga a desinstalar o app antigo; guarde o .jks
  fora do repositório (perdeu = não atualiza mais o app instalado).

Para as lojas (Play Store/App Store) há o `eas.json`: `npx eas-cli@latest build --profile production`.

- **HTTPS sempre** no app de produção: endereço sem protocolo vira `https://`, `http://` é recusado (no
  login, no "Testar conexão" e em toda chamada). O build de produção com `API_URL` em http nem termina.
  Em desenvolvimento (Expo Go) http continua valendo.
- **Token só no cofre do aparelho** (SecureStore; no iPhone, só neste aparelho e desbloqueado: não vai
  para backup do iCloud). Android sem backup automático (`allowBackup: false`). No Expo web de
  produção o token fica só na memória, nunca no `localStorage`.
- **Trocar de servidor apaga o login**: o token de um servidor nunca vai para outro.
- **Rede oscilando não desloga**: só volta ao login quando o servidor recusa o token; sem resposta, a
  tela mostra erro de conexão e a sessão continua.
- **Custo e margem**: sem `catalog.view_costs`, os cadastros da retaguarda e a impressão do turno não
  mostram as colunas (mesma regra do frontend, `frontend/src/utils/costs.ts`).

