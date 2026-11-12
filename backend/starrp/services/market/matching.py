"""Pareamento: a oferta do mercado é o MESMO produto que o nosso?

Errar aqui é pior que não achar: um preço de produto diferente vira sugestão errada.

- `score`, oferta da busca por título: o nosso título (já com marca e modelo, ver `full_title`) vira partes (`title_items`).
  As palavras valem 85% da nota e os trechos em sequência, 15%: anúncio com todas as palavras em outra ordem fica com 85.
  Erro de digitação conta como a mesma palavra ("caemmum" = "caemmun", ver `_same_word`); número e modelo, nunca.
- `score_by_code`, oferta da busca por EAN: outro critério, porque o título achado não vem da mesma busca:
  50% título (palavras em comum) + 25% marca + 25% modelo; sem código de modelo, 75% título + 25% marca.
- Nos dois: GTIN igual na oferta é o mesmo produto (nota 100), e medida diferente (500 ml × 1 l, 110 V × 220 V),
  kit/caixa quando o nosso é unitário, combo ("Coca + Sprite"), acessório (capa, garrafa vazia) ou outra versão
  (zero, diet, light, retornável) dão nota 0, nunca contam.
"""
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

# Palavra de vitrine que não diz nada sobre o produto.
NOISE = {
    "de", "da", "do", "das", "dos", "e", "em", "com", "para", "p", "c", "a", "o", "as", "os", "un", "und", "unid",
    "novo", "nova", "original", "promocao", "oferta", "frete", "gratis", "envio", "imediato", "full", "lacrado",
    "garantia", "nf", "nota", "fiscal", "pronta", "entrega", "top", "melhor", "preco", "barato",
}
UNITS = {
    "ml": ("ml", 1), "l": ("ml", 1000), "lt": ("ml", 1000), "lts": ("ml", 1000), "litro": ("ml", 1000),
    "litros": ("ml", 1000),
    "g": ("g", 1), "gr": ("g", 1), "kg": ("g", 1000), "mg": ("mg", 1),
    "w": ("w", 1), "v": ("v", 1), "gb": ("gb", 1), "tb": ("gb", 1024), "mah": ("mah", 1),
    "mm": ("mm", 1), "cm": ("mm", 10), "m": ("mm", 1000), "pol": ("pol", 1), "polegadas": ("pol", 1),
}
MEASURE = re.compile(r"(\d+(?:[.,]\d+)?)\s?(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b")
PACK = re.compile(r"\b(?:kit|caixa|pack|fardo|combo)\b(?:\s+(?:com|c)?\s*(\d+))?|\b(\d+)\s?(?:unidades|unid|un|pecas|pcs)\b")
VERSION = {"zero", "diet", "light", "retornavel"}  # o mesmo nome e a mesma medida, mas outro produto
ACCESSORY = {"capa", "capinha", "pelicula", "suporte", "refil", "vazia", "vazio", "casco", "vasilhame"}  # é para o produto, não ele
WORDS_WEIGHT = Decimal("85")
PIECES_WEIGHT = Decimal("15")
TYPO_MIN_LENGTH = 5
TYPO_MIN_RATIO = 0.85


def normalize(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9.,]+", " ", text).strip()


def _measure(number, unit):
    kind, factor = UNITS[unit]
    return kind, (Decimal(number.replace(",", ".")) * factor).normalize()


def words(text):
    """As palavras em ordem, sem acento e sem caixa. "2L", "2 litros" e "2,00 lt" viram a mesma palavra."""
    def same_word(match):
        kind, value = _measure(match.group(1), match.group(2))
        return f"{value:f}{kind}"

    joined = MEASURE.sub(same_word, normalize(text).replace("sem acucar", "zero"))
    return [word for word in (t.strip(".,") for t in joined.split()) if word]


def tokens(text):
    return set(words(text)) - NOISE


