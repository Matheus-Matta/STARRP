"""CPF e CNPJ (inclusive o CNPJ alfanumérico): dígito verificador."""
import re

CNPJ_WEIGHTS = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def clean(value):
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def is_valid_cpf(value):
    digits = clean(value)
    if not re.fullmatch(r"\d{11}", digits) or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        if (total * 10 % 11) % 10 != int(digits[size]):
            return False
    return True


def is_valid_cnpj(value):
    """12 posições (números ou letras, valem pelo código ASCII menos 48) + 2 dígitos."""
    text = clean(value)
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", text) or text == text[0] * 14:
        return False
    for size in (12, 13):
        rest = sum((ord(c) - 48) * w for c, w in zip(text[:size], CNPJ_WEIGHTS[-size:], strict=True)) % 11
        if (0 if rest < 2 else 11 - rest) != int(text[size]):
            return False
    return True


def is_valid_document(value):
    return is_valid_cpf(value) or is_valid_cnpj(value)
