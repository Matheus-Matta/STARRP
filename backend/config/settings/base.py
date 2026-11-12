"""Settings comuns. `DJANGO_ENV` (development | production) é a ÚNICA chave do
DEBUG: no StarChef `DJANGO_ENV` e `DJANGO_DEBUG` divergiam e quebravam o login."""
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab
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
# Sem Redis não há worker: a leitura de preço pedida pela tela roda numa thread, para não travar a requisição.
PRICE_READ_IN_THREAD = not REDIS_URL
# Rodadas (precificação e SEO): o tamanho do lote e os segundos de pausa entre um lote e outro.
PRICE_BATCH_SIZE = config("PRICE_BATCH_SIZE", default=10, cast=int)
PRICE_BATCH_PAUSE = config("PRICE_BATCH_PAUSE", default=30, cast=int)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_BEAT_SCHEDULE = {
    # Notas de entrada (DF-e): a SEFAZ bloqueia quem consulta antes de 1 hora sem novidade.
    "sync-dfe": {"task": "starrp.sync_dfe", "schedule": 60 * 65},
    # Cosmos: varredura da supervisão (cadastros com erro, descontos e cancelamentos fora do padrão).
    "cosmos-supervision": {"task": "starrp.cosmos_supervision", "schedule": 60 * 30},
    # Cosmos: resumo do dia anterior para quem supervisiona (não gasta tokens).
    "cosmos-daily-digest": {"task": "starrp.cosmos_daily_digest", "schedule": crontab(hour=7, minute=0)},
    # Precificação: de hora em hora lê a próxima leva de cada conta (a frequência por produto é da conta).
    "price-tracking": {"task": "starrp.price_tracking", "schedule": crontab(minute=20)},
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
# Reutiliza a identidade oficial do frontend no admin (logos e favicons),
# evitando manter duas cópias da marca em lugares diferentes.
STATICFILES_DIRS = [BASE_DIR.parent / "frontend" / "public"]
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

# Cosmos (assistente de IA): OpenAI pela API. Sem a chave, o widget avisa que está desligada.
OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
OPENAI_BASE_URL = config("OPENAI_BASE_URL", default="") or None
OPENAI_MODEL = config("OPENAI_MODEL", default="gpt-5-mini")
OPENAI_TIMEOUT = config("OPENAI_TIMEOUT", default=90, cast=int)
# Roteamento por custo (services/cosmos/router.py): turno simples (saudação, comentar o resultado de uma
# confirmação, resumir o histórico) vai ao modelo leve; planilha/lote vai ao forte (vazio = OPENAI_MODEL).
OPENAI_MODEL_LIGHT = config("OPENAI_MODEL_LIGHT", default="gpt-5-nano")
OPENAI_MODEL_HEAVY = config("OPENAI_MODEL_HEAVY", default="")
# Modelos de raciocínio (gpt-5, o-series): minimal | low | medium | high. "low" = mais rápido e barato.
OPENAI_REASONING_EFFORT = config("OPENAI_REASONING_EFFORT", default="low")
# Voltas modelo ⇄ ferramentas por mensagem (cada consulta à API é uma volta).
COSMOS_MAX_STEPS = config("COSMOS_MAX_STEPS", default=12, cast=int)
# Mensagens por minuto de um mesmo usuário (segura clique repetido e uso abusivo).
COSMOS_MESSAGES_PER_MINUTE = config("COSMOS_MESSAGES_PER_MINUTE", default=20, cast=int)
# Teto de saída por chamada (inclui o raciocínio). O modelo leve usa um terço.
COSMOS_MAX_OUTPUT_TOKENS = config("COSMOS_MAX_OUTPUT_TOKENS", default=4000, cast=int)
# Janela do histórico: as últimas N falas do usuário vão inteiras; o que é mais antigo vira um resumo curto.
COSMOS_HISTORY_TURNS = config("COSMOS_HISTORY_TURNS", default=8, cast=int)

# Precificação (preço comparado com o mercado): chaves da PLATAFORMA das fontes com cadastro.
# Vazio = a fonte fica indisponível; pesquisa da equipe e Open Prices não precisam de chave.
# Teto de consultas por dia, somando todas as contas (o plano gratuito da SerpApi tem 250 por mês).
SERPAPI_KEY = config("SERPAPI_KEY", default="")
BLUESOFT_COSMOS_TOKEN = config("BLUESOFT_COSMOS_TOKEN", default="")
# Ferramenta própria de busca no Google Shopping (projeto search-shop): a fonte precisa dos dois.
SHOPPING_SEARCH_URL = config("SHOPPING_SEARCH_URL", default="")
SHOPPING_SEARCH_TOKEN = config("SHOPPING_SEARCH_TOKEN", default="")
# SERP API da Bright Data: a chave e o nome da zona. A conta pode ter os dela (admin do Django).
BRIGHTDATA_API_KEY = config("BRIGHTDATA_API_KEY", default="")
BRIGHTDATA_ZONE = config("BRIGHTDATA_ZONE", default="")
PRICE_DAILY_LIMITS = {"serpapi": config("PRICE_SERPAPI_DAILY", default=8, cast=int),
                      "google_shopping": config("PRICE_SHOPPING_SEARCH_DAILY", default=500, cast=int),
                      "brightdata": config("PRICE_BRIGHTDATA_DAILY", default=100, cast=int),
                      "cosmos": config("PRICE_COSMOS_DAILY", default=20, cast=int)}
# Analítico de SEO: volume de busca pelo Google Ads (KeywordPlanIdeaService). A conta pode ter as dela (admin do Django).
GOOGLE_ADS_API_VERSION = config("GOOGLE_ADS_API_VERSION", default="v26")
GOOGLE_ADS_CLIENT_ID = config("GOOGLE_ADS_CLIENT_ID", default="")
GOOGLE_ADS_CLIENT_SECRET = config("GOOGLE_ADS_CLIENT_SECRET", default="")
GOOGLE_ADS_REFRESH_TOKEN = config("GOOGLE_ADS_REFRESH_TOKEN", default="")
GOOGLE_ADS_CUSTOMER_ID = config("GOOGLE_ADS_CUSTOMER_ID", default="")
GOOGLE_ADS_LOGIN_CUSTOMER_ID = config("GOOGLE_ADS_LOGIN_CUSTOMER_ID", default="")
GOOGLE_ADS_DEVELOPER_TOKEN = config("GOOGLE_ADS_DEVELOPER_TOKEN", default="")  # só projeto antigo: descontinuado em 09/2026
PRICE_TRACKING_BATCH = config("PRICE_TRACKING_BATCH", default=200, cast=int)

EMAIL_BACKEND = config("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DJANGO_DEFAULT_FROM_EMAIL", default="Starrp <no-reply@localhost>")
PASSWORD_RESET_TIMEOUT_MINUTES = 30

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
    # O Django já tem um handler de console no logger "django"; sem isto cada linha (ex.: o acesso
    # HTTP do runserver/Daphne) saía duas vezes — a dele e a da raiz.
    "loggers": {"django": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO"),
                           "propagate": False}},
}
