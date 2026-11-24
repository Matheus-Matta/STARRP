from config.settings.base import *  # noqa: F401,F403
from config.settings.base import ENVIRONMENT

if ENVIRONMENT != "development":
    raise RuntimeError(f"DJANGO_ENV={ENVIRONMENT} com config.settings.development: tire o DJANGO_SETTINGS_MODULE "
                       "do ambiente (o DJANGO_ENV escolhe as settings sozinho).")
