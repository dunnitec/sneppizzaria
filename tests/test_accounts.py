"""Cadastro do cliente (telefone + senha), fidelidade, desconto do 1º pedido e acompanhamento."""
from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Category, Customer, Order, Product
from app.services.loyalty import card
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401

PHONE = "(11) 98888-1234"


def register(client, phone=PHONE, pin="1234", name="Mariana Alves"):
    return client.post("/snep/api/conta/cadastro", json={"name": name, "phone": phone, "pin": pin})


def promo_item(qty=1):
    cat = Category.query.filter_by(slug="promocionais").one()
    p = cat.products[0]
    return {"category_id": cat.id, "variant": p.variants[0].label, "flavors": [p.id], "quantity": qty}


def drink_free_item():
    paulista = Product.query.filter_by(name="Paulista").one()
    return {"category_id": Category.query.filter_by(slug="premium").one().id, "variant": "Inteira", "flavors": [paulista.id], "quantity": 1}


def order(client, items=None, phone=PHONE, **over):
    body = {"withdraw": True, "customer_name": "Mariana", "customer_phone": phone, "payment_method": "Dinheiro",
            "items": items or [promo_item()], **over}
    return client.post("/snep/api/pedido", json=body).get_json()


def base_price():
    return Decimal(str(Category.query.filter_by(slug="promocionais").one().products[0].variants[0].price))


def set_status(order_id, status):
    o = db.session.get(Order, order_id)
    o.status = status
    db.session.commit()


# ---------- cadastro e login ----------

def test_register_logs_in_and_shows_account(client, tenant):
    r = register(client)
    assert r.status_code == 200 and r.get_json()["logged"]
    c = Customer.query.filter_by(phone_key="11988881234").one()
    assert c.registered_at and c.pin_hash and c.pin_hash != "1234"
    me = client.get("/snep/api/conta").get_json()
    assert me["logged"] and me["name"] == "Mariana Alves" and me["phone"] == "(11) 98888-1234"


@pytest.mark.parametrize("over, msg", [({"pin": "12"}, "4 a 6 números"), ({"pin": "abcd"}, "4 a 6 números"),
                                       ({"phone": "123"}, "telefone válido"), ({"name": ""}, "seu nome")])
def test_register_validation(client, tenant, over, msg):
    data = {"name": "Ana", "phone": PHONE, "pin": "1234", **over}
    r = client.post("/snep/api/conta/cadastro", json=data)
    assert r.status_code == 400 and msg in r.get_json()["error"]


def test_register_needs_json(client, tenant):
    r = client.post("/snep/api/conta/cadastro", data={"name": "Ana", "phone": PHONE, "pin": "1234"})
    assert r.status_code == 400


def test_phone_already_registered(client, tenant):
    register(client)
    r = register(client.application.test_client())  # outro aparelho
    assert r.status_code == 409
    assert "Entrar" in r.get_json()["error"]


def test_old_customer_registers_but_history_starts_now(client, open_store):
    order(client)  # pedido antes do cadastro
    old = Customer.query.one()
    register(client)
    assert Customer.query.count() == 1 and Customer.query.one().id == old.id
    assert client.get("/snep/api/conta").get_json()["orders"] == []
    order(client)
    assert len(client.get("/snep/api/conta").get_json()["orders"]) == 1


def test_login_wrong_pin_and_lock(client, tenant):
    register(client)
    other = client.application.test_client()
    assert other.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "9999"}).status_code == 401
    for _ in range(4):
        other.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "9999"})
    r = other.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "1234"})
    assert r.status_code == 429  # bloqueado mesmo com a senha certa
    c = Customer.query.one()
    c.locked_until = None
    db.session.commit()
    assert other.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "1234"}).status_code == 200


def test_login_unknown_phone(client, tenant):
    r = client.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "1234"})
    assert r.status_code == 404 and "Criar cadastro" in r.get_json()["error"]


def test_logout(client, tenant):
    register(client)
    client.post("/snep/api/conta/sair", json={})
    assert client.get("/snep/api/conta").get_json()["logged"] is False


def test_change_pin_logs_out_other_devices(client, tenant):
    register(client)
    other = client.application.test_client()
    other.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "1234"})
    assert client.post("/snep/api/conta/senha", json={"pin": "0000", "new_pin": "5678"}).status_code == 401
    assert client.post("/snep/api/conta/senha", json={"pin": "1234", "new_pin": "5678"}).status_code == 200
    assert client.get("/snep/api/conta").get_json()["logged"] is True
    assert other.get("/snep/api/conta").get_json()["logged"] is False