def _contains(whole, part):
    """Palavras inteiras e na mesma ordem: "5" não está em "150 cm" e "porta" não está em "portas"."""
    return f" {' '.join(part)} " in f" {' '.join(whole)} "


def _same_word(ours, theirs):
    """A mesma palavra ou erro de digitação. Palavra curta, número e modelo (A54 × A34) só valem iguais."""
    if ours == theirs:
        return True
    if min(len(ours), len(theirs)) < TYPO_MIN_LENGTH or ours[0] != theirs[0] or re.search(r"\d", ours + theirs):
        return False
    return SequenceMatcher(None, ours, theirs).ratio() >= TYPO_MIN_RATIO


def _has_piece(found, piece):
    """O trecho em sequência no título achado, aceitando erro de digitação em cada palavra."""
    size = len(piece)
    return any(all(_same_word(a, b) for a, b in zip(piece, found[start:start + size], strict=True))
               for start in range(len(found) - size + 1))


def full_title(name, *parts):
    """O título do produto, com a marca e o modelo que o nome ainda não cita. É o que vai para a busca e o que é comparado."""
    title = name
    for part in parts:
        if part and not _contains(words(title), words(part)):
            title = f"{title} {part}"
    return title


def title_items(title):
    """As partes do título: cada palavra, os pedaços a cada 2 e a cada 3 espaços, e o título inteiro, sem repetir.

    GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUM → GUARDA, ROUPA, SOPHIA, 5, PORTAS, CAEMMUM,
    GUARDA ROUPA SOPHIA, 5 PORTAS CAEMMUM, GUARDA ROUPA SOPHIA 5, PORTAS CAEMMUM e o título inteiro."""
    all_words = words(title)
    pieces = [all_words[i:i + 1] for i in range(len(all_words))]
    for size in (3, 4):  # 2 espaços separam 3 palavras; 3 espaços, 4
        pieces += [all_words[i:i + size] for i in range(0, len(all_words), size)]
    pieces.append(all_words)
    return list(dict.fromkeys(" ".join(piece) for piece in pieces if piece))


def measures(text):
    """{"ml": {500}, "v": {220}}: cada grandeza com os valores citados (já na mesma unidade)."""
    out = {}
    for number, unit in MEASURE.findall(normalize(text)):
        kind, value = _measure(number, unit)
        out.setdefault(kind, set()).add(value)
    return out


def pack_size(text):
    """Quantas unidades a oferta tem (kit com 3 → 3); 1 quando não fala."""
    for match in PACK.finditer(normalize(text)):
        number = next((g for g in match.groups() if g), None)
        if number:
            return int(number)
        return 2  # "kit"/"caixa" sem número: mais de uma, quantidade desconhecida
    return 1


def models(text):
    """Códigos de modelo: palavra com letra E número (A54, XJ200). Medida (128gb, 500ml) não é modelo:
    ela já tem a trava própria."""
    return {t for t in tokens(text) if re.search(r"\d", t) and re.search(r"[a-z]", t) and not MEASURE.fullmatch(t)}


def _gtins(codes):
    """Só os GTIN de verdade (8 a 14 dígitos), sem zero à esquerda: 07891... = 7891..."""
    return {c.lstrip("0") for c in (str(c).strip() for c in codes) if c.isdigit() and 8 <= len(c) <= 14}


@dataclass
class Ours:
    title: str
    brand: str = ""
    gtins: tuple = ()
    reference: str = ""


@dataclass
class Match:
    score: Decimal
    reason: str


