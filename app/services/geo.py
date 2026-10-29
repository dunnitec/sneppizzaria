"""Frete por distância: CEP → endereço (ViaCEP) → ponto no mapa → km até a loja.

Escolhas (pensadas para custo zero):
- Distância em linha reta × ROAD_FACTOR, para compensar o desenho das ruas. Não usa serviço de rotas.
- Ponto no mapa por várias fontes grátis, da mais exata para a mais larga (find_point):
  rua + número no Nominatim (OpenStreetMap) e no Photon (busca tolerante do OpenStreetMap, acha
  "R. Joaquim Antônio de Freitas" mesmo cadastrada sem o "de"), o ponto do CEP (AwesomeAPI),
  só a rua, e por último o bairro (só para cliente; a loja precisa de ponto exato).
  Nada achado → frete "a combinar" (quem chama decide).
- Toda consulta ao mapa fica guardada em GeoCache. Nominatim e Photon pedem no máximo 1 consulta
  por segundo e um User-Agent identificando o sistema; _throttled() respeita as duas regras.
"""

import math
import re
import threading
import time
from decimal import ROUND_HALF_UP, Decimal

import requests

from app.extensions import db
from app.models import GeoCache

ROAD_FACTOR = 1.3
TIMEOUT = 5
USER_AGENT = "DunniDelivery/1.0 (frete por distancia; contato: suporte da plataforma)"
VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
CEP_POINT_URL = "https://cep.awesomeapi.com.br/json/{cep}"
UF_NAMES = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia", "CE": "ceara",
    "DF": "distrito federal", "ES": "espirito santo", "GO": "goias", "MA": "maranhao", "MT": "mato grosso",
    "MS": "mato grosso do sul", "MG": "minas gerais", "PA": "para", "PB": "paraiba", "PR": "parana",
    "PE": "pernambuco", "PI": "piaui", "RJ": "rio de janeiro", "RN": "rio grande do norte",
    "RS": "rio grande do sul", "RO": "rondonia", "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo",
    "SE": "sergipe", "TO": "tocantins",
}
# abreviações comuns no endereço digitado → como o mapa conhece a rua
ABBREVIATIONS = [
    (r"r", "Rua"), (r"av", "Avenida"), (r"al", "Alameda"), (r"tv|trav", "Travessa"), (r"pca|pç|pça|praca", "Praça"),
    (r"rod", "Rodovia"), (r"estr", "Estrada"), (r"lgo|lg", "Largo"), (r"vl", "Vila"), (r"jd", "Jardim"),
    (r"pq", "Parque"), (r"dr", "Doutor"), (r"prof", "Professor"), (r"sto|sta", "Santo"), (r"cel", "Coronel"),
]

_lock = threading.Lock()
_last_call = [0.0]
_ceps = {}  # CEP → endereço (só os achados; o ViaCEP é consultado de novo a cada reinício)


def cep_digits(text):
    digits = re.sub(r"\D", "", str(text or ""))
    return digits if len(digits) == 8 else None


def _get_json(url, params=None):
    """Única saída para a internet (os testes trocam esta função)."""
    r = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()


def lookup_cep(cep):
    """{street, neighborhood, city, uf} ou None (CEP inexistente ou ViaCEP fora do ar)."""
    cep = cep_digits(cep)
    if not cep:
        return None
    if cep in _ceps:
        return _ceps[cep]
    try:
        d = _get_json(VIACEP_URL.format(cep=cep))
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(d, dict) or d.get("erro"):
        return None
    if len(_ceps) > 5000:
        _ceps.clear()
    _ceps[cep] = {"street": d.get("logradouro") or "", "neighborhood": d.get("bairro") or "",
                  "city": d.get("localidade") or "", "uf": d.get("uf") or ""}
    return _ceps[cep]


