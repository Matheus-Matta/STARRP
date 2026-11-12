"""Tarefas Celery. Importadas aqui para o autodiscover registrar."""
from starrp.tasks.batches import batch_step  # noqa: F401
from starrp.tasks.dfe import sync_dfe  # noqa: F401
from starrp.tasks.cosmos import cosmos_daily_digest, cosmos_supervision  # noqa: F401
from starrp.tasks.market import price_read, price_tracking  # noqa: F401
from starrp.tasks.seo import seo_read  # noqa: F401