def _never_or_same(ours, title, gtins):
    """O que decide sem olhar a nota: trava dura (nota 0) ou GTIN igual (nota 100). `None` = segue para a nota."""
    mine, theirs = measures(ours.title), measures(title)
    for kind, values in mine.items():
        if kind in theirs and not values & theirs[kind]:
            return Match(Decimal("0"), f"Medida diferente ({kind}).")
    if pack_size(title) != pack_size(ours.title):
        return Match(Decimal("0"), "Quantidade/kit diferente.")
    theirs_tokens, our_tokens = tokens(title), tokens(ours.title)
    if theirs_tokens & VERSION != our_tokens & VERSION:
        return Match(Decimal("0"), "Versão diferente (zero, diet, light ou retornável).")
    if (theirs_tokens & ACCESSORY) - our_tokens:
        return Match(Decimal("0"), "Acessório ou embalagem, não o produto.")
    if re.search(r"\s\+\s", str(title or "")) and not re.search(r"\s\+\s", ours.title):
        return Match(Decimal("0"), "Combo com outro produto.")

    if _gtins(ours.gtins) & _gtins(gtins):
        return Match(Decimal("100"), "Mesmo código de barras (GTIN).")
    return None


def score(ours: Ours, title, *, gtins=()):
    """Oferta da busca por título: as palavras do nosso título que o achado tem (85%) e os trechos em sequência (15%)."""
    decided = _never_or_same(ours, title, gtins)
    if decided:
        return decided
    items, found = title_items(ours.title), words(title)
    if not items or not found:
        return Match(Decimal("0"), "Sem título para comparar.")
    pieces = [item.split() for item in items if " " in item]
    singles = [item for item in items if " " not in item]
    # "de", "original", "novo"... não dizem qual é o produto: não tiram nota de quem não escreveu.
    key_words = [word for word in singles if word not in NOISE] or singles
    missing = [word for word in key_words if not any(_same_word(word, other) for other in found)]
    typos = [word for word in key_words if word not in found and word not in missing]
    words_hit = len(key_words) - len(missing)
    pieces_hit = sum(_has_piece(found, piece) for piece in pieces)
    if pieces:
        total = Decimal(words_hit) * WORDS_WEIGHT / len(key_words) + Decimal(pieces_hit) * PIECES_WEIGHT / len(pieces)
    else:
        total = Decimal(words_hit) * 100 / len(key_words)
    reason = f"{words_hit} de {len(key_words)} palavras do título, {pieces_hit} de {len(pieces)} trechos em sequência."
    if missing:
        reason += " Faltou: " + ", ".join(missing) + "."
    if typos:
        reason += " Escrita parecida: " + ", ".join(typos) + "."
    return Match(total.quantize(Decimal("0.01")), reason)


def score_by_code(ours: Ours, title, *, brand="", gtins=(), model=""):
    """Oferta da busca por EAN: o resultado traz produto errado junto, então pesa título, marca e modelo."""
    decided = _never_or_same(ours, title, gtins)
    if decided:
        return decided
    a, b = tokens(ours.title), tokens(title)
    if not a or not b:
        return Match(Decimal("0"), "Sem título para comparar.")
    common = a & b
    title_score = Decimal(len(common)) / len(a) * Decimal("0.6") + Decimal(len(common)) / len(a | b) * Decimal("0.4")

    if ours.brand:
        brand_tokens = tokens(ours.brand)
        brand_score = Decimal(1) if brand_tokens and (brand_tokens <= tokens(brand) or brand_tokens <= b) else Decimal(0)
    else:
        brand_score = Decimal("0.5")

    parts = [f"título {int(title_score * 100)}%", "marca " + ("ok" if brand_score == 1 else "?" if brand_score else "não")]
    our_models = models(f"{ours.title} {ours.reference}")
    if our_models:
        model_score = Decimal(len(our_models & models(f"{title} {model}"))) / len(our_models)
        total = title_score * 50 + brand_score * 25 + model_score * 25
        parts.append(f"modelo {int(model_score * 100)}%")
    else:  # sem código de modelo (shampoo, arroz): o peso do modelo vai para o título
        total = title_score * 75 + brand_score * 25
    total = total.quantize(Decimal("0.01"))
    return Match(min(total, Decimal("100")), ", ".join(parts).capitalize() + ".")
