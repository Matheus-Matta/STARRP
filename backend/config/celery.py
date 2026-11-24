from celery import Celery

from config.environment import use_settings

use_settings()

app = Celery("starrp")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["starrp.tasks"])
