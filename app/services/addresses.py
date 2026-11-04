"""Local exato de cada número da rua, com o Cadastro de Endereços do Censo 2022 (CNEFE/IBGE, público e grátis).

O mapa grátis (OpenStreetMap) quase não tem número de casa no Brasil: devolve um ponto qualquer da rua, e o
número 10 e o 3000 davam o mesmo km. Aqui o número certo vem do IBGE; número que o IBGE não tem é estimado entre
os vizinhos da mesma rua. Rua ou número fora do cadastro: None, e services/geo.py usa o mapa como aproximação.

Cada cidade é carregada uma vez: flask importar-enderecos SP Itu Salto
"""

import bisect
import csv
import difflib
import io
import re
import tempfile
import zipfile
from collections import defaultdict

import requests

from app.extensions import db
from app.models import AddressPoint

IBGE_CITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
CNEFE_DIR = ("https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
             "Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/{code_uf}_{uf}/")
USER_AGENT = "DunniDelivery/1.0 (frete por distancia)"
GOOD_COORDS = {"1", "2", "3", "4"}  # 5 e 6: só o bairro ou o setor do censo, largos demais para o frete
MAX_SPAN_KM = 4  # mesma rua espalhada por mais que isso: nomes iguais em bairros diferentes, quem decide é o CEP
NUMBER_MARGIN = 100  # número além da última casa conhecida: até aqui ainda vale a ponta da rua
SIMILAR = 0.86

STREET_TYPES = {"rua", "r", "avenida", "av", "alameda", "al", "travessa", "tv", "trav", "praca", "pca", "largo", "lgo",
                "estrada", "estr", "rodovia", "rod", "viela", "beco", "via", "servidao", "ladeira", "acesso", "marginal"}
TITLES = {"doutor", "doutora", "dr", "dra", "professor", "professora", "prof", "profa", "padre", "pe", "santa", "santo",
          "sta", "sto", "sao", "marechal", "mal", "tenente", "ten", "maestro", "monsenhor", "mons", "coronel", "cel",
          "general", "gal", "capitao", "cap", "major", "sargento", "dom", "dona", "presidente", "pres", "prefeito",
          "vereador", "engenheiro", "eng", "deputado", "dep", "senador", "governador", "gov", "comendador", "barao",
          "visconde", "conselheiro", "almirante", "frei", "irma", "madre", "cardeal", "bispo", "brigadeiro"}
LINKS = {"de", "da", "do", "das", "dos", "e"}


def plain(text):
    from app.services.geo import plain as to_plain

    return to_plain(text)


def street_key(street):
    """'Av. Dr. Ermelindo de Maffei, 120' → 'ermelindo maffei': compara o que o cliente digita com o cadastro."""
    words = re.sub(r"[^a-z0-9 ]", " ", plain(str(street or "").split(",")[0])).split()
    if words and words[0] in STREET_TYPES:
        words = words[1:]
    while len(words) > 1 and words[0] in TITLES:
        words = words[1:]
    return " ".join(w for w in words if w not in LINKS)[:120]


def load_rows(city, uf, rows):
    """Troca os endereços da cidade pelas linhas do arquivo do IBGE. Devolve quantos pontos ficaram gravados."""
    keys, grouped = {}, {}
    for r in rows:
        number = (r.get("NUM_ENDERECO") or "").strip()
        if r.get("NV_GEO_COORD") not in GOOD_COORDS or r.get("DSC_MODIFICADOR") == "KM" or not number.isdigit() or not int(number):
            continue
        try:
            lat, lng = float(r["LATITUDE"]), float(r["LONGITUDE"])
        except (KeyError, TypeError, ValueError):
            continue
        name = f"{r.get('NOM_TITULO_SEGLOGR') or ''} {r.get('NOM_SEGLOGR') or ''}"
        key = keys.setdefault(name, street_key(name))
        if key:
            place = (key, int(number), r.get("CEP") or "")
            sum_lat, sum_lng, count = grouped.get(place, (0.0, 0.0, 0))
            grouped[place] = (sum_lat + lat, sum_lng + lng, count + 1)
    city_key, uf = plain(city), uf.upper()
    AddressPoint.query.filter_by(city=city_key, uf=uf).delete()
    db.session.bulk_insert_mappings(AddressPoint, [
        {"city": city_key, "uf": uf, "street_key": key, "number": number, "cep": cep[:8],
         "lat": round(sum_lat / count, 6), "lng": round(sum_lng / count, 6)}
        for (key, number, cep), (sum_lat, sum_lng, count) in grouped.items()])
    db.session.commit()
    return len(grouped)


