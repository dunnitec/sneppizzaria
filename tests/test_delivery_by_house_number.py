"""Frete pelo número da casa: só calcula com o número, e cada número fica no seu lugar da rua (endereços do IBGE)."""

from decimal import Decimal

import pytest

from app.extensions import db
from app.models import AddressPoint, Order
from app.services.addresses import city_file, find_address, load_rows, street_key
from tests.test_delivery_km import km_store, net, site_order  # noqa: F401


def row(street, number, lat, lng, cep="13300000", title="", level="1", modifier=""):
    return {"NOM_TITULO_SEGLOGR": title, "NOM_SEGLOGR": street, "NUM_ENDERECO": str(number), "LATITUDE": str(lat),
            "LONGITUDE": str(lng), "CEP": cep, "NV_GEO_COORD": level, "DSC_MODIFICADOR": modifier}


@pytest.fixture
def street(app):
    """Rua Perto: do número 100 (perto da loja) ao 2000 (longe)."""
    load_rows("Itu", "SP", [row("PERTO", 100, -23.2641, -47.2995), row("PERTO", 1000, -23.2641, -47.2800),
                            row("PERTO", 2000, -23.2641, -47.2700)])


def lat_lng(point):
    return round(point["lat"], 4), round(point["lng"], 4)


def test_street_key_matches_what_people_type():
    assert street_key("Av. Dr. Ermelindo de Maffei, 120") == "ermelindo maffei"
    assert street_key("Doutor Ermelindo Maffei") == street_key("ERMELINDO MAFFEI")
    assert street_key("Rua São Paulo") == street_key("SAO PAULO")
    assert street_key("Rua Rio Amazonas") == "rio amazonas"


def test_finds_the_city_file_by_name():
    html = """<a href="3523909_ITU.zip">x</a> <a href="3545803_SANTA_BARBARA_D_OESTE.zip">y</a> <a href="3550308_SAO_PAULO.zip">z</a>"""
    assert city_file(html, "Itu") == "3523909_ITU.zip"
    assert city_file(html, "São Paulo") == "3550308_SAO_PAULO.zip"
    assert city_file(html, "Santa Bárbara d'Oeste") == "3545803_SANTA_BARBARA_D_OESTE.zip"
    assert city_file(html, "Itupeva") is None


def test_each_number_has_its_own_place(street):
    assert lat_lng(find_address("Itu", "SP", "Rua Perto", "100")) == (-23.2641, -47.2995)
    assert lat_lng(find_address("Itu", "SP", "Rua Perto", "2000")) == (-23.2641, -47.27)


def test_number_between_known_houses_is_estimated(street):
    assert lat_lng(find_address("Itu", "SP", "Rua Perto", "1500")) == (-23.2641, -47.275)


def test_number_with_letters_and_typo_in_street(street):
    assert lat_lng(find_address("Itu", "SP", "R. Pertoo", "1000-A")) == (-23.2641, -47.28)


def test_outside_the_register_goes_back_to_the_map(street):
    assert find_address("Itu", "SP", "Rua Perto", "9000") is None
    assert find_address("Itu", "SP", "Rua Perto", "S/N") is None
    assert find_address("Itu", "SP", "Rua Que Nao Existe", "10") is None
    assert find_address("Salto", "SP", "Rua Perto", "100") is None


def test_same_name_in_far_apart_places_uses_the_cep(app):
    load_rows("Itu", "SP", [row("FLORES", 10, -23.20, -47.30, cep="13300001"), row("FLORES", 10, -23.40, -47.30, cep="13300002")])
    assert lat_lng(find_address("Itu", "SP", "Rua das Flores", "10", "13300002")) == (-23.4, -47.3)
    assert find_address("Itu", "SP", "Rua das Flores", "10") is None


def test_import_skips_vague_points_and_replaces_the_city(app):
    rows = [row("A", 1, -23.1, -47.1), row("A", 1, -23.3, -47.3), row("B", 0, -23, -47), row("C", 5, -23, -47, level="6"),
            row("D", 7, -23, -47, modifier="KM"), row("E", "SN", -23, -47)]
    assert load_rows("Itu", "SP", rows) == 1
    only = AddressPoint.query.one()
    assert (round(only.lat, 1), only.number) == (-23.2, 1)
    assert load_rows("Itu", "SP", [row("F", 2, -23, -47)]) == 1
    assert AddressPoint.query.one().street_key == "f"


def test_quote_waits_for_the_house_number(client, km_store, net, street):
    r = client.get("/snep/api/frete?cep=13300000").json
    assert (r["status"], r["km"], r["fee"]) == ("number", None, None)
    assert r["street"] == "Rua Perto"  # o CEP já preenche a rua
    assert net["map"] == 0


def test_changing_the_number_changes_km_and_fee(client, km_store, net, street):
    first = client.get("/snep/api/frete?cep=13300000&number=100").json
    last = client.get("/snep/api/frete?cep=13300000&number=2000").json
    assert first["status"] == last["status"] == "ok" and first["approx"] is False and last["approx"] is False
    assert first["km"] < last["km"] and first["fee"] < last["fee"]


def test_unknown_number_is_marked_as_approximate(client, km_store, net):
    r = client.get("/snep/api/frete?cep=13300000&number=100").json
    assert r["status"] == "ok" and r["approx"] is True


def test_house_without_number_can_still_be_quoted(client, km_store, net, street):
    r = client.get("/snep/api/frete?cep=13300000&number=S/N").json
    assert r["status"] == "ok" and r["approx"] is True


def test_order_charges_for_the_house_number(client, km_store, net, street):
    expected = client.get("/snep/api/frete?cep=13300000&number=2000").json
    r = site_order(client, cep="13300-000", number="2000")
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert (o.distance_km, o.delivery_fee) == (Decimal(str(expected["km"])), Decimal(str(expected["fee"])).quantize(Decimal("0.01")))
