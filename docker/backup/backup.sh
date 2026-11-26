#!/bin/sh
# Uma cópia completa: banco + media + private, cada um cifrado (AES-256, PBKDF2) e enviado ao S3.
#
#   docker compose exec backup backup.sh              # cópia agora
#   docker compose exec backup backup.sh --list       # o que está no armazenamento
#   backup.sh --healthcheck                            # (healthcheck do container) última cópia boa há < 26 h
#
# Destino: s3://BACKUP_S3_BUCKET/BACKUP_S3_PREFIX/AAAA-MM-DD_HHMMSS/{db.dump,media.tar.gz,private.tar.gz}.enc
# BACKUP_S3_ENDPOINT vazio = AWS; preenchido = MinIO, B2, R2, Wasabi... (endereço com path-style).
set -eu
set -o pipefail  # pg_dump que falha no meio do pipe não vira "cópia feita"

STATE=/var/lib/starrp-backup
PREFIX="${BACKUP_S3_PREFIX:-starrp}"
KEEP="${BACKUP_KEEP_DAYS:-30}"

if [ "${1:-}" = "--healthcheck" ]; then
  # Saudável: a última cópia boa (ou a subida, enquanto a primeira não chegou) tem menos de 26 h.
  ref="$STATE/last_ok"
  [ -f "$ref" ] || ref="$STATE/started"
  [ -f "$ref" ] || exit 1
  [ $(( $(date +%s) - $(cat "$ref") )) -lt $(( 26 * 3600 )) ]
  exit $?
fi

[ -f /etc/starrp-backup.env ] && . /etc/starrp-backup.env

s3() {
  if [ -n "${BACKUP_S3_ENDPOINT:-}" ]; then
    aws --endpoint-url "$BACKUP_S3_ENDPOINT" s3 "$@"
  else
    aws s3 "$@"
  fi
}
export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-us-east-1}"
# MinIO e afins não têm o bucket como subdomínio: endereço em path-style.
aws configure set default.s3.addressing_style "${BACKUP_S3_ADDRESSING:-path}"

if [ "${1:-}" = "--list" ]; then
  s3 ls "s3://$BACKUP_S3_BUCKET/$PREFIX/"
  exit 0
fi

seal() {  # stdin → arquivo cifrado
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -out "$1"
}

stamp="$(date +%Y-%m-%d_%H%M%S)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
echo "backup $stamp: começando"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --compress=6 | seal "$work/db.dump.enc"
for part in media private; do
  if [ -d "/data/$part" ]; then
    tar -C "/data/$part" -czf - . | seal "$work/$part.tar.gz.enc"
  fi
done
( cd "$work" && sha256sum ./*.enc > SHA256SUMS )

s3 cp --recursive --only-show-errors "$work/" "s3://$BACKUP_S3_BUCKET/$PREFIX/$stamp/"
# Só conta como feita depois de conferir que chegou inteira lá.
s3 ls "s3://$BACKUP_S3_BUCKET/$PREFIX/$stamp/SHA256SUMS" > /dev/null
echo "backup $stamp: enviado ($(du -sh "$work" | cut -f1))"
mkdir -p "$STATE" && date +%s > "$STATE/last_ok"

# Retenção: apaga as cópias com mais de BACKUP_KEEP_DAYS dias (0 = guarda todas). Nunca a de hoje.
if [ "$KEEP" -gt 0 ]; then
  limit="$(date -d "@$(( $(date +%s) - KEEP * 86400 ))" +%Y-%m-%d)"
  s3 ls "s3://$BACKUP_S3_BUCKET/$PREFIX/" | awk '$1 == "PRE" {print $2}' | tr -d '/' | while read -r old; do
    case "$old" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_*) ;;
      *) continue ;;
    esac
    if [ "${old%%_*}" \< "$limit" ]; then
      s3 rm --recursive --only-show-errors "s3://$BACKUP_S3_BUCKET/$PREFIX/$old/"
      echo "backup: cópia antiga $old apagada (mais de $KEEP dias)"
    fi
  done
fi
