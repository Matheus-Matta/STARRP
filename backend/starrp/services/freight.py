"""Cotação de frete (padrão do StarHub: `apps/logistica/cotacao.py` + `geo.py`).

    quote(table, "20040-020")  -> Quote(value=Decimal("129.90"), lead_days=3, ...)
    quotes(account, store, zip) -> [Quote ...] de todas as tabelas ativas (as que não
                                   atendem vêm com `error`, para a tela dizer por quê)

Por distância: taxa fixa + km × preço por km (ao centavo), nunca abaixo do mínimo;
acima da distância máxima, FreightUnavailable. Por faixa de CEP: a faixa que contém o
CEP; havendo mais de uma, a mais estreita.

Distância: coordenada do CEP pela AwesomeAPI e, se faltar, BrasilAPI v2 (guardada em
ZipCoordinate, cada CEP é consultado uma vez); km por estrada pelo OSRM público (guardado
em ZipDistance). OSRM fora do ar: linha reta × ROAD_FACTOR, e a cotação avisa que é
estimativa. Com muito volume, troque ROUTE por um servidor OSRM próprio.
"""
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from urllib.error import HTTPError, URLError

from django.db.models import Q

from starrp.models import FreightTable, ZipCoordinate, ZipDistance

TIMEOUT = 6  # segundos por API: a cotação responde na hora, não espera API parada
ZIP_SOURCES = (
    ("awesomeapi", "https://cep.awesomeapi.com.br/json/{zip}"),
    ("brasilapi", "https://brasilapi.com.br/api/cep/v2/{zip}"),
)
ROUTE = "https://router.project-osrm.org/route/v1/driving/{lng1},{lat1};{lng2},{lat2}?overview=false"
# Endereço completo → CEP (ViaCEP, por UF/cidade/logradouro) e → coordenada (Nominatim/OpenStreetMap).
VIACEP_SEARCH = "https://viacep.com.br/ws/{state}/{city}/{street}/json/"
NOMINATIM = "https://nominatim.openstreetmap.org/search?{query}"
# Estrada nunca é reta: 1,3 é o desvio médio usado em logística para estimar.
ROAD_FACTOR = Decimal("1.3")
EARTH_KM = 6371.0


class FreightUnavailable(Exception):
    """Não há frete para o CEP: a mensagem diz por quê (vai para quem cotou)."""


