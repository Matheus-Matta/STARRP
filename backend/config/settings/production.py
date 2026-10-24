from config.settings.base import *  # noqa: F401,F403
from config.settings.base import MIDDLEWARE

if SECRET_KEY == "unsafe-dev-key":  # noqa: F405
    raise RuntimeError("Defina DJANGO_SECRET_KEY em produção.")

MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
