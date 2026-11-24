#!/bin/sh
# Servidor da API em produção: uvicorn ASSÍNCRONO (event loop uvloop + parser httptools), sem gunicorn.
#
# Cada processo atende muitas conexões ao mesmo tempo: nada fica em fila esperando a anterior terminar.
# - WebSocket (Cosmos) e o que é async rodam direto no event loop;
# - as views do Django/DRF (síncronas) rodam cada requisição na sua própria thread (ThreadSensitiveContext
#   do Django), em paralelo; o banco vem do pool do psycopg (POSTGRES_POOL_MAX por processo).
#
# Variáveis (do .env / do compose):
#   WEB_CONCURRENCY      processos (o uvicorn reinicia o que morrer)       padrão 3
#   UVICORN_KEEPALIVE    segundos de keep-alive com o nginx (> 60 do nginx) padrão 75
#   UVICORN_LIMIT        máx. de conexões simultâneas por processo; acima disso responde 503 na hora
#                        em vez de enfileirar (0 = sem limite). Conta também as conexões que o nginx
#                        mantém abertas (keepalive 32 por processo do nginx): use 200 ou mais. padrão 0
#   UVICORN_LOOP         event loop (uvloop na imagem Linux; asyncio para testar no Windows) padrão uvloop
#   FORWARDED_ALLOW_IPS  de quem aceitar X-Forwarded-* (o compose põe "*": só o nginx chega aqui)
set -eu

limit="${UVICORN_LIMIT:-0}"
extra=""
[ "$limit" -gt 0 ] && extra="--limit-concurrency ${limit}"

# --lifespan off: o Django não usa o protocolo lifespan (sem isso o uvicorn só avisa no log).
# shellcheck disable=SC2086
exec uvicorn config.asgi:application \
  --host 0.0.0.0 --port 8000 \
  --workers "${WEB_CONCURRENCY:-3}" \
  --loop "${UVICORN_LOOP:-uvloop}" --http httptools --ws websockets \
  --lifespan off \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --timeout-keep-alive "${UVICORN_KEEPALIVE:-75}" \
  --timeout-graceful-shutdown 30 \
  --no-server-header \
  $extra
