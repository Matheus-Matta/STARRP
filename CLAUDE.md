# Starrp — instruções para a IA

Monorepo do ERP de varejo: `backend/` (Django), `frontend/` (Vue), `desktop/` (PDV Electron),
`mobile/` (Expo) e `shared/` (código comum). Respostas e textos de commit em **português**.

## Commits e tags (publicação)

Cada parte tem versão própria e é publicada pela **tag da parte**. A tag dispara só o workflow
dela (`.github/workflows/release-<parte>.yml`): `backend-v1.0.1` gera só a imagem do backend.

| Parte      | Tag                  | Caminhos da parte                     | O que a tag gera                       |
| ---------- | -------------------- | ------------------------------------- | -------------------------------------- |
| backend    | `backend-vX.Y.Z`     | `backend/`                            | imagem `ghcr.io/<dono>/starrp-backend` |
| frontend   | `frontend-vX.Y.Z`    | `frontend/`, `shared/fiscal/`         | imagem `ghcr.io/<dono>/starrp-web`     |
| desktop    | `desktop-vX.Y.Z`     | `desktop/`, `shared/`                 | .zip Windows/Linux + instalador .exe   |
| mobile     | `mobile-vX.Y.Z`      | `mobile/` (e `frontend/src/` que ele reaproveita) | .apk, .aab e .ipa (EAS)      |

### Regras

1. **Um commit por parte.** Mudança que toca backend e frontend vira dois commits, cada um só com os
   arquivos da sua parte (`git add backend/...` / `git add frontend/...`). As notas da Release listam os
   commits pelos caminhos; commit misturado aparece nas duas.
2. **Mensagem**: `<parte>: <o que mudou, no imperativo>` — ex.: `backend: corrige troco no fechamento cego`,
   `frontend: esconde custo para o caixa`. Mudança comum: `shared: ...`; só CI/docs da raiz: `ci: ...`/`docs: ...`.
3. **Versão (semver)** a partir da última tag DA PARTE:
   ```bash
   git fetch --tags
   git tag --list 'backend-v*' --sort=-v:refname | head -1     # ex.: backend-v1.0.1
   ```
   - correção sem mudar comportamento esperado → `Z+1` (1.0.1 → 1.0.2);
   - função nova compatível → `Y+1`, `Z=0` (1.0.2 → 1.1.0);
   - quebra (API/contrato muda, migration que exige ação, app antigo para de funcionar) → `X+1` (→ 2.0.0);
   - teste antes da final: sufixo `-beta.N` / `-rc.N` (vira pré-release, imagem sem `latest`).
   - Primeira publicação de uma parte: `<parte>-v1.0.0`.
4. **Ordem**: checagens → commit(s) → `git push` da branch → tag no commit da parte → `git push` da tag.
   ```bash
   git push origin main
   git tag -a backend-v1.0.2 -m "backend 1.0.2: corrige troco no fechamento cego"
   git push origin backend-v1.0.2
   ```
   Empurre **uma tag por vez, com o nome dela** (nunca `git push --tags`: publicaria tudo que estiver local).
5. **Checagens antes da tag** (as mesmas do workflow; falhou lá = nada publicado):
   - backend: `npm run test` (pytest em paralelo) e `.venv\Scripts\python -m ruff check .` em `backend/`;
     model alterado → migration gerada e `npm run test:migrations`;
   - frontend: `npm run lint`, `npm run typecheck`, `npm test` em `frontend/`;
   - desktop: `npm run build` em `desktop/` (tipos + regras iguais ao backend + segurança);
   - mobile: `npm run typecheck`, `npm run lint` e `npm run check:build` em `mobile/`.
6. **Dependências entre partes** — quando a mudança precisa chegar a mais de uma, uma tag para cada:
   - `shared/fiscal/` → frontend e desktop; `shared/pdv-rules.cases.json` → backend e desktop;
   - `frontend/src/` usado pelo app → frontend e, se o app precisa da mudança, mobile;
   - mudança de API no backend que o front/desktop/mobile usam → publique o **backend primeiro**.
7. **Tag publicada não se move nem se apaga.** Saiu errado → corrija e publique a próxima versão.
8. **Nunca** commitar `.env`, certificados, tokens, `backend/media/`, `dist/`, `out/`, `node_modules/`.
9. Commit, push e tag **só quando o usuário pedir** ("commita", "publica", "sobe a versão"). Se ele pedir
   para publicar sem dizer a versão, siga a regra 3 e diga qual versão escolheu e por quê.

## Ambiente local

- Windows nativo (sem WSL/Docker para o dia a dia). Python do backend sempre pelo `.venv` da raiz.
- Comandos do monorepo em `package.json` da raiz (`npm run dev`, `npm run test`, `npm run lint`...).
- Produção: `docker/docker-compose.yml` — nginx (só HTTPS, certificado de origem da Cloudflare em
  `docker/certs/`, uploads até 10 MB) balanceando `backend-blue` e `backend-green`, frontend, Postgres, Redis,
  Celery e o ACBr (rede interna, sem porta). Um `.env` só (`docker/.env`). Backend novo sem tirar do ar:
  `bash docker/deploy-backend.sh X.Y.Z` (troca o green, depois o blue). Login só por cookie httpOnly no
  navegador; desktop e mobile exigem `https://` no app de produção.

## Segurança

O estado da segurança e o plano de correção estão em [docs/SEGURANCA.md](docs/SEGURANCA.md): achados com ID
(`S-01`...), prioridade por fase, o teste de regressão que cada correção precisa ter e as defesas já confirmadas.
- Antes de mexer em autenticação, permissões, usuários, fiscal (certificado/CSC), PDV offline, Cosmos ou
  exportações, leia o achado correspondente.
- Corrigiu um achado: teste em `backend/starrp/tests/test_security_<tema>.py`, commit `backend: fecha S-NN ...`
  e o estado no documento vira `CORRIGIDO em <versão>`.
- Nunca serve segredo por `/media/`, nunca grava segredo no histórico/auditoria, nunca confia em valor/aprovação
  vindos do cliente (PDV, Cosmos) sem conferir no servidor.
