"""Acesso dos usuários: e-mails que não podem segurar (nem denunciar pelo tempo) a requisição."""
import logging

from celery import shared_task

from starrp.services import password_reset

logger = logging.getLogger(__name__)


@shared_task(name="starrp.send_password_reset", ignore_result=True)
def send_password_reset(email):
    try:
        password_reset.send(email)
    except Exception:  # noqa: BLE001 — servidor de e-mail fora: a pessoa pede de novo; o erro fica no log/Sentry
        logger.exception("Falha ao enviar o e-mail de redefinição de senha.")