def test_tampered_cookie_is_ignored(client, tenant):
    register(client)
    client.set_cookie("cliente_snep", "lixo", domain="localhost")
    assert client.get("/snep/api/conta").get_json()["logged"] is False


# ---------- desconto do 1º pedido ----------

def enable_first_order(tenant, kind="percent", value="10"):
    tenant.first_order_enabled, tenant.first_order_type, tenant.first_order_value = True, kind, Decimal(value)
    db.session.commit()


def test_first_order_discount_only_once(client, open_store):
    enable_first_order(open_store)
    register(client)
    assert client.get("/snep/api/conta").get_json()["first_order"] == "10% de desconto no 1º pedido"
    r = order(client)
    o = db.session.get(Order, r["order_id"])
    assert o.first_order and o.discount == (base_price() * Decimal("0.1")).quantize(Decimal("0.01"))
    assert o.total == o.subtotal - o.discount
    assert "Desconto (1º pedido)" in unquote(r["wa_link"])
    second = db.session.get(Order, order(client)["order_id"])
    assert second.discount == 0 and not second.first_order


def test_first_order_comes_back_if_first_was_cancelled(client, open_store):
    enable_first_order(open_store, "amount", "5")
    register(client)
    set_status(order(client)["order_id"], "cancelado")
    assert db.session.get(Order, order(client)["order_id"]).discount == Decimal("5.00")


def test_no_discount_without_login_or_with_other_phone(client, open_store):
    enable_first_order(open_store)
    assert db.session.get(Order, order(client)["order_id"]).discount == 0
    register(client, phone="(11) 97777-0000")
    assert db.session.get(Order, order(client)["order_id"]).discount == 0  # telefone do pedido é outro


def test_who_already_ordered_does_not_get_first_order(client, open_store):
    enable_first_order(open_store)
    order(client)
    register(client)
    assert db.session.get(Order, order(client)["order_id"]).discount == 0


# ---------- fidelidade ----------

def enable_loyalty(tenant, goal=3):
    cat = Category.query.filter_by(slug="promocionais").one()
    tenant.loyalty_enabled, tenant.loyalty_goal, tenant.loyalty_kinds = True, goal, "pizza,doce"
    tenant.loyalty_reward_category_id, tenant.loyalty_reward_size = cat.id, None
    db.session.commit()


def test_stamps_count_only_confirmed_pizzas_after_signup(client, open_store):
    enable_loyalty(open_store)
    order(client, items=[promo_item(2)])  # antes do cadastro: não conta
    register(client)
    c = Customer.query.one()
    a = order(client, items=[promo_item(2)])["order_id"]
    assert card(open_store, c)["total_stamps"] == 0  # pendente ainda não conta
    set_status(a, "confirmado")
    assert card(open_store, c)["total_stamps"] == 2
    b = order(client, items=[promo_item(1)])["order_id"]
    set_status(b, "entregue")
    lc = card(open_store, c)
    assert (lc["filled"], lc["rewards"]) == (0, 1)
    assert client.get("/snep/api/conta").get_json()["loyalty"]["rewards"] == 1


def test_reward_makes_one_pizza_free_and_is_used_once(client, open_store):
    enable_loyalty(open_store, goal=2)
    register(client)
    set_status(order(client, items=[promo_item(2)])["order_id"], "confirmado")
    c = Customer.query.one()
    assert card(open_store, c)["rewards"] == 1
    r = order(client, items=[promo_item(1), drink_free_item()], use_reward=True)
    o = db.session.get(Order, r["order_id"])
    assert o.loyalty_reward and o.discount == base_price()
    assert card(open_store, c)["rewards"] == 0  # pendente já segura o prêmio
    again = db.session.get(Order, order(client, items=[promo_item(1)], use_reward=True)["order_id"])
    assert again.discount == 0
    set_status(o.id, "cancelado")
    assert card(open_store, c)["rewards"] == 1  # cancelou: prêmio volta


def test_reward_needs_the_right_pizza_in_the_cart(client, open_store):
    enable_loyalty(open_store, goal=1)
    register(client)
    set_status(order(client)["order_id"], "confirmado")
    o = db.session.get(Order, order(client, items=[drink_free_item()], use_reward=True)["order_id"])
    assert o.discount == 0 and not o.loyalty_reward