def import_city(uf, city):
    """Baixa o arquivo da cidade no IBGE e carrega. Levanta ValueError se a cidade não existir."""
    uf, wanted = uf.upper(), plain(city)
    towns = requests.get(IBGE_CITIES_URL.format(uf=uf), timeout=30, headers={"User-Agent": USER_AGENT}).json()
    code = next((str(t["id"]) for t in towns if plain(t["nome"]) == wanted), None)
    if not code:
        raise ValueError(f"Cidade '{city}' não encontrada em {uf}.")
    folder = CNEFE_DIR.format(code_uf=code[:2], uf=uf)
    listing = requests.get(folder, timeout=30, headers={"User-Agent": USER_AGENT})
    listing.raise_for_status()
    found = re.search(rf'href="({code}_[^"]+\.zip)"', listing.text)
    if not found:
        raise ValueError(f"O IBGE não tem o arquivo de '{city}' ({code}).")
    with tempfile.TemporaryFile() as tmp:
        with requests.get(folder + found.group(1), stream=True, timeout=120, headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                tmp.write(chunk)
        tmp.seek(0)
        with zipfile.ZipFile(tmp) as z, z.open(z.namelist()[0]) as raw:
            return load_rows(city, uf, csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";"))


def _span_km(rows):
    lats, lngs = [r.lat for r in rows], [r.lng for r in rows]
    return max(max(lats) - min(lats), max(lngs) - min(lngs)) * 111


def _same_street(city_rows, key, cep):
    rows = city_rows.filter_by(street_key=key).all()
    if not rows:
        known = [k for (k,) in city_rows.with_entities(AddressPoint.street_key).distinct()]
        close = difflib.get_close_matches(key, known, 1, SIMILAR)  # "Pala Souza" → "Paula Souza"
        rows = city_rows.filter_by(street_key=close[0]).all() if close else []
    if rows and _span_km(rows) > MAX_SPAN_KM:
        rows = [r for r in rows if r.cep == cep]
    return rows


def find_address(city, uf, street, number, cep=""):
    """Ponto do número na rua: {lat, lng, label, city, uf, exact: True} ou None (fora do cadastro)."""
    digits = re.search(r"\d+", str(number or ""))
    key = street_key(street)
    if not digits or not key or not city:
        return None
    wanted = int(digits.group()[:6])
    rows = _same_street(AddressPoint.query.filter_by(city=plain(city), uf=(uf or "").upper()), key, cep)
    if not rows:
        return None
    points = defaultdict(list)
    for r in rows:
        points[r.number].append((r.lat, r.lng))
    points = {n: (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)) for n, ps in points.items()}
    numbers = sorted(points)
    if wanted < numbers[0] - NUMBER_MARGIN or wanted > numbers[-1] + NUMBER_MARGIN:
        return None
    at = bisect.bisect_left(numbers, wanted)
    if at == len(numbers):
        lat, lng = points[numbers[-1]]
    elif numbers[at] == wanted or at == 0:
        lat, lng = points[numbers[at]]
    else:  # entre duas casas conhecidas
        below, above = numbers[at - 1], numbers[at]
        part = (wanted - below) / (above - below)
        lat = points[below][0] + (points[above][0] - points[below][0]) * part
        lng = points[below][1] + (points[above][1] - points[below][1]) * part
    return {"lat": lat, "lng": lng, "label": f"{street}, {wanted}", "city": city, "uf": uf, "exact": True}
