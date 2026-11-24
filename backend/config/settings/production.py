"""Produção: escolhida por DJANGO_ENV=production (config/environment.py). Recusa subir sem o essencial."""
from decouple import Csv, config

from config.settings.base import *  # noqa: F401,F403
from config.settings.base import DATABASES, ENVIRONMENT, FRONTEND_URL, MIDDLEWARE, REDIS_URL, SECRET_KEY

if ENVIRONMENT != "production":
    raise RuntimeError(f"config.settings.production exige DJANGO_ENV=production (está {ENVIRONMENT!r}).")

if SECRET_KEY == "unsafe-dev-key" or len(SECRET_KEY) < 32:
    raise RuntimeError("Defina DJANGO_SECRET_KEY em produção (mínimo de 32 caracteres).")

# Segredos cifrados no banco (core/secrets.py): chave própria, nunca derivada do SECRET_KEY em produção.
from config.settings.base import FIELD_ENCRYPTION_KEY  # noqa: E402

if not FIELD_ENCRYPTION_KEY:
    raise RuntimeError("Defina FIELD_ENCRYPTION_KEY em produção (cifra do CSC, da senha do A1 e dos tokens).")
try:
    from cryptography.fernet import Fernet

    for _key in FIELD_ENCRYPTION_KEY.split(","):
        Fernet(_key.strip())
except ValueError as _error:
    raise RuntimeError("FIELD_ENCRYPTION_KEY inválida: gere com Fernet.generate_key().") from _error

# Banco: SEMPRE Postgres. Sem os dados de conexão não sobe (nada de cair no SQLite em silêncio).
_POSTGRES_VARS = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST")
_missing = [name for name in _POSTGRES_VARS if not config(name, default="")]
if _missing:
    raise RuntimeError(f"Produção usa sempre Postgres: defina {', '.join(_missing)}.")
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise RuntimeError("Produção usa sempre Postgres.")
# Redis: SEMPRE. Sem ele a camada de canais é em memória (com mais de um processo do uvicorn, a
# resposta da Cosmos gerada num processo não chega ao WebSocket aberto em outro) e o Celery roda as
# tarefas dentro da própria requisição (precificação/SEO travariam a tela).
if not REDIS_URL:
    raise RuntimeError("Produção usa sempre Redis: defina REDIS_URL (cache, WebSocket e fila do Celery).")

# E-mail: nunca no terminal em produção (o link de redefinição de senha ficaria no log do container). Sem
# EMAIL_HOST o app sobe, mas nada é enviado: o aviso sai na abertura.
from config.settings.base import EMAIL_BACKEND  # noqa: E402

if EMAIL_BACKEND.endswith("console.EmailBackend"):
    import warnings

    EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
    warnings.warn("EMAIL_HOST não definido: a redefinição de senha por e-mail não envia nada.", stacklevel=1)

# Schema da API (mapa de todas as rotas) só para a equipe (staff) em produção (S-13).
from config.settings.base import SPECTACULAR_SETTINGS  # noqa: E402

SPECTACULAR_SETTINGS = {**SPECTACULAR_SETTINGS, "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"]}

# Pool de conexões do psycopg (Django 5.1+). Em ASGI as views síncronas rodam num pool de threads e
# conexão persistente (CONN_MAX_AGE > 0) fica presa em cada thread até estourar o max_connections do
# Postgres; o pool reaproveita poucas conexões entre as requisições. O pool exige CONN_MAX_AGE = 0.
# Conta: processos do uvicorn (WEB_CONCURRENCY) × POSTGRES_POOL_MAX (+ worker/beat do Celery) < max_connections.
DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["CONN_HEALTH_CHECKS"] = False
DATABASES["default"]["OPTIONS"] = {"pool": {
    "min_size": config("POSTGRES_POOL_MIN", default=2, cast=int),
    "max_size": config("POSTGRES_POOL_MAX", default=10, cast=int),
    "timeout": config("POSTGRES_POOL_TIMEOUT", default=10, cast=int),
}}

# Arquivos estáticos: WhiteNoise serve o que o collectstatic juntou em STATIC_ROOT, comprimido (gzip/brotli)
# e com hash no nome (cache longo no navegador). Os envios (/media) continuam no disco (MEDIA_ROOT).
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 365

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True

# Login SEMPRE por cookie em HTTPS: Secure (só trafega em https), httpOnly (o JS não lê) e SameSite=Strict
# (outro site não manda o cookie junto; o app e a API estão na mesma origem atrás do Caddy). Só troque
# para "Lax"/"None" se o app ficar em outro domínio que a API (aí também DJANGO_CORS_ALLOWED_ORIGINS).
AUTH_COOKIE_SECURE = SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
AUTH_COOKIE_SAMESITE = config("AUTH_COOKIE_SAMESITE", default="Strict")
if AUTH_COOKIE_SAMESITE not in {"Strict", "Lax", "None"}:
    raise RuntimeError("AUTH_COOKIE_SAMESITE deve ser Strict, Lax ou None.")
# App e API na mesma origem (Caddy): sem variável, CORS e CSRF confiam só no FRONTEND_URL (não no
# localhost:5173 do desenvolvimento).
CORS_ALLOWED_ORIGINS = config("DJANGO_CORS_ALLOWED_ORIGINS", default=FRONTEND_URL, cast=Csv())
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default=",".join(CORS_ALLOWED_ORIGINS), cast=Csv())
_http = [origin for origin in (FRONTEND_URL, *CORS_ALLOWED_ORIGINS, *CSRF_TRUSTED_ORIGINS)
         if origin and not origin.startswith("https://")]
if _http:
    raise RuntimeError(f"Produção é só HTTPS (cookie Secure não trafega em http): corrija {', '.join(_http)} "
                       "em FRONTEND_URL / DJANGO_CORS_ALLOWED_ORIGINS / DJANGO_CSRF_TRUSTED_ORIGINS.")

# HTTPS sempre (o API_URL já é exigido https): o navegador nem tenta http depois da primeira visita.
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
# http → https também no Django (o proxy já redireciona; isto cobre acesso direto). O healthcheck do
# container fala http com o próprio processo, então /health/ fica de fora.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_REDIRECT_EXEMPT = [r"^health/$"]

# Erros de produção no Sentry (opcional): sem SENTRY_DSN, nada é enviado. Sem dados pessoais (PII).
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=config("SENTRY_ENVIRONMENT", default="production"),
        release=config("APP_VERSION", default="") or None,
        send_default_pii=False,
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.0, cast=float),
    )
