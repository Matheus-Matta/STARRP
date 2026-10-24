# Starrp

ERP de nicho geral para comércio e varejo: retaguarda, PDV desktop e PDV móvel.

- `backend/`: Django 5.1 + DRF, multi-conta (SaaS) e multi-loja.
- `frontend/`: retaguarda web e PDV web — Vue 3 + TypeScript + PrimeVue 4.

Documentação:
- Arquitetura do backend: [docs/ARQUITETURA.md](docs/ARQUITETURA.md)
- Frontend: [docs/FRONTEND.md](docs/FRONTEND.md)
- O que veio do StarChef, o que mudou e o que falta: [docs/ANALISE_STARCHEF.md](docs/ANALISE_STARCHEF.md)
- Lista de melhorias: [docs/MELHORIAS.md](docs/MELHORIAS.md)

## Começar

Precisa de **Python 3.12+** e **Node 20+**. Tudo roda da raiz do projeto:

```bash
npm run setup:demo   # cria .venv, .env, instala tudo, prepara o banco e a conta "Loja Demo"
npm run dev          # backend em :8000 e frontend em :5173, juntos
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
| `npm run dev:backend` / `dev:frontend` | sobe só um |
| `npm run test` | testes do backend (pytest) e do frontend (vitest) |
| `npm run lint` | ruff + eslint + checagem de tipos |
| `npm run build` | build de produção do frontend |
| `npm run api:types` | regera os tipos TS do frontend a partir do backend |
| `npm run migrate` / `makemigrations` | migrations do banco |
| `npm run account -- "Minha Loja" --admin dono --password senha123` | cria uma conta pronta para vender |
| `npm run manage -- <comando>` | qualquer comando do `manage.py` (ex.: `createsuperuser`) |

Sem `POSTGRES_DB` e `REDIS_URL` no `.env`, o backend usa SQLite e serviços em
memória. Swagger em http://localhost:8000/api/schema/swagger-ui/.
