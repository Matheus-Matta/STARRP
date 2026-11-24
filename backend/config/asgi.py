from django.core.asgi import get_asgi_application

from config.environment import use_settings

use_settings()
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from starrp.core.ws_auth import JWTAuthMiddleware  # noqa: E402
from starrp.urls.websocket import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # Só abre WebSocket vindo de uma origem do ALLOWED_HOSTS (S-15: sem sequestro por outro site).
    "websocket": AllowedHostsOriginValidator(JWTAuthMiddleware(URLRouter(websocket_urlpatterns))),
})
