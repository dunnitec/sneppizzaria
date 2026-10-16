"""Lançar pedido pelo painel: balcão, mesa e telefone/WhatsApp."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Category, Customer, Neighborhood, Order, Product
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


def pizza(qty=1, price=None):
    p = Product.query.filter_by(name="Paulista").one()
    c = Category.query.filter_by(slug="premium").one()
    item = {"category_id": c.id, "variant": "Inteira", "flavors": [p.id], "quantity": qty}
    if price is not None:
        item["unit_price"] = price
    return item


def paulista_price():
    p = Product.query.filter_by(name="Paulista").one()
    return next(v.price for v in p.variants if v.label == "Inteira")


def post(client, **data):
    return client.post("/snep/admin/pedidos/novo", json={"payment_method": "Pix", "items": [pizza()], **data})


def test_page_opens_with_menu_data(panel):
    html = panel.get("/snep/admin/pedidos/novo").get_data(as_text=True)
    assert "Novo pedido" in html and "POS_DATA" in html and "Paulista" in html


def test_counter_order_without_name_is_confirmed_and_printed(panel, tenant):
    tenant.is_open_override = False  # site fechado não impede venda no balcão
    db.session.commit()
    r = post(panel, channel="balcao")
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert (o.channel, o.status, o.delivery, o.customer_name) == ("balcao", "confirmado", False, "Balcão")
    assert o.total == paulista_price()
    assert f"imprimir={o.id}" in r.json["redirect"]


def test_table_order_needs_table_number(panel):
    assert post(panel, channel="mesa").status_code == 400
    r = post(panel, channel="mesa", table_label="7")
    o = db.session.get(Order, r.json["order_id"])
    assert (o.channel, o.table_label, o.customer_name) == ("mesa", "7", "Mesa 7")


def test_phone_order_with_delivery_charges_neighborhood_fee(panel):
    hood = Neighborhood.query.first()
    r = post(panel, channel="telefone", customer_name="Carla", customer_phone="11955554444", withdraw=False,
             street="Rua B", number="20", neighborhood=hood.name)
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert o.delivery is True and o.delivery_fee == hood.fee and o.total == paulista_price() + hood.fee
    assert Customer.query.filter_by(phone_key="11955554444").one().name == "Carla"


def test_phone_order_needs_name_and_phone(panel):
    assert post(panel, channel="telefone", customer_name="Carla").status_code == 400


def test_price_from_browser_is_ignored(panel):
    r = post(panel, channel="balcao", items=[pizza(qty=2, price=0.01)])
    assert db.session.get(Order, r.json["order_id"]).total == paulista_price() * 2


def test_counter_never_delivers(panel):
    r = post(panel, channel="balcao", withdraw=False, street="Rua X", number="1")
    o = db.session.get(Order, r.json["order_id"])
    assert o.delivery is False and o.street == ""


def test_invalid_channel_and_empty_cart(panel):
    assert post(panel, channel="drive-thru").status_code == 400
    assert post(panel, channel="balcao", items=[]).status_code == 400


def test_staff_can_take_orders(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.get("/snep/admin/pedidos/novo").status_code == 200
    assert post(client, channel="balcao").status_code == 200


def test_orders_page_has_new_order_button(panel):
    assert "/snep/admin/pedidos/novo" in panel.get("/snep/admin/pedidos").get_data(as_text=True)
