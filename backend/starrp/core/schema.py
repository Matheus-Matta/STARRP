"""Extensões do drf-spectacular (documentação OpenAPI)."""
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class CookieJWTScheme(SimpleJWTScheme):
    """O Swagger trata o nosso JWT (header ou cookie) como Bearer."""

    target_class = "starrp.core.authentication.CookieJWTAuthentication"
    name = "jwtAuth"