def _throttled(url, params):
    """Nominatim e Photon: 1 consulta por segundo, para o sistema todo. (dados, respondeu?)"""
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            return _get_json(url, params), True
        except (requests.RequestException, ValueError):
            return None, False  # fora do ar: não guarda, tenta de novo na próxima
        finally:
            _last_call[0] = time.monotonic()


def _cached(key, fetch):
    """Consulta guardada em GeoCache (achados e não achados). fetch() → (ponto ou None, respondeu?)."""
    key = key[:255]
    hit = GeoCache.query.filter_by(key=key).first()
    if hit:
        return hit.as_point()
    place, answered = fetch()
    if not answered:
        return None
    place = place or {}
    hit = GeoCache(key=key, lat=place.get("lat"), lng=place.get("lng"), label=(place.get("label") or "")[:255] or None,
                   city=(place.get("city") or "")[:80] or None, uf=place.get("uf") or None)
    db.session.add(hit)
    db.session.commit()
    return hit.as_point()


def _nominatim(params):
    found, answered = _throttled(NOMINATIM_URL, {**params, "format": "json", "limit": 1,
                                                 "countrycodes": "br", "addressdetails": 1})
    place = found[0] if answered and isinstance(found, list) and found else None
    if not place:
        return None, answered
    addr = place.get("address") or {}
    return {"lat": float(place["lat"]), "lng": float(place["lon"]), "label": place.get("display_name", ""),
            "city": addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or "",
            "uf": _uf(addr.get("ISO3166-2-lvl4"))}, True


def geocode(**params):
    """Ponto no mapa pelo Nominatim: {lat, lng, label, city, uf} ou None."""
    key = "|".join(f"{k}={' '.join(str(v).lower().split())}" for k, v in sorted(params.items()) if v)
    return _cached(key, lambda: _nominatim(params)) if key else None


