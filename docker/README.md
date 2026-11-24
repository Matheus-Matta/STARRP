# Starrp em produção (Docker)

```
internet ──► Cloudflare ──HTTPS──► nginx :443 ─┬─► backend-blue  ┐
              (proxy)      (:80 → redireciona) ├─► backend-green ┴─► Postgres, Redis, ACBr (redes internas)
                                               ├─► frontend (app Vue)
                                               └─► /media (fotos, direto do volume)
```

| Serviço         | Imagem                                         | Porta publicada |
| --------------- | ---------------------------------------------- | --------------- |
| `nginx`         | `nginx:1.28-alpine`                            | 80, 443 (`.env`) |
| `backend-blue`  | `ghcr.io/matheus-matta/starrp-backend`         | —               |
| `backend-green` | idem (pode estar noutra versão durante a troca) | —              |
| `frontend`      | `ghcr.io/matheus-matta/starrp-web`             | —               |
| `migrate`       | backend: migrations + permissões, roda e sai   | —               |
| `worker`/`beat` | backend: fila e agendador do Celery            | —               |
| `postgres`      | `postgres:16-alpine`                           | —               |
| `redis`         | `redis:7-alpine`                               | —               |
| `acbr`          | `ghcr.io/matheus-matta/comunicador-fiscal`     | —               |

**Redes** — só o nginx tem porta para fora:

- `web` (interna): nginx ↔ backends e frontend;
- `data` (interna): backends/worker ↔ Postgres e Redis;
- `fiscal`: backends/worker ↔ ACBr. Nem o nginx nem o frontend chegam no ACBr; ele sai para a SEFAZ.

## Subir

```bash
cd docker
cp .env.example .env                 # preencha (um .env só para todos)
# certs/origin.pem e certs/origin.key: certificado de origem da Cloudflare (certs/README.md)
docker login ghcr.io                 # se os pacotes forem privados
docker compose up -d
docker compose ps                    # backends "healthy"
```

Primeira vez: crie a conta `docker compose run --rm migrate python manage.py create_account "Loja" --admin admin --password <senha>`.

## Atualizar

- **Backend sem tirar do ar** (blue/green): `bash deploy-backend.sh 1.0.2`
  Troca o green, espera ficar saudável e só então troca o blue, o worker e o beat. Enquanto um troca,
  o nginx manda tudo para o outro (falhou 3 vezes em 10 s, sai da roda).
- **Frontend**: `FRONTEND_VERSION=1.0.2` no `.env` e `docker compose up -d frontend`.
- **ACBr**: `ACBR_VERSAO=...` no `.env` e `docker compose up -d acbr`.

## Portas

Dentro do container o nginx ouve sempre **80** e **443**; no servidor, as do `.env`:

| Variável                  | Padrão | Para quê                                                        |
| ------------------------- | ------ | --------------------------------------------------------------- |
| `NGINX_HTTP_PORT`         | 80     | porta http do servidor (só redireciona)                         |
| `NGINX_HTTPS_PORT`        | 443    | porta https do servidor                                         |
| `NGINX_PUBLIC_HTTPS_PORT` | 443    | porta que o **navegador** usa, no redirecionamento http → https |

Atrás da Cloudflare o navegador usa sempre 443: mantenha `NGINX_PUBLIC_HTTPS_PORT=443` mesmo com o servidor
noutra porta. A Cloudflare só repassa HTTPS para 443, 2053, 2083, 2087, 2096 e 8443 (ou para a porta de uma
*Origin Rule*). A config do site é o template `nginx/templates/starrp.conf.template`: o container troca as
variáveis `NGINX_*` ao subir (as do nginx, como `$host`, ficam como estão).

## Regras do nginx

- Só HTTPS: a porta 80 responde `301` para `https://`. TLS 1.2/1.3, HSTS de 1 ano.
- Envio de arquivos até **10 MB** (`client_max_body_size`).
- IP real do visitante pelo `CF-Connecting-IP`, aceito só dos IPs da Cloudflare
  (`nginx/snippets/cloudflare-real-ip.conf`). O `X-Forwarded-For` que chega ao Django é esse IP.
- WebSocket da Cosmos (`/api/v1/ws/`) com upgrade e 1 h de conexão.
- `POST`/`PATCH` nunca são repetidos no outro backend (não duplica venda nem pagamento); `GET` com erro
  de conexão tenta o outro.
