"""Frete por distância: CEP → endereço → ponto no mapa → km × preço (services/geo.py). Sem internet: _get_json é trocado."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import GeoCache, Order
from app.routes import public
from app.services import geo
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401
from tests.test_pos import pizza, paulista_price

STORE = (-23.2640, -47.3000)
# ~1 km a leste da loja (em linha reta); com a margem de 30% vira 1,3 km
NEAR = {"lat": "-23.2640", "lon": "-47.2902"}
# ~10 km a leste
FAR = {"lat": "-23.2640", "lon": "-47.2020"}

CEPS = {
    "13300000": {"logradouro": "Rua Perto", "bairro": "Centro", "localidade": "Itu", "uf": "SP"},
    "13309999": {"logradouro": "Rua Longe", "bairro": "Pirapitingui", "localidade": "Itu", "uf": "SP"},
}
PLACES = {"rua perto": NEAR, "rua longe": FAR, "centro, itu, sp": NEAR}


@pytest.fixture
def net(monkeypatch):
    """Internet falsa: ViaCEP pelos CEPS e Nominatim pelos PLACES. Conta as consultas ao mapa."""
    calls = {"map": 0}

    def fake(url, params=None):
        if "viacep" in url:
            cep = url.rstrip("/").split("/")[-2]
            return CEPS.get(cep, {"erro": True})
        calls["map"] += 1
        text = (params.get("street") or params.get("q") or "").lower()
        place = PLACES.get(text)
        return [{**place, "display_name": text, "address": {"city": "Itu", "ISO3166-2-lvl4": "BR-SP"}}] if place else []

    monkeypatch.setattr(geo, "_get_json", fake)
    monkeypatch.setattr(geo, "_last_call", [0.0])
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    geo._ceps.clear()
    public._quotes.clear()
    return calls


@pytest.fixture
def km_store(open_store):
    t = open_store
    t.delivery_mode, t.store_lat, t.store_lng = "km", *STORE
    t.store_city, t.store_uf = "Itu", "SP"
    t.km_price, t.km_base_km, t.km_base_fee, t.km_max = Decimal("2.00"), Decimal("1.5"), Decimal("5.00"), Decimal("8")
    db.session.commit()
    return t


def site_order(client, **data):
    payload = {"customer_name": "Ana", "customer_phone": "11977776666", "payment_method": "Pix",
               "items": [pizza()], "withdraw": False, "street": "Rua Perto", "number": "10", **data}
    return client.post("/snep/api/pedido", json=payload)


# ---------- cálculo ----------

def test_km_between_adds_road_margin():
    km = geo.km_between(*STORE, float(NEAR["lat"]), float(NEAR["lon"]))
    assert km == Decimal("1.3")


def test_fixed_fee_up_to_base_km_then_only_per_km(km_store):
    assert geo.km_fee(km_store, Decimal("1.3")) == Decimal("5.00")  # perto: taxa fixa
    assert geo.km_fee(km_store, Decimal("1.5")) == Decimal("5.00")  # no limite ainda é a fixa
    assert geo.km_fee(km_store, Decimal("1.6")) == Decimal("3.20")  # passou: a fixa sai, só o km
    assert geo.km_fee(km_store, Decimal("4.0")) == Decimal("8.00")
    km_store.km_base_km = km_store.km_base_fee = None  # sem taxa fixa: sempre pelo km
    assert geo.km_fee(km_store, Decimal("1.3")) == Decimal("2.60")


def test_parse_coords_from_google_maps():
    assert geo.parse_coords("-23.2641, -47.2995") == (-23.2641, -47.2995)
    assert geo.parse_coords("abc") is None


# ---------- consulta do site ----------

def test_quote_fills_address_from_cep(client, km_store, net):
    r = client.get("/snep/api/frete?cep=13300-000").json
    assert (r["status"], r["km"], r["fee"]) == ("ok", 1.3, 5.0)
    assert (r["street"], r["neighborhood"], r["city"]) == ("Rua Perto", "Centro", "Itu")


def test_quote_far_and_unknown(client, km_store, net):
    assert client.get("/snep/api/frete?cep=13309999").json["status"] == "far"
    r = client.get("/snep/api/frete?street=Rua+Inexistente").json
    assert r["status"] == "unknown" and r["fee"] is None


def test_quote_falls_back_to_neighborhood(client, km_store, net):
    r = client.get("/snep/api/frete?street=Rua+Inexistente&neighborhood=Centro").json
    assert r["status"] == "ok"


def test_map_lookups_are_cached(client, km_store, net):
    client.get("/snep/api/frete?cep=13300000")
    client.get("/snep/api/frete?cep=13300000")
    assert net["map"] == 1 and GeoCache.query.count() == 1


def test_quote_only_when_store_charges_by_km(client, open_store, net):
    assert client.get("/snep/api/frete?cep=13300000").status_code == 404


def test_quote_rate_limited_per_ip(client, km_store, net, monkeypatch):
    monkeypatch.setattr(public, "QUOTES_PER_10_MIN", 2)
    client.get("/snep/api/frete?cep=13300000")
    client.get("/snep/api/frete?cep=13300000")
    assert client.get("/snep/api/frete?cep=13300000").status_code == 429


def test_store_not_on_map_yet_is_to_be_agreed(client, km_store, net):
    km_store.store_lat = None
    db.session.commit()
    assert client.get("/snep/api/frete?cep=13300000").json["status"] == "store"


# ---------- pedido pelo site (o servidor refaz a conta) ----------

def test_site_order_charges_by_km(client, km_store, net):
    r = site_order(client, cep="13300-000", neighborhood="Centro")
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert (o.cep, o.distance_km, o.delivery_fee, o.fee_pending) == ("13300000", Decimal("1.3"), Decimal("5.00"), False)
    assert o.total == paulista_price() + Decimal("5.00")
    assert "Entrega (1,3 km): R$ 5,00" in o.whatsapp_message


def test_site_order_far_is_refused(client, km_store, net):
    r = site_order(client, cep="13309999", street="Rua Longe")
    assert r.status_code == 400 and "entregamos até 8,0 km" in r.json["error"]


def test_site_order_without_limit_accepts_far(client, km_store, net):
    km_store.km_max = None
    db.session.commit()
    r = site_order(client, cep="13309999", street="Rua Longe")
    assert r.status_code == 200
    assert db.session.get(Order, r.json["order_id"]).delivery_fee > Decimal("20")


def test_site_order_unknown_address_is_to_be_agreed_and_hides_pix(client, km_store, net, tenant):
    tenant.pix_key, tenant.pix_key_type, tenant.pix_name, tenant.pix_city = "pizzaria.teste@email.com", "email", "PIZZARIA", "ITU"
    db.session.commit()
    r = site_order(client, street="Rua Inexistente", neighborhood="Bairro Novo")
    assert r.status_code == 200 and r.json["delivery_fee"] is None and r.json["pix"] is None
    o = db.session.get(Order, r.json["order_id"])
    assert o.fee_pending and o.neighborhood_name == "Bairro Novo"
    html = client.get(r.json["track_url"]).get_data(as_text=True)
    assert "a confirmar" in html and "+ entrega a confirmar" in html and "Pague com Pix" not in html


def test_client_fee_is_ignored(client, km_store, net):
    r = site_order(client, cep="13300000", delivery_fee=0)
    assert db.session.get(Order, r.json["order_id"]).delivery_fee == Decimal("5.00")


def test_neighborhood_mode_still_uses_table(client, open_store, net):
    from app.models import Neighborhood

    hood = Neighborhood.query.first()
    r = site_order(client, neighborhood=hood.name, cep="13300000")
    o = db.session.get(Order, r.json["order_id"])
    assert o.delivery_fee == hood.fee and o.distance_km is None and net["map"] == 0


def test_disabled_neighborhood_becomes_pending_not_zero(client, open_store, net):
    """Relatório item 5: bairro desligado com o site aberto não pode gravar entrega R$ 0 e Pix sem a taxa."""
    from app.models import Neighborhood

    hood = Neighborhood.query.first()
    hood.active = False
    db.session.commit()
    r = site_order(client, neighborhood=hood.name)
    o = db.session.get(Order, r.json["order_id"])
    assert o.fee_pending and r.json["delivery_fee"] is None


# ---------- pedido por telefone ----------

def test_phone_order_uses_typed_fee_over_km(panel, km_store, net):
    r = panel.post("/snep/admin/pedidos/novo", json={
        "channel": "telefone", "customer_name": "Bia", "customer_phone": "11955554444", "withdraw": False,
        "street": "Rua Longe", "number": "5", "cep": "13309999", "delivery_fee": "15,00",
        "payment_method": "Dinheiro", "items": [pizza()]})
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert o.delivery_fee == Decimal("15.00") and o.distance_km is not None


def test_phone_order_far_without_fee_asks_for_it(panel, km_store, net):
    r = panel.post("/snep/admin/pedidos/novo", json={
        "channel": "telefone", "customer_name": "Bia", "customer_phone": "11955554444", "withdraw": False,
        "street": "Rua Longe", "number": "5", "cep": "13309999", "payment_method": "Dinheiro", "items": [pizza()]})
    assert r.status_code == 400 and "digite a taxa" in r.json["error"]


def test_panel_quote_and_pos_page(panel, km_store, net):
    assert panel.get("/snep/admin/pedidos/frete?cep=13300000").json["fee"] == 5.0
    html = panel.get("/snep/admin/pedidos/novo").get_data(as_text=True)
    assert 'name="cep"' in html and "pos-km-fee" in html


# ---------- painel: escolher a forma de cobrar ----------

def test_owner_switches_to_km_with_pasted_coords(panel, tenant, net):
    r = panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "2,50", "km_base_km": "1", "km_base_fee": "4,00",
                                                    "km_max": "7,5", "store_coords": "-23.2641, -47.2995"},
                   follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Entrega pela distância salva" in html
    assert (tenant.delivery_mode, tenant.km_price, tenant.km_base_km, tenant.km_base_fee, tenant.km_max) == \
        ("km", Decimal("2.50"), Decimal("1.0"), Decimal("4.00"), Decimal("7.5"))
    assert (tenant.store_lat, tenant.store_lng) == (-23.2641, -47.2995)
    assert "Conferir no mapa" in html and "Bairros atendidos" not in html


def test_owner_locates_store_by_address(panel, tenant, net):
    tenant.address = "Centro, Itu, SP"
    db.session.commit()
    panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "2"})
    assert tenant.delivery_mode == "km" and tenant.store_lat == float(NEAR["lat"]) and tenant.store_city == "Itu"


def test_store_not_found_keeps_neighborhood_mode(panel, tenant, net):
    tenant.address = "Lugar que não existe"
    db.session.commit()
    html = panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "2"},
                      follow_redirects=True).get_data(as_text=True)
    assert "Não achamos" in html and tenant.delivery_mode == "bairro"


def test_km_needs_price(panel, tenant, net):
    html = panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "",
                                                       "store_coords": "-23.2, -47.3"},
                      follow_redirects=True).get_data(as_text=True)
    assert tenant.delivery_mode == "bairro" and "preço por km" in html


def test_site_shows_cep_info_in_km_mode(client, km_store):
    html = client.get("/snep/").get_data(as_text=True)
    assert "Taxa pela distância, até 8 km" in html and "/snep/api/frete" in html


def test_fixed_fee_needs_both_fields(panel, tenant, net):
    html = panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "2", "km_base_km": "1",
                                                       "store_coords": "-23.2, -47.3"},
                      follow_redirects=True).get_data(as_text=True)
    assert tenant.delivery_mode == "bairro" and "preencha os dois campos" in html


def test_only_per_km_when_fixed_fee_is_blank(panel, tenant, net):
    panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "3", "km_base_km": "",
                                                "km_base_fee": "", "store_coords": "-23.2, -47.3"})
    assert tenant.delivery_mode == "km" and tenant.km_base_km is None and tenant.km_base_fee is None


def test_neighborhood_fee_still_records_the_distance_for_the_receipt(client, panel, open_store, net):
    """Frete por bairro com a loja no mapa: a taxa é a do bairro, mas o cupom mostra os km e a corrida."""
    from app.models import Neighborhood

    t = open_store
    t.store_lat, t.store_lng, t.store_city, t.store_uf = *STORE, "Itu", "SP"
    db.session.commit()
    hood = Neighborhood.query.filter_by(tenant_id=t.id, active=True).first()
    r = site_order(client, neighborhood=hood.name)
    o = db.session.get(Order, r.get_json()["order_id"])
    assert o.delivery_fee == hood.fee and o.distance_km == Decimal("1.3")
    label = panel.get(f"/snep/admin/pedidos/{o.id}/etiqueta").get_data(as_text=True)
    assert "1,3 km até o cliente" in label and f"Corrida: R$ {hood.fee:.2f}".replace(".", ",") in label


def test_neighborhood_order_goes_without_distance_when_map_fails(client, open_store, monkeypatch):
    from app.models import Neighborhood

    t = open_store
    t.store_lat, t.store_lng = STORE
    db.session.commit()

    def broken(*a, **k):
        raise OSError("sem internet")

    monkeypatch.setattr(geo, "quote", broken)
    monkeypatch.setattr("app.services.order_create.quote", broken)
    hood = Neighborhood.query.filter_by(tenant_id=t.id, active=True).first()
    r = site_order(client, neighborhood=hood.name)
    assert r.status_code == 200 and db.session.get(Order, r.get_json()["order_id"]).distance_km is None


def test_neighborhood_mode_can_put_store_on_map(panel, open_store):
    r = panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "bairro", "store_coords": "-23.2641, -47.2995"})
    assert r.status_code == 302
    db.session.refresh(open_store)
    assert open_store.delivery_mode == "bairro" and (open_store.store_lat, open_store.store_lng) == (-23.2641, -47.2995)
