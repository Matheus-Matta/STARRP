"""Link de redefinição de senha: só o hash é gravado, e o link vale por pouco tempo."""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from starrp.models import PasswordResetRequest


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def invalidate(user):
    """Os links ainda abertos deste usuário deixam de valer."""
    PasswordResetRequest.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())


#: Pedidos por usuário na última hora: acima disso ninguém recebe mais e-mail (o limite por IP não segura um botnet).
MAX_PER_HOUR = 5


def send(email):
    """Um e-mail para cada login ativo com este endereço (a mesma pessoa pode ter login em mais de uma conta)."""
    users = get_user_model().objects.filter(email__iexact=email, is_active=True).exclude(email="")
    sent = 0
    for user in users.order_by("pk")[:10]:
        hour_ago = timezone.now() - timedelta(hours=1)
        if PasswordResetRequest.objects.filter(user=user, created_at__gte=hour_ago).count() >= MAX_PER_HOUR:
            continue
        invalidate(user)  # só o link mais novo vale
        token = secrets.token_urlsafe(32)
        PasswordResetRequest.objects.create(
            user=user, token_hash=token_hash(token),
            expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_TIMEOUT_MINUTES),
        )
        link = f"{settings.FRONTEND_URL.rstrip('/')}/redefinir-senha#token={token}"  # depois do #: fora dos logs
        send_mail("Redefinição de senha", (
            f"Para criar uma nova senha do usuário {user.get_username()} acesse: {link}\n\n"
            f"O link vale por {settings.PASSWORD_RESET_TIMEOUT_MINUTES} minutos. Se não foi você, ignore este e-mail."
        ), None, [user.email])
        sent += 1
    return sent
