"""O worker e o beat do Celery sobem com as versões instaladas de kombu e redis-py.

O celery aceita qualquer kombu 5.x; o kombu 5.7 passou a exigir redis-py 6.1+ e, com o redis 5.0, o worker
morria ao conectar (VersionMismatch) num loop de reinício, sem nenhuma tarefa rodar. A imagem resolve as
dependências no build: este teste roda no workflow antes de publicar.
"""
from types import SimpleNamespace

from kombu.transport.redis import Channel


def test_kombu_aceita_o_redis_instalado():
    # _get_client é onde o kombu confere a versão do redis-py (antes de abrir qualquer conexão).
    client = Channel._get_client(SimpleNamespace(global_keyprefix=None))
    assert client is not None
