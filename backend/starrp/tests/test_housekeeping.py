from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from starrp.models import IdempotencyRecord
from starrp.services import housekeeping


def _record(ctx, key, days_ago):
    record = IdempotencyRecord.objects.create(account=ctx.account, key=key, method="POST", path="/x/",
                                              request_fingerprint="f", status_code=201, response_body={})
    IdempotencyRecord.objects.filter(pk=record.pk).update(created_at=timezone.now() - timedelta(days=days_ago))


def test_limpa_idempotencia_antiga_e_tokens_vencidos(ctx):
    _record(ctx, "velha", 45)
    _record(ctx, "nova", 2)
    RefreshToken.for_user(ctx.admin)  # válido
    expired = RefreshToken.for_user(ctx.admin)
    OutstandingToken.objects.filter(jti=expired["jti"]).update(expires_at=timezone.now() - timedelta(days=1))

    result = housekeeping.run()

    assert result["idempotency"] == 1 and result["jwt_tokens"] == 1
    assert list(IdempotencyRecord.objects.values_list("key", flat=True)) == ["nova"]
    assert not OutstandingToken.objects.filter(jti=expired["jti"]).exists()
