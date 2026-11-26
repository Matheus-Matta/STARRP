"""Leitura do corpo da requisição."""
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


def _has_nul(data):
    """O caractere nulo: o Postgres não o guarda em texto nem em JSON (virava erro 500)."""
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if "\x00" in value:
                return True
        elif isinstance(value, dict):
            pending += [*value.keys(), *value.values()]
        elif isinstance(value, list):
            pending += value
    return False


class ObjectJSONParser(JSONParser):
    """JSON que é um objeto. Lista, texto, número ou `null` no corpo davam erro 500 nas views que leem
    `request.data.get(...)` (auditoria, B-03 a B-05); agora é 400."""

    def parse(self, stream, media_type=None, parser_context=None):
        try:
            data = super().parse(stream, media_type, parser_context)
        except RecursionError:
            raise ParseError("JSON aninhado demais.") from None
        if not isinstance(data, dict):
            raise ParseError("O corpo da requisição precisa ser um objeto JSON.")
        if _has_nul(data):
            raise ParseError("O texto tem um caractere inválido.")
        return data
