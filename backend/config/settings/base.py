"""Settings comuns. `DJANGO_ENV` (development | production) é a ÚNICA chave do
DEBUG: no StarChef `DJANGO_ENV` e `DJANGO_DEBUG` divergiam e quebravam o login."""
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parents[2]

ENVIRONMENT = config("DJANGO_ENV", default="development")
if ENVIRONMENT not in {"development", "production"}:
    raise RuntimeError(f"DJANGO_ENV inválido: {ENVIRONMENT!r} (use development ou production)")
DEBUG = ENVIRONMENT == "development"

SECRET_KEY = config("DJANGO_SECRET_KEY", default="unsafe-dev-key")
ALLOWED_HOSTS = [*config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv()), "localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "channels",
    "simple_history",
    "starrp",
]

MIDDLEWARE = [
    "starrp.core.envelope.ApiErrorEnvelopeMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Guarda a requisição: o histórico pega o usuário (o DRF autentica o JWT e põe em request.user).
    "simple_history.middleware.HistoryRequestMiddleware",
    "starrp.core.middleware.TenantMiddleware",
    # Depois do tenant: a deduplicação é por conta.
    "starrp.core.idempotency.IdempotencyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"
LOGIN_URL = "/admin/login/"
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173").rstrip("/")
API_URL = config("API_URL", default="")

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

if config("POSTGRES_DB", default=""):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("POSTGRES_DB"),
            "USER": config("POSTGRES_USER", default="starrp"),
            "PASSWORD": config("POSTGRES_PASSWORD", default="starrp"),
            "HOST": config("POSTGRES_HOST", default="localhost"),
            "PORT": config("POSTGRES_PORT", default="5432"),
            "CONN_MAX_AGE": config("POSTGRES_CONN_MAX_AGE", default=60, cast=int),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / config("SQLITE_DB_NAME", default="db.sqlite3")),
            "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
        }
    }

REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}}
    CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
    CELERY_TASK_ALWAYS_EAGER = False
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    CELERY_BROKER_URL = "memory://"
    CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_BEAT_SCHEDULE = {
    # Notas de entrada (DF-e): a SEFAZ bloqueia quem consulta antes de 1 hora sem novidade.
    "sync-dfe": {"task": "starrp.sync_dfe", "schedule": 60 * 65},
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("starrp.core.authentication.CookieJWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "starrp.core.permissions.HasAccount",
        "starrp.core.permissions.HasModule",
        "starrp.core.permissions.HasViewPermission",
    ),
    "DEFAULT_PAGINATION_CLASS": "starrp.core.pagination.StandardPagination",
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "starrp.core.ordering.ColumnOrderingFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "starrp.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.AnonRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("THROTTLE_RATE_ANON", default="60/min"),
        "login": config("THROTTLE_RATE_LOGIN", default="10/min"),
        "password_reset": config("THROTTLE_RATE_PASSWORD_RESET", default="5/min"),
        "approval": config("THROTTLE_RATE_APPROVAL", default="10/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=config("JWT_ACCESS_HOURS", default=12, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
JWT_AUTH_COOKIE = "srp_access"
JWT_AUTH_REFRESH_COOKIE = "srp_refresh"
AUTH_COOKIE_SECURE = not DEBUG
AUTH_COOKIE_SAMESITE = "Lax"

SPECTACULAR_SETTINGS = {
    "TITLE": "Starrp API",
    "DESCRIPTION": "ERP de varejo: PDV desktop/móvel, estoque, fiscal e financeiro.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = config("DJANGO_CORS_ALLOWED_ORIGINS", default="http://localhost:5173", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key", "x-terminal-id", "x-store-id", "x-account-id")
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_PATH = "/admin/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
IMAGE_UPLOAD_MAX_BYTES = config("IMAGE_UPLOAD_MAX_BYTES", default=8 * 1024 * 1024, cast=int)

# Fiscal: emissor ACBrLib da própria instalação (loja ou nuvem).
ACBRLIB_URL = config("ACBRLIB_URL", default="").rstrip("/")
ACBRLIB_TOKEN = config("ACBRLIB_TOKEN", default="")
ACBRLIB_TIMEOUT = config("ACBRLIB_TIMEOUT", default=40, cast=int)

# Sincronização: papel desta instalação (vazio = desligada).
SYNC_NODE_TYPE = config("SYNC_NODE_TYPE", default="")  # "LOCAL" | "CLOUD"
SYNC_ENVIRONMENT = config("SYNC_ENVIRONMENT", default="development")

EMAIL_BACKEND = config("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DJANGO_DEFAULT_FROM_EMAIL", default="Starrp <no-reply@localhost>")
PASSWORD_RESET_TIMEOUT_MINUTES = 30

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
}
