from django.urls import path

from starrp.views.cosmos_socket import CosmosConsumer

# Sob /api/ para passar pelo mesmo proxy da API (Vite em desenvolvimento, Nginx em produção).
websocket_urlpatterns = [
    path("api/v1/ws/cosmos/", CosmosConsumer.as_asgi()),
]
