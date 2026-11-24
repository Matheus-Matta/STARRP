"""Os testes rodam com --nomigrations (tabelas direto dos models). Este garante que nenhum model mudou
sem a migration correspondente; aplicar todas do zero é o `npm run test:migrations`."""
from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_nenhum_model_sem_migration(settings):
    # O --nomigrations do pytest-django troca MIGRATION_MODULES por "sem migrations": aqui volta o real,
    # senão o makemigrations não enxerga as migrations do app e não confere nada.
    settings.MIGRATION_MODULES = {}
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
    except SystemExit as exit_:
        raise AssertionError(f"Model alterado sem migration (rode npm run makemigrations):\n{out.getvalue()}") from exit_
