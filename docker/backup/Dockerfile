# Backup do Starrp: pg_dump do Postgres + fotos (media) + certificados cifrados (private), cifrado com a
# senha do .env e enviado a um armazenamento S3 (AWS, MinIO, Backblaze B2, Cloudflare R2, Wasabi...).
# A versão do pg_dump é a mesma do banco (postgres:16): dump de versão diferente pode não restaurar.
FROM postgres:16-alpine
RUN apk add --no-cache aws-cli openssl tar gzip tzdata
COPY backup.sh restore.sh entrypoint.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/backup.sh /usr/local/bin/restore.sh /usr/local/bin/entrypoint.sh \
    && mkdir -p /var/lib/starrp-backup
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
HEALTHCHECK --interval=30m --timeout=10s --start-period=10m \
  CMD /usr/local/bin/backup.sh --healthcheck
