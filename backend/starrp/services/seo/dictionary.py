"""Dicionário comercial: abreviação de cadastro → como o cliente escreve na busca.

O contexto importa: "5P" é "5 Portas" num guarda-roupa, não em outro produto, e "500G" é medida. Por isso cada regra diz
onde vale. Nunca acrescenta atributo que o cadastro não tem ("casal", "MDF"...): só expande o que já está escrito.
Sinônimo correto ("roupeiro" × "guarda-roupa") não é erro: quem decide é o volume de busca (ver `SYNONYMS`).
"""
import re

WITH_DOORS = re.compile(r"\b(guarda.?roupas?|roupeiro|arm[aá]rio|balc[aã]o|sapateira|estante|cozinha|gabinete|multiuso|gr)\b", re.I)
GR_CONTEXT = re.compile(r"\b(casal|solteiro|solt|portas?|\d+\s?p)\b", re.I)
TV_FURNITURE = re.compile(r"\b(rack|painel|estante)\b", re.I)

SMALL_WORDS = {"de", "da", "do", "das", "dos", "e", "em", "com", "para", "por", "sem", "a", "o", "as", "os", "na", "no"}
KEEP_UPPER = {"tv", "mdf", "led", "usb", "hd", "lcd", "uv", "gps", "wifi", "pvc", "inox"}

# (termo do cadastro, termo equivalente): a troca só é sugerida com dados de busca a favor.
SYNONYMS = (("roupeiro", "guarda-roupa"), ("refri", "refrigerante"))
# O sinônimo precisa ter ao menos este múltiplo das buscas do termo cadastrado.
SYNONYM_MIN_RATIO = 2

AMBIGUOUS = {"cj": "\"Cj\" pode ser conjunto ou conjugado: confirme e escreva por extenso."}


def _plural(number, one, many):
    return f"{number} {one if number == '1' else many}"


def _rules():
    return (
        # (padrão, troca, contexto que precisa existir no texto, nome do problema)
        (r"^gr\b", "Guarda-Roupa", GR_CONTEXT, "Sigla \"GR\" pouco descritiva"),
        (r"\b(\d+)\s?p\b", lambda m: _plural(m[1], "Porta", "Portas"), WITH_DOORS, "Abreviação de portas"),
        (r"\b(\d+)\s?g\b", lambda m: _plural(m[1], "Gaveta", "Gavetas"), WITH_DOORS, "Abreviação de gavetas"),
        (r"\barm[aá]rio\s+coz\b", "Armário de Cozinha", None, "Abreviação da categoria"),
        (r"\brack\s+tv\b", "Rack para TV", None, "Falta a preposição"),
        (r"\bmesa\s+jantar\b", "Mesa de Jantar", None, "Falta a preposição"),
        (r"\b(?:c/\s?|com\s+)?(\d+)\s?cad\b", lambda m: "com " + _plural(m[1], "Cadeira", "Cadeiras"), re.compile(r"\bmesa\b", re.I),
         "Abreviação de cadeiras"),
        (r"\btv\s+(\d)[.,](\d{1,2})\b(?!\s?m\b)", lambda m: f"TV {m[1]},{m[2].ljust(2, '0')} m", TV_FURNITURE,
         "Medida sem unidade"),
        (r"\bc/\s?", "com ", None, "Abreviação"),
        (r"\bp/\s?", "para ", None, "Abreviação"),
        (r"\bs/\s?", "sem ", None, "Abreviação"),
    )


def expand(name):
    """Devolve o nome com as abreviações por extenso e a lista do que foi trocado."""
    text, found = name.strip(), []
    for pattern, replacement, context, problem in _rules():
        if context is not None and not context.search(text):
            continue
        text, count = re.subn(pattern, replacement, text, flags=re.I)
        if count:
            found.append(problem)
    return re.sub(r"\s+", " ", text).strip(), found


def ambiguous(name):
    words = re.findall(r"[\w/]+", name.lower())
    return [message for term, message in AMBIGUOUS.items() if term in words]


def _case_word(word, first):
    low = word.lower()
    if low in KEEP_UPPER:
        return low.upper()
    if low in SMALL_WORDS and not first:
        return low
    if any(char.isdigit() for char in word):
        return word.upper() if word.isupper() and not re.fullmatch(r"\d+[a-z]+", low) else low
    return "-".join(part.capitalize() for part in low.split("-"))


def is_shouting(name):
    letters = [char for char in name if char.isalpha()]
    return len(letters) >= 4 and all(char.isupper() for char in letters)


def nice_case(name, *keep):
    """TUDO MAIÚSCULO vira título, com "de" e "para" minúsculos. Marca e modelo ficam como no cadastro."""
    out = " ".join(_case_word(word, index == 0) for index, word in enumerate(name.split()))
    for part in keep:
        if part:
            out = re.sub(re.escape(part), part, out, flags=re.I)
    return out


def search_term(text):
    """Como o Google guarda o termo: sem hífen e pontuação. Ele devolve "guarda roupa" (550 mil), nunca "guarda-roupa"."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def terms_of(name):
    """Termos para pesquisar: o nome inteiro, o começo dele (a categoria) e o equivalente do dicionário."""
    clean = search_term(name)
    words = clean.split()
    # "roupeiro casal 5" é um pedaço sem sentido: o começo só vale se não terminar em número.
    starts = [" ".join(words[:size]) for size in (2, 3) if len(words) >= size and not words[size - 1].isdigit()]
    terms = [clean, *starts]
    for ours, other in SYNONYMS:
        ours_term, other_term = search_term(ours), search_term(other)
        if re.search(rf"\b{ours_term}\b", clean):
            terms += [re.sub(rf"\b{ours_term}\b", other_term, clean), ours_term, other_term]
    # O Google recusa o pedido inteiro com termo de mais de 80 letras ou 10 palavras: o nome muito longo fica de fora.
    return [term for term in dict.fromkeys(terms) if 3 <= len(term) <= 80 and len(term.split()) <= 10][:8]
