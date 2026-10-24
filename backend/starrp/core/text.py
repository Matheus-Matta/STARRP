"""Texto e formatação pt-BR usados pelo backend (documentos, etiquetas, comprovantes)."""
import re
from decimal import Decimal


def only_digits(value):
    """CPF/CNPJ/CEP como vêm (com pontuação) → só os dígitos."""
    return re.sub(r"\D", "", value or "")


def brl(value):
    """Decimal → "R$ 1.234,56" (sem depender do locale do servidor)."""
    text = f"{Decimal(value or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def br_date(value):
    return value.strftime("%d/%m/%Y") if value else ""


# Casas por nome de campo (o primeiro que aparecer no nome vence).
PLACES = (("quantity", "0.001"), ("weight", "0.001"), ("cubic", "0.0001"))


def decimals_as_text(value, key=""):
    """Decimal sai como TEXTO, como nos serializers: o JSON padrão o transformaria
    em float ("91.8"), e dinheiro nunca é float. Quantidade e peso guardam 3 casas
    (kg); cubagem, 4 (m³). O resto é dinheiro: 2 casas."""
    if isinstance(value, Decimal):
        places = next((p for word, p in PLACES if word in key), "0.01")
        return f"{value.quantize(Decimal(places))}"
    if isinstance(value, dict):
        return {k: decimals_as_text(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [decimals_as_text(v, key) for v in value]
    return value


# Texto rico do editor (descrição de produto/categoria): só formatação, nada que execute.
RICH_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li", "a", "h1", "h2", "h3", "blockquote", "span"}


def clean_html(value):
    """Limpa o HTML do editor: fica negrito, listas, títulos e links; some script,
    estilo, evento (`onclick`) e `javascript:`. Ex.: '<p onclick="x()">Oi<script>...</script></p>' → '<p>Oi</p>'.
    Editor vazio ("<p></p>", "<p><br></p>") vira texto vazio."""
    import nh3

    cleaned = nh3.clean(value or "", tags=RICH_TAGS, attributes={"a": {"href", "target"}},
                        url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer").strip()
    return "" if cleaned in {"<p></p>", "<p><br></p>", "<br>"} else cleaned


def plain_text(value):
    """HTML do editor em texto corrido (resumo do serviço, cupom). Ex.: '<p>Montagem <b>grátis</b></p>' → 'Montagem grátis'."""
    import html

    import nh3

    text = nh3.clean((value or "").replace("</p>", " </p>").replace("<br>", " "), tags=set())
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
