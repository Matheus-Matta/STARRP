# Starrp

ERP de nicho geral para comércio e varejo: retaguarda, PDV desktop e app móvel.

| Pasta | O que é |
| --- | --- |
| `backend/` | API e admin: Django 5.2 + DRF, multi-conta (SaaS) e multi-loja |
| `frontend/` | retaguarda web e PDV web: Vue 3 + TypeScript + PrimeVue 4 |
| `desktop/` | PDV do caixa: Electron, com venda offline e NFC-e ([README](desktop/README.md)) |
| `mobile/` | app de celular: Expo ([README](mobile/README.md)) |
| `shared/` | código comum: fiscal (web e desktop) e casos de teste das regras do PDV |
| `docker/` | **produção**: compose, nginx, certificados ([README](docker/README.md)) |
| `deploy/` | `acbr/`: comunicador fiscal avulso; `production/`: opção antiga de produção, com Caddy |
| `scripts/` | os comandos `npm run` da raiz, em Node puro |
| `docs/` | documentação |
| `.github/` | CI e publicação por tag |

Documentação:
- Arquitetura do backend: [docs/ARQUITETURA.md](docs/ARQUITETURA.md)
- Frontend: [docs/FRONTEND.md](docs/FRONTEND.md)
- Segurança: [docs/SEGURANCA.md](docs/SEGURANCA.md)
- Histórico da migração do StarChef: [análise](docs/historico/ANALISE_STARCHEF.md) e
  [melhorias](docs/historico/MELHORIAS.md)
- Regras de commit, tag e publicação: [CLAUDE.md](CLAUDE.md)

## Começar

Precisa de **Python 3.12+** e **Node 20+**. Tudo roda da raiz do projeto:

```bash
npm run setup:demo   # cria .venv, .env, instala tudo, prepara o banco e a conta "Loja Demo"
npm run dev          # backend em :8001 e frontend em :5173, juntos
```

Abra http://localhost:5173 e entre com `admin` / `senha123`.
Sem demonstração, use `npm run setup` e crie a sua conta (veja abaixo).

## O que fica na raiz

| Arquivo | Para quê |
| --- | --- |
| `package.json` | os comandos `npm run` |
| `.venv/` | ambiente Python do backend (criado pelo `setup`) |
| `.env` | configuração do backend e do frontend (criado do `.env.example` com chave secreta nova; nunca vai para o git) |
| `scripts/` | os comandos em Node puro, iguais no Windows e no Linux |

## Comandos

| Comando | O que faz |
| --- | --- |
| `npm run setup` | prepara o ambiente (pode repetir; o `.env` existente é mantido) |
| `npm run setup:demo` | o mesmo + conta de demonstração |
| `npm run dev` | sobe backend e frontend (Ctrl+C para os dois) |
| `npm run backend` / `frontend` | sobe só um |
| `npm run desktop` / `mobile` | abre o PDV desktop / o Expo do app |
| `npm run test` | testes do backend (pytest) e do frontend (vitest) |
| `npm run lint` | ruff + eslint + checagem de tipos |
| `npm run build` | build de produção do frontend |
| `npm run api:types` | regera os tipos TS do frontend a partir do backend |
| `npm run migrate` / `makemigrations` | migrations do banco |
| `npm run account -- "Minha Loja" --admin dono --password senha123` | cria uma conta pronta para vender |
| `npm run manage -- <comando>` | qualquer comando do `manage.py` (ex.: `createsuperuser`) |

Sem `POSTGRES_DB` e `REDIS_URL` no `.env`, o backend usa SQLite e serviços em
memória. Swagger em http://localhost:8001/api/schema/swagger-ui/.

## Versões e publicação (GitHub Actions)

Cada parte tem a própria versão, publicada por uma tag `<parte>-v<maior>.<menor>.<correção>`. A tag só
gera a parte dela: `backend-v1.0.1` publica só o backend.

```bash
git push origin main                 # o commit vai para a branch (o CI testa só o que mudou)
git tag backend-v1.0.1               # na mesma revisão
git push origin backend-v1.0.1       # publica
```

| Tag                | Gera                                                                      | Workflow              |
| ------------------ | ------------------------------------------------------------------------- | --------------------- |
| `backend-v1.0.1`   | imagem `ghcr.io/<dono>/starrp-backend:1.0.1` (+ `1.0`, `1`, `latest`)      | `release-backend.yml`  |
| `frontend-v1.0.1`  | imagem `ghcr.io/<dono>/starrp-web:1.0.1` (+ `1.0`, `1`, `latest`)          | `release-frontend.yml` |
| `desktop-v1.0.1`   | `Starrp-PDV-1.0.1-win-x64.zip`, `Starrp-PDV-Setup-1.0.1.exe`, `Starrp-PDV-1.0.1-linux-x64.zip` | `release-desktop.yml` |
| `mobile-v1.0.1`    | `Starrp-1.0.1.apk`, `.aab` (Google Play) e `.ipa` (App Store), pelo EAS    | `release-mobile.yml`   |

- Cada release roda os testes da parte antes de publicar; teste falhando = nada publicado.
- A Release do GitHub traz só os commits que mexeram naquela parte desde a tag anterior dela.
- Sufixo vira pré-release (`mobile-v1.2.0-beta.1`): imagem sem `latest`, Release marcada como pré-release.
- O CI (`ci.yml`) roda em todo push/PR, só para as partes cujos arquivos mudaram. Não publica nada.

Configuração única no GitHub (Settings → Secrets and variables → Actions):

- **mobile**: segredo `EXPO_TOKEN`; rodar uma vez `npx eas-cli@latest init` em `mobile/` (grava o
  `projectId` no `app.json`, commitar) e `npx eas-cli@latest credentials` para o iOS (conta Apple);
  variável `API_URL=https://...` nos ambientes `preview` e `production` do EAS. Variável do repositório
  `MOBILE_AUTO_SUBMIT=true` envia o `.aab`/`.ipa` às lojas sozinho.
- **desktop** (opcional): segredos `WIN_CSC_LINK` (certificado .pfx em base64) e `WIN_CSC_KEY_PASSWORD`
  assinam o executável do Windows.
- **imagens**: nada a configurar (usa o `GITHUB_TOKEN`). No servidor, `docker login ghcr.io` se o pacote
  for privado; a versão usada é a do `docker/.env` (ver [docker/README.md](docker/README.md)).

## Licença

Copyright (c) 2026 Matheus Matta. **Todos os direitos reservados.** O código está público para leitura e
avaliação profissional; uso, cópia, modificação e distribuição dependem de autorização escrita ([LICENSE](LICENSE)).
