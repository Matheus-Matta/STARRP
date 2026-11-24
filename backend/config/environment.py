"""Qual módulo de settings carregar. `DJANGO_ENV` (variável de ambiente ou o `.env` da raiz) decide:
development → config.settings.development, production → config.settings.production.

Um `DJANGO_SETTINGS_MODULE` já definido no ambiente vence (o pytest usa config.settings.test)."""
import os

SETTINGS_BY_ENV = {"development": "config.settings.development", "production": "config.settings.production"}


def use_settings():
    if os.environ.get("DJANGO_SETTINGS_MODULE"):
        return
    from decouple import config

    env = config("DJANGO_ENV", default="development")
    # Valor inválido cai no development, e o base.py recusa com a mensagem certa.
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS_BY_ENV.get(env, SETTINGS_BY_ENV["development"])
