# Contexto de build = RAIZ do monorepo (o admin reusa a marca de frontend/public):
#   docker build -f backend/Dockerfile -t starrp-backend .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_ENV=production
# Versão da tag (backend-v1.0.1 → 1.0.1), pelo workflow de release: vira a release do Sentry.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
WORKDIR /app
COPY backend/requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt
# STATICFILES_DIRS = BASE_DIR.parent/frontend/public → /frontend/public no container.
COPY frontend/public/ /frontend/public/
COPY backend/ .
# collectstatic não abre o banco nem o Redis: valores só para passar nas checagens do production.py.
RUN DJANGO_SECRET_KEY=collectstatic-build-key-0123456789abcdef FRONTEND_URL=https://build.invalid \
    POSTGRES_DB=build POSTGRES_USER=build POSTGRES_PASSWORD=build POSTGRES_HOST=build \
    REDIS_URL=redis://build:6379/0 FIELD_ENCRYPTION_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY= \
    python manage.py collectstatic --noinput
# Sem root (S-16): o processo roda como `app` (uid 10001); só media/ e private/ (volumes) são graváveis por ele.
# Volume criado antes desta versão (dono root), antes do 1º up: docker compose run --rm --no-deps -u root backend-blue chown -R app /app/media /app/private
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/media /app/private && chown -R app:app /app/media /app/private
USER app
EXPOSE 8000
# Servidor: uvicorn assíncrono (start-web.sh). WEB_CONCURRENCY = processos; cada um atende muitas
# conexões ao mesmo tempo (event loop + uma thread por requisição síncrona do Django).
ENV WEB_CONCURRENCY=3
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py sync_permissions && exec sh ./start-web.sh"]
