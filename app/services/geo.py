"""Frete por distância: CEP → endereço (ViaCEP) → ponto no mapa (OpenStreetMap/Nominatim) → km até a loja.

Escolhas (pensadas para custo zero):
- Distância em linha reta × ROAD_FACTOR, para compensar o desenho das ruas. Não usa serviço de rotas.
- Localiza a rua (sem o número): basta para o frete e não guarda o endereço exato de ninguém.
  Rua não achada → tenta o bairro; nada achado → frete "a combinar" (quem chama decide).
- Toda consulta ao mapa fica guardada em GeoCache. O Nominatim pede no máximo 1 consulta por
  segundo e um User-Agent identificando o sistema; _nominatim() respeita as duas regras.
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


def _nominatim(params):
    with _lock:  # 1 consulta por segundo, para o sistema todo
        wait = 1.05 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            found = _get_json(NOMINATIM_URL, {**params, "format": "json", "limit": 1,
                                              "countrycodes": "br", "addressdetails": 1})
        except (requests.RequestException, ValueError):
            return None, False  # fora do ar: não guarda, tenta de novo na próxima
        finally:
            _last_call[0] = time.monotonic()
    return (found[0] if isinstance(found, list) and found else None), True


def geocode(**params):
    """Ponto no mapa: {lat, lng, label, city, uf} ou None. Guarda achados e não achados."""
    key = "|".join(f"{k}={' '.join(str(v).lower().split())}" for k, v in sorted(params.items()) if v)[:255]
    if not key:
        return None
    hit = GeoCache.query.filter_by(key=key).first()
    if hit:
        return hit.as_point()
    place, answered = _nominatim(params)
    if not answered:
        return None
    addr = (place or {}).get("address") or {}
    hit = GeoCache(key=key, lat=float(place["lat"]) if place else None, lng=float(place["lon"]) if place else None,
                   label=(place or {}).get("display_name", "")[:255] or None,
                   city=(addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or "")[:80] or None,
                   uf=_uf(addr.get("ISO3166-2-lvl4")))
    db.session.add(hit)
    db.session.commit()
    return hit.as_point()


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
    """Preço: km × R$/km, nunca abaixo da taxa mínima (opcional)."""
    fee = (km * Decimal(str(tenant.km_price or 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return max(fee, Decimal(str(tenant.km_min_fee or 0)))


def locate_customer(tenant, cep="", street="", neighborhood=""):
    """Ponto do cliente: rua na cidade do CEP (ou da loja); senão o bairro. None = não achou."""
    info = lookup_cep(cep) if cep else None
    city = (info or {}).get("city") or tenant.store_city or ""
    uf = (info or {}).get("uf") or tenant.store_uf or ""
    street = street or (info or {}).get("street") or ""
    neighborhood = neighborhood or (info or {}).get("neighborhood") or ""
    if not city:
        return None
    if street:
        point = geocode(street=street, city=city, state=uf)
        if point:
            return point
    if neighborhood:
        return geocode(q=f"{neighborhood}, {city}, {uf}")
    return None


def quote(tenant, cep="", street="", neighborhood=""):
    """Frete por distância. Devolve dict:
    status: "ok" (fee e km), "far" (passou do limite, km), "unknown" (não achou: a combinar)
            ou "store" (loja ainda sem ponto no mapa: a combinar).
    """
    if tenant.store_lat is None or tenant.store_lng is None:
        return {"status": "store", "km": None, "fee": None}
    point = locate_customer(tenant, cep, street, neighborhood)
    if not point:
        return {"status": "unknown", "km": None, "fee": None}
    km = km_between(tenant.store_lat, tenant.store_lng, point["lat"], point["lng"])
    if tenant.km_max and km > Decimal(str(tenant.km_max)):
        return {"status": "far", "km": km, "fee": None}
    return {"status": "ok", "km": km, "fee": km_fee(tenant, km)}
