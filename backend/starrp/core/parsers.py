"""Leitura do corpo da requisição."""
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjectJSONParser(JSONParser):
    """JSON que é um objeto. Lista, texto, número ou `null` no corpo davam erro 500 nas views que leem
    `request.data.get(...)` (auditoria, B-03 a B-05); agora é 400."""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError("O corpo da requisição precisa ser um objeto JSON.")
        return data
