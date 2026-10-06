from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Category, Neighborhood, Order, Product
from app.services.menu_data import data_from_db


def payload(**over):
    paulista = Product.query.filter_by(name="Paulista").one()
    premium = Category.query.filter_by(slug="premium").one()
    base = {
        "withdraw": True,
        "customer_name": "Ana",
        "customer_phone": "11999990000",
        "payment_method": "Pix",
        "items": [{"category_id": premium.id, "variant": "Inteira", "flavors": [paulista.id], "quantity": 2, "unit_price": 0.01}],
    }
    base.update(over)
    return base


def paulista_price():
    paulista = Product.query.filter_by(name="Paulista").one()
    return next(Decimal(str(v.price)) for v in paulista.variants if v.label == "Inteira")


def test_total_is_calculated_on_server(client, open_store):
    r = client.post("/snep/api/pedido", json=payload())
    assert r.status_code == 200
    expected = float(paulista_price() * 2)
    assert r.json["subtotal"] == expected
    assert r.json["total"] == expected
    order = Order.query.one()
    assert order.total == paulista_price() * 2
    assert order.items[0].unit_price == paulista_price()


def test_delivery_fee_comes_from_neighborhood_table(client, open_store):
    hood = Neighborhood.query.first()
    r = client.post("/snep/api/pedido", json=payload(withdraw=False, street="Rua A", number="10", neighborhood=hood.name))
    assert r.json["delivery_fee"] == float(hood.fee)
    assert r.json["total"] == float(paulista_price() * 2 + Decimal(str(hood.fee)))


def test_whatsapp_message_carries_order_number(client, open_store):
    r = client.post("/snep/api/pedido", json=payload())
    order = Order.query.one()
    assert f"Pedido #{order.id}" in order.whatsapp_message
    assert f"Pedido #{order.id}" in unquote(r.json["wa_link"])
    assert r.json["order_id"] == order.id


def test_tampered_item_is_rejected_and_nothing_is_saved(client, open_store):
    bad = payload()
    bad["items"][0]["flavors"] = [999999]
    r = client.post("/snep/api/pedido", json=bad)
    assert r.status_code == 400
    assert r.json["ok"] is False
    assert Order.query.count() == 0


def test_order_refused_while_store_is_closed(client, tenant):
    tenant.is_open_override = False
    db.session.commit()
    r = client.post("/snep/api/pedido", json=payload())
    assert r.status_code == 400
    assert "fechad" in r.json["error"].lower()
    assert Order.query.count() == 0


def test_change_for_is_stored(client, open_store):
    client.post("/snep/api/pedido", json=payload(payment_method="Dinheiro", change_for="200"))
    order = Order.query.one()
    assert order.change_for == Decimal("200.00")
    assert "Troco para: R$ 200,00" in order.whatsapp_message


@pytest.mark.parametrize("garbage", ["abc", "NaN", "Infinity", "-5", "0", "1e15", ["x"]])
def test_nonsense_change_for_is_dropped(client, open_store, garbage):
    r = client.post("/snep/api/pedido", json=payload(payment_method="Dinheiro", change_for=garbage))
    assert r.status_code == 200
    order = Order.query.one()
    assert order.change_for is None
    assert "Troco" not in order.whatsapp_message


def test_empty_cart_rejected(client, open_store):
    r = client.post("/snep/api/pedido", json=payload(items=[]))
    assert r.status_code == 400


def test_menu_data_exposes_ids_and_open_flag(tenant, open_store):
    d = data_from_db(tenant, order_url="/x", assets={})
    category = d["categories"][0]
    assert isinstance(category["id"], int)
    assert isinstance(category["products"][0]["id"], int)
    assert isinstance(d["borders"][0]["id"], int)
    assert isinstance(d["addons"][0]["id"], int)
    assert d["open"] is True
    assert [c["allows_addons"] for c in d["categories"]] == [False, True, False, False]


def test_menu_page_renders(client):
    r = client.get("/snep/")
    assert r.status_code == 200
    assert "Snep Pizzaria" in r.get_data(as_text=True)