def test_free_pizza_does_not_earn_a_stamp(client, open_store):
    enable_loyalty(open_store, goal=2)
    register(client)
    set_status(order(client, items=[promo_item(2)])["order_id"], "confirmado")
    o = order(client, items=[promo_item(1)], use_reward=True)["order_id"]
    set_status(o, "confirmado")
    assert card(open_store, Customer.query.one())["total_stamps"] == 2


# ---------- acompanhamento ----------

def test_tracking_page_shows_times_and_status(client, open_store, admin):
    r = order(client)
    assert r["track_url"].startswith("/snep/pedido/")
    page = client.get(r["track_url"]).get_data(as_text=True)
    assert f"Pedido #{r['order_id']}" in page and "Pronto para retirar" in page and r["eta"] in page
    assert "Pedido recebido" in page and "aguardando" in page
    login(client)
    client.post(f"/snep/admin/pedidos/{r['order_id']}/status", data={"status": "confirmado"})
    assert db.session.get(Order, r["order_id"]).confirmed_at is not None
    page = client.get(r["track_url"]).get_data(as_text=True)
    assert "Confirmado" in page


def test_tracking_unknown_token_404(client, tenant):
    assert client.get("/snep/pedido/nao-existe").status_code == 404


def test_account_history_has_tracking_links(client, open_store):
    register(client)
    r = order(client)
    hist = client.get("/snep/api/conta").get_json()["orders"]
    assert hist[0]["id"] == r["order_id"] and hist[0]["track_url"] == r["track_url"]


# ---------- painel ----------

def test_owner_configures_loyalty_and_first_order(panel, tenant):
    cat = Category.query.filter_by(slug="premium").one()
    r = panel.post("/snep/admin/fidelidade", data={
        "loyalty_enabled": "on", "loyalty_goal": "8", "kinds": ["pizza", "doce"], "reward_category": cat.id,
        f"reward_size-{cat.id}": "Broto", "first_order_enabled": "on", "first_order_type": "percent", "first_order_value": "15"})
    assert r.status_code == 302
    db.session.expire_all()
    assert (tenant.loyalty_enabled, tenant.loyalty_goal, tenant.loyalty_kinds) == (True, 8, "pizza,doce")
    assert (tenant.loyalty_reward_category_id, tenant.loyalty_reward_size) == (cat.id, "Broto")
    assert (tenant.first_order_enabled, tenant.first_order_value) == (True, Decimal("15.00"))
    site = panel.get("/snep/").get_data(as_text=True)
    assert '"loyalty": {' in site and '"first_order": {' in site


@pytest.mark.parametrize("over, msg", [({"loyalty_goal": "1"}, "de 2 a"), ({"kinds": []}, "conta selo"),
                                       ({"first_order_value": "80"}, "1% a 50%")])
def test_loyalty_form_validation(panel, tenant, over, msg):
    cat = Category.query.filter_by(slug="premium").one()
    data = {"loyalty_enabled": "on", "loyalty_goal": "8", "kinds": ["pizza"], "reward_category": cat.id,
            "first_order_enabled": "on", "first_order_type": "percent", "first_order_value": "10", **over}
    r = panel.post("/snep/admin/fidelidade", data=data, follow_redirects=True)
    assert msg in r.get_data(as_text=True)
    db.session.expire_all()
    assert tenant.loyalty_enabled is False


def test_owner_generates_new_pin(client, tenant):
    register(client)
    make_admin(tenant)
    staff = client.application.test_client()
    login(staff)
    c = Customer.query.one()
    r = staff.post(f"/snep/admin/clientes/{c.id}/senha", follow_redirects=True)
    text = r.get_data(as_text=True)
    assert "Senha nova de Mariana Alves:" in text
    pin = text.split("Senha nova de Mariana Alves: ")[1][:4]
    assert client.application.test_client().post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": pin}).status_code == 200


def test_customers_page_shows_registration_and_stamps(client, open_store):
    enable_loyalty(open_store, goal=4)
    register(client)
    set_status(order(client)["order_id"], "confirmado")
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    page = staff.get("/snep/admin/clientes").get_data(as_text=True)
    assert "Cadastro no site" in page and "1/4" in page


def test_receipt_shows_discount(client, open_store):
    enable_first_order(open_store)
    register(client)
    oid = order(client)["order_id"]
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    assert "Desconto (1º pedido)" in staff.get(f"/snep/admin/pedidos/{oid}/etiqueta").get_data(as_text=True)
