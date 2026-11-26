#!/bin/sh
# Agenda o backup (crond do BusyBox) no horário de BACKUP_CRON e deixa o log no `docker compose logs backup`.
set -eu

: "${BACKUP_CRON:=0 3 * * *}"

# Configuração mínima antes de agendar: sem ela, nada seria copiado e ninguém saberia.
for name in BACKUP_S3_BUCKET BACKUP_S3_ACCESS_KEY BACKUP_S3_SECRET_KEY BACKUP_PASSPHRASE POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD; do
  eval "value=\${$name:-}"
  [ -n "$value" ] || { echo "backup: defina $name no .env" >&2; exit 1; }
done
[ "${#BACKUP_PASSPHRASE}" -ge 20 ] || { echo "backup: BACKUP_PASSPHRASE precisa de 20+ caracteres" >&2; exit 1; }

# O cron não herda o ambiente do container: as variáveis vão num arquivo só do root.
env | grep -E '^(BACKUP_|POSTGRES_|TZ=)' | sed "s/'/'\\\\''/g; s/=\(.*\)/='\1'/; s/^/export /" > /etc/starrp-backup.env
chmod 600 /etc/starrp-backup.env

mkdir -p /var/lib/starrp-backup && date +%s > /var/lib/starrp-backup/started
echo "$BACKUP_CRON . /etc/starrp-backup.env && /usr/local/bin/backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2" > /etc/crontabs/root
echo "backup: agendado ($BACKUP_CRON, fuso ${TZ:-UTC}) para s3://$BACKUP_S3_BUCKET/${BACKUP_S3_PREFIX:-starrp}"

if [ "${BACKUP_ON_START:-0}" = "1" ]; then
  /usr/local/bin/backup.sh || echo "backup: a cópia da subida falhou (veja acima); o agendamento continua" >&2
fi
exec crond -f -l 6
