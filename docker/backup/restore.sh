#!/bin/sh
# Restauração de uma cópia do S3.
#
#   docker compose exec backup restore.sh --check [CÓPIA]   # TESTE: restaura num banco à parte e apaga (não mexe em nada)
#   docker compose stop backend-blue backend-green worker beat
#   docker compose exec backup restore.sh --apply CÓPIA     # SUBSTITUI banco, media e private pela cópia
#   docker compose up -d
#
# CÓPIA = a pasta (ex.: 2026-11-25_030000); sem ela, --check usa a mais nova. Faça o --check todo mês.
# O volume de media/private só é gravado no --apply (o container monta os dois para isso).
set -eu
set -o pipefail

[ -f /etc/starrp-backup.env ] && . /etc/starrp-backup.env
mode="${1:-}"
copy="${2:-}"
PREFIX="${BACKUP_S3_PREFIX:-starrp}"

s3() {
  if [ -n "${BACKUP_S3_ENDPOINT:-}" ]; then aws --endpoint-url "$BACKUP_S3_ENDPOINT" s3 "$@"; else aws s3 "$@"; fi
}
export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-us-east-1}" PGPASSWORD="$POSTGRES_PASSWORD"
aws configure set default.s3.addressing_style "${BACKUP_S3_ADDRESSING:-path}"
PG="-h ${POSTGRES_HOST:-postgres} -p ${POSTGRES_PORT:-5432} -U $POSTGRES_USER"

case "$mode" in
  --check|--apply) ;;
  *) echo "uso: restore.sh --check [CÓPIA] | --apply CÓPIA"; exit 2 ;;
esac
if [ -z "$copy" ]; then
  [ "$mode" = "--check" ] || { echo "--apply exige o nome da cópia (veja backup.sh --list)"; exit 2; }
  copy="$(s3 ls "s3://$BACKUP_S3_BUCKET/$PREFIX/" | awk '$1 == "PRE" {print $2}' | tr -d '/' | sort | tail -1)"
  [ -n "$copy" ] || { echo "Nenhuma cópia em s3://$BACKUP_S3_BUCKET/$PREFIX/"; exit 1; }
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
s3 cp --recursive --only-show-errors "s3://$BACKUP_S3_BUCKET/$PREFIX/$copy/" "$work/"
( cd "$work" && sha256sum -c SHA256SUMS ) || { echo "✗ cópia $copy corrompida (soma não confere)"; exit 1; }

open() {  # arquivo cifrado → stdout
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$1"
}

if [ "$mode" = "--check" ]; then
  test_db="starrp_restore_check"
  # shellcheck disable=SC2086
  dropdb $PG --if-exists "$test_db"
  # shellcheck disable=SC2086
  createdb $PG "$test_db"
  # shellcheck disable=SC2086
  open "$work/db.dump.enc" | pg_restore $PG -d "$test_db" --no-owner --exit-on-error
  # shellcheck disable=SC2086
  tables="$(psql $PG -d "$test_db" -tAc "select count(*) from information_schema.tables where table_schema='public'")"
  # shellcheck disable=SC2086
  sales="$(psql $PG -d "$test_db" -tAc "select count(*) from starrp_sale" 2>/dev/null || echo "?")"
  # shellcheck disable=SC2086
  dropdb $PG "$test_db"
  for part in media private; do
    [ -f "$work/$part.tar.gz.enc" ] && open "$work/$part.tar.gz.enc" | tar -tzf - > /dev/null
  done
  echo "✓ cópia $copy restaura: $tables tabelas, $sales vendas; media e private abrem."
  exit 0
fi

echo "→ Restaurando $copy POR CIMA do banco $POSTGRES_DB (os backends devem estar parados)."
# shellcheck disable=SC2086
open "$work/db.dump.enc" | pg_restore $PG -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error
for part in media private; do
  if [ -f "$work/$part.tar.gz.enc" ]; then
    find "/data/$part" -mindepth 1 -delete
    open "$work/$part.tar.gz.enc" | tar -C "/data/$part" -xzf -
    chown -R 10001:10001 "/data/$part"  # o usuário `app` do backend
  fi
done
echo "✓ $copy restaurada. Suba os backends: docker compose up -d"