class GeoError(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    table_id: str
    table: str
    value: Decimal | None
    lead_days: int | None
    distance_km: Decimal | None = None
    detail: str = ""
    error: str = ""

    def as_dict(self):
        return {"table": self.table_id, "table_name": self.table,
                "value": None if self.value is None else str(self.value), "lead_days": self.lead_days,
                "distance_km": None if self.distance_km is None else str(self.distance_km),
                "detail": self.detail, "error": self.error}


def cents(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_zip(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        raise FreightUnavailable(f"CEP '{value}' inválido: informe os 8 dígitos.")
    return digits


# ── Geo ─────────────────────────────────────────────────────────────────────
def _json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Starrp/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (URLs fixas acima)
            return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise GeoError(str(error)) from error


def _point(source, data):
    if source == "awesomeapi":
        lat, lng = data.get("lat"), data.get("lng")
    else:
        spot = ((data.get("location") or {}).get("coordinates")) or {}
        lat, lng = spot.get("latitude"), spot.get("longitude")
    return (Decimal(str(lat)), Decimal(str(lng))) if lat and lng else None


def coordinate(zip_code):
    saved = ZipCoordinate.objects.filter(zip_code=zip_code).first()
    if saved:
        return saved.latitude, saved.longitude
    reasons = []
    for source, url in ZIP_SOURCES:
        try:
            point = _point(source, _json(url.format(zip=zip_code)))
        except GeoError as error:
            reasons.append(f"{source}: {error}")
            continue
        if point:
            ZipCoordinate.objects.update_or_create(zip_code=zip_code, defaults={
                "latitude": point[0], "longitude": point[1], "source": source})
            return point
        reasons.append(f"{source}: sem coordenada")
    raise GeoError(f"Não foi possível localizar o CEP {zip_code} ({'; '.join(reasons)}).")


def straight_km(origin, destination):
    lat1, lng1, lat2, lng2 = map(math.radians, map(float, (*origin, *destination)))
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return Decimal(str(2 * EARTH_KM * math.asin(math.sqrt(half))))


def road_km(origin, destination):
    """(km por estrada com 1 casa, True se veio da rota; False se é estimativa)."""
    url = ROUTE.format(lat1=origin[0], lng1=origin[1], lat2=destination[0], lng2=destination[1])
    try:
        km, exact = Decimal(str(_json(url)["routes"][0]["distance"])) / 1000, True
    except (GeoError, KeyError, IndexError, TypeError):
        km, exact = straight_km(origin, destination) * ROAD_FACTOR, False
    return km.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), exact


def zip_for_address(street, city, state, district=""):
    """CEP de um endereço pela ViaCEP (busca por UF/cidade/logradouro); havendo vários, o do bairro."""
    if len(street.strip()) < 3 or not city.strip() or len(state.strip()) != 2:
        return None
    quoted = {k: urllib.parse.quote(v.strip()) for k, v in {"state": state.upper(), "city": city, "street": street}.items()}
    try:
        rows = _json(VIACEP_SEARCH.format(**quoted))
    except GeoError:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    wanted = district.strip().casefold()
    best = next((r for r in rows if wanted and r.get("bairro", "").casefold() == wanted), rows[0])
    return {"zip_code": re.sub(r"\D", "", best.get("cep", "")), "street": best.get("logradouro", ""),
            "district": best.get("bairro", ""), "city": best.get("localidade", ""), "state": best.get("uf", "")}


def geocode_address(street, number, city, state, district=""):
    """(lat, lng) do endereço pelo Nominatim (OpenStreetMap); `None` se não achar."""
    query = urllib.parse.urlencode({"street": f"{number} {street}".strip(), "city": city, "state": state,
                                    "country": "Brasil", "format": "json", "limit": 1})
    try:
        rows = _json(NOMINATIM.format(query=query))
    except GeoError:
        return None
    if not rows:
        return None
    return Decimal(str(rows[0]["lat"])), Decimal(str(rows[0]["lon"]))


def km_between(origin_zip, destination_zip, destination_point=None):
    """Km por estrada. Com `destination_point` (endereço completo geocodificado) mede até o ponto
    exato; senão, até o centro do CEP."""
    if destination_point is not None:
        return road_km(coordinate(origin_zip), destination_point)
    saved = ZipDistance.objects.filter(origin=origin_zip, destination=destination_zip).first()
    if saved:
        return saved.km, True
    km, exact = road_km(coordinate(origin_zip), coordinate(destination_zip))
    if exact:
        ZipDistance.objects.update_or_create(origin=origin_zip, destination=destination_zip, defaults={"km": km})
    return km, exact


# ── Cotação ─────────────────────────────────────────────────────────────────
def _by_range(table, zip_code):
    ranges = [r for r in table.ranges.all() if r.deleted_at is None and r.zip_start <= zip_code <= r.zip_end]
    if not ranges:
        raise FreightUnavailable(f"O CEP {zip_code} não está em nenhuma faixa de '{table.name}'.")
    best = min(ranges, key=lambda r: (int(r.zip_end) - int(r.zip_start), r.zip_start))
    days = best.lead_days if best.lead_days is not None else table.lead_days
    label = best.label or f"Faixa {best.zip_start} a {best.zip_end}"
    return Quote(str(table.pk), table.name, cents(best.value), days, detail=label)


def _by_distance(table, zip_code, point=None):
    if not table.origin_zip or table.price_per_km is None:
        raise FreightUnavailable(f"'{table.name}' está sem CEP de origem ou preço por km.")
    if not zip_code and point is None:
        raise FreightUnavailable("Sem CEP nem coordenada do endereço para medir a distância.")
    try:
        km, exact = km_between(table.origin_zip, zip_code, point)
    except GeoError as error:
        raise FreightUnavailable(str(error)) from error
    if table.max_distance_km is not None and km > table.max_distance_km:
        raise FreightUnavailable(f"{km} km passa da distância máxima de {table.max_distance_km} km.")
    value = max(cents(table.fixed_fee) + cents(km * table.price_per_km), cents(table.min_value))
    shown = f"{km}".replace(".", ",")
    detail = f"{shown} km por estrada" if exact else f"{shown} km estimados (linha reta × 1,3; rota indisponível)"
    return Quote(str(table.pk), table.name, value, table.lead_days, distance_km=km, detail=detail)


def quote(table, zip_code, point=None):
    """Por faixa: precisa do CEP. Por distância: usa a coordenada do endereço (`point`) quando
    houver; senão, a do CEP."""
    if not table.is_active:
        raise FreightUnavailable(f"A tabela '{table.name}' está desativada.")
    if table.kind == FreightTable.Kind.ZIP_RANGE:
        if not zip_code:
            raise FreightUnavailable("Não achamos o CEP deste endereço: a tabela por faixa precisa dele.")
        return _by_range(table, normalize_zip(zip_code))
    return _by_distance(table, normalize_zip(zip_code) if zip_code else "", point)


def tables_for(account_id, store_id=None):
    qs = FreightTable.all_objects.filter(account_id=account_id, is_active=True, deleted_at__isnull=True)
    if store_id:
        qs = qs.filter(Q(store__isnull=True) | Q(store_id=store_id))
    return qs.prefetch_related("ranges").order_by("position", "name")


def quotes(account_id, store_id, zip_code, point=None):
    """Todas as tabelas ativas da loja: as que atendem com valor, as outras com o motivo."""
    zip_code = normalize_zip(zip_code) if zip_code else ""
    out = []
    for table in tables_for(account_id, store_id):
        try:
            out.append(quote(table, zip_code, point))
        except FreightUnavailable as error:
            out.append(Quote(str(table.pk), table.name, None, None, error=str(error)))
    return sorted(out, key=lambda q: (q.value is None, q.value or 0))
