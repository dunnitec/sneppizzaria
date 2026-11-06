"""Balcão: puxa o cadastro pelo telefone, não estraga o nome do cliente e usa a pizza grátis do cartão."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Customer, Order
from app.services.loyalty import card
from tests.test_accounts import PHONE, base_price, make_program, promo_item, register
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401
from tests.test_pos import pizza


def lookup(panel, phone=PHONE):
    return panel.get("/snep/admin/pedidos/cliente", query_string={"telefone": phone}).get_json()


def counter(panel, **data):
    body = {"channel": "balcao", "customer_name": "", "customer_phone": PHONE, "payment_method": "Dinheiro",
            "items": [promo_item(1)], **data}
    return panel.post("/snep/admin/pedidos/novo", json=body)


@pytest.fixture
def program(client, open_store):
    """Cartão de 3 pizzas e cliente com cadastro feito no site."""
    p = make_program(open_store)
    register(client)
    return p


# ---------- puxar o cadastro ----------

def test_lookup_finds_customer_and_stamps_with_any_phone_format(panel, program):
    assert counter(panel, items=[promo_item(2)]).status_code == 200
    for phone in (PHONE, "11988881234", "+55 11 98888-1234"):
        r = lookup(panel, phone)
        assert (r["found"], r["registered"], r["name"]) == (True, True, "Mariana Alves")
        assert (r["cards"][0]["filled"], r["cards"][0]["goal"], r["cards"][0]["rewards"]) == (2, 3, 0)


def test_lookup_brings_the_saved_address(panel, program):
    c = Customer.query.one()
    c.street, c.number, c.neighborhood = "Rua Certa", "10", "Centro"
    db.session.commit()
    a = lookup(panel)["address"]
    assert (a["street"], a["number"], a["neighborhood"]) == ("Rua Certa", "10", "Centro")


def test_lookup_unknown_or_invalid_phone(panel, program):
    assert lookup(panel, "11977776666") == {"found": False, "loyalty": True, "first_order": None}
    assert lookup(panel, "123") == {"found": False, "loyalty": True, "first_order": None}


def test_lookup_of_customer_without_registration_has_no_card(panel, program):
    counter(panel, customer_name="João", customer_phone="11977776666")
    r = lookup(panel, "11977776666")
    assert (r["found"], r["registered"], r["name"], r["cards"]) == (True, False, "João", [])


def test_lookup_does_not_offer_placeholder_as_a_name(panel, program):
    Customer.query.one().name = "Mesa 3"
    db.session.commit()
    assert lookup(panel)["name"] == ""


def test_lookup_needs_the_panel_login(client, program):
    r = client.get("/snep/admin/pedidos/cliente", query_string={"telefone": PHONE})
    assert r.status_code == 302 and "Mariana" not in r.get_data(as_text=True)


def test_employee_can_look_up_customers(client, tenant, program):
    make_admin(tenant, "func").role = "funcionario"
    db.session.commit()
    login(client, username="func")
    assert lookup(client)["found"] is True


# ---------- nome do cliente ----------

@pytest.mark.parametrize("extra", [{}, {"channel": "mesa", "table_label": "3"}])
def test_blank_name_keeps_the_customer_name(panel, program, extra):
    r = counter(panel, **extra)
    assert r.status_code == 200, r.json
    assert Customer.query.one().name == "Mariana Alves"
    assert db.session.get(Order, r.json["order_id"]).customer_name == "Mariana Alves"


def test_typed_name_still_updates_the_customer(panel, program):
    counter(panel, customer_name="Mariana Souza")
    assert Customer.query.one().name == "Mariana Souza"


def test_real_name_replaces_a_placeholder(panel, open_store):
    counter(panel, channel="mesa", table_label="3")
    assert Customer.query.one().name == "Mesa 3"
    counter(panel)
    assert Customer.query.one().name == "Mesa 3"
    counter(panel, customer_name="Ana")
    assert Customer.query.one().name == "Ana"


def test_counter_without_phone_still_works(panel, program):
    r = counter(panel, customer_phone="")
    o = db.session.get(Order, r.json["order_id"])
    assert (o.customer_id, o.customer_name) == (None, "Balcão")


# ---------- pizza grátis no balcão ----------

def test_reward_used_at_the_counter(panel, program):
    counter(panel, items=[promo_item(3)])
    c = Customer.query.one()
    assert card(program, c)["rewards"] == 1
    r = counter(panel, use_rewards=[program.id])
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert (o.discount, o.total, o.loyalty_reward) == (base_price(), Decimal("0.00"), True)
    lc = card(program, c)
    assert (lc["rewards"], lc["total_stamps"]) == (0, 3)  # a pizza-prêmio não gera selo


def test_reward_is_not_used_unless_asked(panel, program):
    counter(panel, items=[promo_item(3)])
    r = counter(panel)
    assert db.session.get(Order, r.json["order_id"]).discount == 0
    assert card(program, Customer.query.one())["rewards"] == 1


def test_reward_cannot_be_used_twice(panel, program):
    counter(panel, items=[promo_item(3)])
    assert counter(panel, use_rewards=[program.id]).status_code == 200
    orders = Order.query.count()
    r = counter(panel, use_rewards=[program.id])
    assert r.status_code == 400 and "já foi usada" in r.json["error"]
    assert Order.query.count() == orders


def test_reward_needs_a_pizza_that_fits(panel, program):
    counter(panel, items=[promo_item(3)])
    orders = Order.query.count()
    r = counter(panel, use_rewards=[program.id], items=[pizza()])  # Paulista: fora do cartão Promocional
    assert r.status_code == 400 and "Nenhum item" in r.json["error"]
    assert Order.query.count() == orders


def test_reward_needs_a_registered_phone(panel, program):
    r = counter(panel, customer_phone="", use_rewards=[program.id])
    assert r.status_code == 400 and "cartão fidelidade" in r.json["error"]
    r = counter(panel, customer_phone="11977776666", customer_name="João", use_rewards=[program.id])
    assert r.status_code == 400


# ---------- desconto do 1º pedido no balcão ----------

@pytest.fixture
def first_on(open_store):
    open_store.first_order_enabled, open_store.first_order_type, open_store.first_order_value = True, "percent", Decimal("5")
    db.session.commit()
    return open_store


def five_percent(value):
    return (value * Decimal("0.05")).quantize(Decimal("0.01"))


def test_counter_first_order_discount_for_registered_customer(panel, program, first_on):
    assert lookup(panel)["first_order"] == {"text": "5% de desconto no 1º pedido", "type": "percent", "value": 5.0}
    r = counter(panel, first_order=True)
    assert r.status_code == 200, r.json
    o = db.session.get(Order, r.json["order_id"])
    assert (o.first_order, o.discount) == (True, five_percent(base_price()))
    assert o.total == o.subtotal - o.discount


def test_counter_first_order_discount_for_new_phone_without_registration(panel, first_on):
    assert lookup(panel, "11977776666")["first_order"]["value"] == 5.0
    r = counter(panel, customer_phone="11977776666", customer_name="João", first_order=True)
    assert r.status_code == 200, r.json
    assert db.session.get(Order, r.json["order_id"]).discount == five_percent(base_price())


def test_counter_without_the_box_has_no_discount(panel, program, first_on):
    assert db.session.get(Order, counter(panel).json["order_id"]).discount == 0


def test_counter_first_order_only_once(panel, program, first_on):
    r = counter(panel, first_order=True)
    o = db.session.get(Order, r.json["order_id"])
    o.status = "confirmado"
    db.session.commit()
    assert lookup(panel)["first_order"] is None
    orders = Order.query.count()
    r = counter(panel, first_order=True)
    assert r.status_code == 400 and "1º pedido" in r.json["error"]
    assert Order.query.count() == orders


def test_counter_first_order_needs_a_phone(panel, first_on):
    r = counter(panel, customer_phone="", first_order=True)
    assert r.status_code == 400


def test_first_order_off_shows_nothing(panel, program, open_store):
    assert lookup(panel)["first_order"] is None