def plain(text):
    """'São Paulo' → 'sao paulo' (para comparar nomes sem acento)."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def photon(q, city="", uf=""):
    """Busca tolerante (Photon/OpenStreetMap): acha nomes com pequenas diferenças. Só aceita na cidade/UF pedidas."""
    def fetch():
        found, answered = _throttled(PHOTON_URL, {"q": q, "limit": 5})
        if not answered:
            return None, False
        for f in (found or {}).get("features") or []:
            pr = f.get("properties") or {}
            if (pr.get("countrycode") or "").upper() != "BR":
                continue
            if city and plain(city) not in {plain(pr.get(k)) for k in ("city", "county", "district", "locality", "name")}:
                continue
            if uf and UF_NAMES.get(uf.upper()) and plain(pr.get("state")) != UF_NAMES[uf.upper()]:
                continue
            lng, lat = f["geometry"]["coordinates"][:2]
            label = ", ".join(str(pr[k]) for k in ("name", "street", "housenumber", "city") if pr.get(k))
            return {"lat": float(lat), "lng": float(lng), "label": label, "city": pr.get("city") or city, "uf": uf}, True
        return None, True

    return _cached(f"photon|{plain(q)}|{plain(city)}|{uf.lower()}", fetch) if q else None


def cep_point(cep):
    """Ponto do CEP (AwesomeAPI, grátis): no Brasil o CEP costuma ser um trecho de rua."""
    cep = cep_digits(cep)
    if not cep:
        return None

    def fetch():
        try:
            d = _get_json(CEP_POINT_URL.format(cep=cep))
        except requests.HTTPError:
            return None, True  # CEP sem ponto
        except (requests.RequestException, ValueError):
            return None, False
        try:
            lat, lng = float(d["lat"]), float(d["lng"])
        except (KeyError, TypeError, ValueError):
            return None, True
        return {"lat": lat, "lng": lng, "label": f"CEP {cep[:5]}-{cep[5:]} · {d.get('address') or ''}".strip(" ·"),
                "city": d.get("city") or "", "uf": d.get("state") or ""}, True

    return _cached(f"cep|{cep}", fetch)


def expand_street(street):
    """'R. Joaquim' → 'Rua Joaquim'; 'Av Brasil' → 'Avenida Brasil'."""
    street = " ".join(str(street or "").split())
    for short, full in ABBREVIATIONS:
        street = re.sub(rf"(?i)(^|\s)(?:{short})\.?(?=\s)", lambda m: m.group(1) + full, street)
    return street


def find_point(street="", number="", city="", uf="", cep="", neighborhood=""):
    """Ponto no mapa tentando várias fontes, da mais exata para a mais larga. None = não achou.
    neighborhood: último recurso (cliente); a loja não passa o bairro, para não ficar num ponto aproximado."""
    street, number = expand_street(street), re.sub(r"\D", "", str(number or ""))[:6]
    if street and city:
        if number:
            point = geocode(street=f"{number} {street}", city=city, state=uf) or photon(f"{street}, {number}, {city}", city, uf)
            if point:
                return point
    point = cep_point(cep) if cep else None
    if point:
        return point
    if street and city:
        point = geocode(street=street, city=city, state=uf) or photon(f"{street}, {city}", city, uf)
        if point:
            return point
    if neighborhood and city:
        return geocode(q=f"{neighborhood}, {city}, {uf}") or photon(f"{neighborhood}, {city}", city, uf)
    return None


def _uf(iso):
    """'BR-SP' → 'SP'."""
    return iso[3:5] if iso and iso.startswith("BR-") else None


def parse_coords(text):
    """Coordenadas coladas do Google Maps, ex.: '-23.2641, -47.2995' → (lat, lng) ou None."""
    nums = re.findall(r"-?\d{1,3}\.\d+", str(text or ""))
    if len(nums) != 2:
        return None
    lat, lng = float(nums[0]), float(nums[1])
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


def km_between(lat1, lng1, lat2, lng2):
    """Distância de entrega estimada: linha reta (haversine) × ROAD_FACTOR, com 1 casa decimal."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    straight = 2 * r * math.asin(math.sqrt(a))
    return Decimal(str(straight * ROAD_FACTOR)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def km_fee(tenant, km):
    """Preço: até km_base_km cobra a taxa fixa km_base_fee; acima disso, só km × R$/km (a fixa sai).
    Sem taxa fixa configurada, sempre km × R$/km."""
    if tenant.km_base_km and tenant.km_base_fee is not None and km <= Decimal(str(tenant.km_base_km)):
        return Decimal(str(tenant.km_base_fee)).quantize(Decimal("0.01"))
    return (km * Decimal(str(tenant.km_price or 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def locate_customer(tenant, cep="", street="", neighborhood="", number=""):
    """Ponto do cliente: rua e número na cidade do CEP (ou da loja), o CEP, a rua; senão o bairro."""
    info = lookup_cep(cep) if cep else None
    city = (info or {}).get("city") or tenant.store_city or ""
    uf = (info or {}).get("uf") or tenant.store_uf or ""
    street = street or (info or {}).get("street") or ""
    neighborhood = neighborhood or (info or {}).get("neighborhood") or ""
    if not city and not cep:
        return None
    return find_point(street, number, city, uf, cep, neighborhood)


def quote(tenant, cep="", street="", neighborhood="", number=""):
    """Frete por distância. Devolve dict:
    status: "ok" (fee e km), "far" (passou do limite, km), "unknown" (não achou: a combinar)
            ou "store" (loja ainda sem ponto no mapa: a combinar).
    """
    if tenant.store_lat is None or tenant.store_lng is None:
        return {"status": "store", "km": None, "fee": None}
    point = locate_customer(tenant, cep, street, neighborhood, number)
    if not point:
        return {"status": "unknown", "km": None, "fee": None}
    km = km_between(tenant.store_lat, tenant.store_lng, point["lat"], point["lng"])
    if tenant.km_max and km > Decimal(str(tenant.km_max)):
        return {"status": "far", "km": km, "fee": None}
    return {"status": "ok", "km": km, "fee": km_fee(tenant, km)}
