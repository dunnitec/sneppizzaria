"""Cadastro do cliente (telefone + senha), fidelidade, desconto do 1º pedido e acompanhamento."""
import json
from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Category, Customer, LoyaltyProgram, Order, Product
from app.services.loyalty import card
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401

PHONE = "(11) 98888-1234"


def register(client, phone=PHONE, pin="482913", name="Mariana Alves"):
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
    assert c.registered_at and c.pin_hash and c.pin_hash != "482913"
    me = client.get("/snep/api/conta").get_json()
    assert me["logged"] and me["name"] == "Mariana Alves" and me["phone"] == "(11) 98888-1234"


@pytest.mark.parametrize("over, msg", [({"pin": "12"}, "6 números"), ({"pin": "abcdef"}, "6 números"),
                                       ({"pin": "4829"}, "6 números"), ({"pin": "123456"}, "fácil de adivinhar"),
                                       ({"pin": "777777"}, "fácil de adivinhar"), ({"pin": "987654"}, "fácil de adivinhar"),
                                       ({"phone": "123"}, "telefone válido"), ({"name": ""}, "seu nome")])
def test_register_validation(client, tenant, over, msg):
    data = {"name": "Ana", "phone": PHONE, "pin": "482913", **over}
    r = client.post("/snep/api/conta/cadastro", json=data)
    assert r.status_code == 400 and msg in r.get_json()["error"]


def test_register_needs_json(client, tenant):
    r = client.post("/snep/api/conta/cadastro", data={"name": "Ana", "phone": PHONE, "pin": "482913"})
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


def test_login_lock_is_per_connection_not_per_account(client, tenant):
    """Relatório item 3: errar a senha tranca quem errou (a conexão), não o dono da conta."""
    register(client)
    attacker = client.application.test_client()
    for _ in range(5):
        assert attacker.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "999999"}).status_code == 401
    r = attacker.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "482913"})
    assert r.status_code == 429  # quem errou fica bloqueado, mesmo acertando depois
    owner = client.application.test_client()
    r = owner.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "482913"},
                   environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert r.status_code == 200  # o cliente, de outra conexão, entra normalmente


def test_many_phones_from_one_connection_get_blocked(client, tenant):
    for i in range(20):
        client.post("/snep/api/conta/entrar", json={"phone": f"119880000{i:02d}", "pin": "111111"})
    assert client.post("/snep/api/conta/entrar", json={"phone": "11988000099", "pin": "111111"}).status_code == 429


def test_login_unknown_phone_looks_like_wrong_pin(client, tenant):
    register(client)
    unknown = client.application.test_client().post("/snep/api/conta/entrar", json={"phone": "11977770000", "pin": "482913"})
    wrong = client.application.test_client().post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "999999"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json()["error"] == wrong.get_json()["error"]


def test_old_pin_with_4_digits_still_logs_in(client, tenant):
    register(client)
    c = Customer.query.one()
    c.set_pin("4829")
    db.session.commit()
    assert client.application.test_client().post("/snep/api/conta/entrar",
                                                 json={"phone": PHONE, "pin": "4829"}).status_code == 200


def test_register_on_phone_with_orders_does_not_reveal_address(client, open_store):
    """Relatório item 1: o número não é verificado, então o cadastro não herda o endereço de quem já pediu."""
    victim = client.application.test_client()
    order(victim, withdraw=False, street="Rua Ficticia", number="10", neighborhood="Centro")
    assert Customer.query.one().street == "Rua Ficticia"
    me = register(client).get_json()
    assert me["address"] == {"rua": "", "num": "", "comp": "", "bairro": "", "ref": ""} and me["orders"] == []


def test_anonymous_order_does_not_touch_registered_customer(client, open_store):
    """Relatório item 2: pedido sem entrar na conta, com o telefone de quem tem senha, não mexe no cadastro."""
    register(client)
    order(client, withdraw=False, street="Rua Certa", number="1", neighborhood="Centro")
    stranger = client.application.test_client()
    r = order(stranger, customer_name="Fulano", withdraw=False, street="Rua Falsa", number="99", neighborhood="Centro")
    assert r["ok"]
    c = Customer.query.one()
    assert (c.name, c.street) == ("Mariana", "Rua Certa")
    from app.models import Order
    assert db.session.get(Order, r["order_id"]).customer_id is None
    assert len(client.get("/snep/api/conta").get_json()["orders"]) == 1


def test_logout(client, tenant):
    register(client)
    client.post("/snep/api/conta/sair", json={})
    assert client.get("/snep/api/conta").get_json()["logged"] is False


def test_change_pin_logs_out_other_devices(client, tenant):
    register(client)
    other = client.application.test_client()
    other.post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": "482913"})
    assert client.post("/snep/api/conta/senha", json={"pin": "000001", "new_pin": "739104"}).status_code == 401
    assert client.post("/snep/api/conta/senha", json={"pin": "482913", "new_pin": "739104"}).status_code == 200
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


# ---------- fidelidade (cartões) ----------

def make_program(tenant, name="Promocional", goal=3, counted=("promocionais",), reward="promocionais", flavors=None, size=None):
    cats = {c.slug: c for c in Category.query.filter_by(tenant_id=tenant.id)}
    reward_cat = cats[reward]
    ids = flavors if flavors is not None else [x.id for x in reward_cat.products]
    p = LoyaltyProgram(tenant_id=tenant.id, name=name, active=True, goal=goal,
                       count_category_ids=json.dumps([cats[s].id for s in counted]), reward_category_id=reward_cat.id,
                       reward_size=size, reward_product_ids=json.dumps(ids))
    db.session.add(p)
    db.session.commit()
    return p


def premium_item(name="Paulista", size="Inteira", qty=1):
    p = Product.query.filter_by(name=name).one()
    return {"category_id": p.category_id, "variant": size, "flavors": [p.id], "quantity": qty}


def doce_item(qty=1):
    cat = Category.query.filter_by(slug="doces").one()
    p = cat.products[0]
    return {"category_id": cat.id, "variant": "Inteira", "flavors": [p.id], "quantity": qty}


def test_stamps_count_only_confirmed_pizzas_after_signup(client, open_store):
    prog = make_program(open_store)
    order(client, items=[promo_item(2)])  # antes do cadastro: não conta
    register(client)
    c = Customer.query.one()
    a = order(client, items=[promo_item(2)])["order_id"]
    lc = card(prog, c)
    assert lc["total_stamps"] == 0 and lc["pending"] == 2  # pendente: aparece como “chegando”
    set_status(a, "confirmado")
    lc = card(prog, c)
    assert (lc["total_stamps"], lc["pending"]) == (2, 0)
    set_status(order(client, items=[promo_item(1)])["order_id"], "entregue")
    lc = card(prog, c)
    # completou: cartão cheio com o prêmio, não “0 de 3” (parecia que os selos tinham sumido)
    assert (lc["filled"], lc["full"], lc["rewards"]) == (3, True, 1)
    assert client.get("/snep/api/conta").get_json()["loyalty"][0]["rewards"] == 1
    set_status(order(client, items=[promo_item(1)])["order_id"], "confirmado")
    lc = card(prog, c)
    assert (lc["filled"], lc["full"], lc["rewards"]) == (1, False, 1)  # novo cartão começa, prêmio continua


def test_pending_reward_order_does_not_count_as_stamp(client, open_store):
    prog = make_program(open_store, goal=2)
    register(client)
    set_status(order(client, items=[promo_item(2)])["order_id"], "confirmado")
    order(client, items=[promo_item(1)], use_rewards=[prog.id])  # pizza grátis, ainda pendente
    assert card(prog, Customer.query.one())["pending"] == 0


def test_two_cards_count_separately_and_doces_join_premium(client, open_store):
    promo = make_program(open_store, "Promocional", goal=10)
    premium = make_program(open_store, "Premium", goal=10, counted=("premium", "doces"), reward="premium")
    register(client)
    o = order(client, items=[promo_item(3), premium_item(qty=2), doce_item(2)])["order_id"]
    set_status(o, "confirmado")
    c = Customer.query.one()
    assert card(promo, c)["total_stamps"] == 3
    assert card(premium, c)["total_stamps"] == 4  # 2 premium + 2 doces
    names = [x["name"] for x in client.get("/snep/api/conta").get_json()["loyalty"]]
    assert names == ["Promocional", "Premium"]


def test_reward_only_with_allowed_flavors(client, open_store):
    paulista, peperone = Product.query.filter_by(name="Paulista").one(), Product.query.filter_by(name="Peperone").one()
    prog = make_program(open_store, "Premium", goal=1, counted=("premium",), reward="premium", flavors=[paulista.id])
    register(client)
    set_status(order(client, items=[premium_item("Peperone")])["order_id"], "confirmado")
    c = Customer.query.one()
    assert card(prog, c)["rewards"] == 1
    no = db.session.get(Order, order(client, items=[premium_item("Peperone")], use_rewards=[prog.id])["order_id"])
    assert no.discount == 0 and not no.loyalty_reward  # sabor fora da lista do dono
    half = {"category_id": paulista.category_id, "variant": "Inteira", "flavors": [paulista.id, peperone.id], "quantity": 1}
    assert db.session.get(Order, order(client, items=[half], use_rewards=[prog.id])["order_id"]).discount == 0
    yes = db.session.get(Order, order(client, items=[premium_item("Paulista")], use_rewards=[prog.id])["order_id"])
    assert yes.loyalty_reward and yes.loyalty_programs == f",{prog.id}," and yes.discount == yes.subtotal


def test_reward_makes_one_pizza_free_and_is_used_once(client, open_store):
    prog = make_program(open_store, goal=2)
    register(client)
    set_status(order(client, items=[promo_item(2)])["order_id"], "confirmado")
    c = Customer.query.one()
    assert card(prog, c)["rewards"] == 1
    r = order(client, items=[promo_item(1), drink_free_item()], use_rewards=[prog.id])
    o = db.session.get(Order, r["order_id"])
    assert o.loyalty_reward and o.discount == base_price()
    assert "Promocional grátis (fidelidade)" in o.discount_note
    assert card(prog, c)["rewards"] == 0  # pendente já segura o prêmio
    again = order(client, items=[promo_item(1)], use_rewards=[prog.id])
    assert again["ok"] is False and "já foi usada" in again["error"]  # avisa em vez de cobrar cheio calado
    set_status(o.id, "cancelado")
    assert card(prog, c)["rewards"] == 1  # cancelou: prêmio volta


def test_two_rewards_in_the_same_order(client, open_store):
    promo = make_program(open_store, "Promocional", goal=1)
    premium = make_program(open_store, "Premium", goal=1, counted=("premium",), reward="premium")
    register(client)
    set_status(order(client, items=[promo_item(1), premium_item()])["order_id"], "confirmado")
    o = db.session.get(Order, order(client, items=[promo_item(1), premium_item()], use_rewards=[promo.id, premium.id])["order_id"])
    assert o.discount == o.subtotal and o.loyalty_programs in (f",{promo.id},{premium.id},", f",{premium.id},{promo.id},")


def test_free_pizza_does_not_earn_a_stamp(client, open_store):
    prog = make_program(open_store, goal=2)
    register(client)
    set_status(order(client, items=[promo_item(2)])["order_id"], "confirmado")
    set_status(order(client, items=[promo_item(1)], use_rewards=[prog.id])["order_id"], "confirmado")
    assert card(prog, Customer.query.one())["total_stamps"] == 2


def test_card_without_flavors_is_not_shown(client, open_store):
    make_program(open_store, flavors=[])
    register(client)
    assert client.get("/snep/api/conta").get_json()["loyalty"] == []


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

def program_form(**over):
    promo, premium, doces = (Category.query.filter_by(slug=s).one() for s in ("promocionais", "premium", "doces"))
    data = {"name": "Premium", "goal": "10", "active": "on", "counted": [str(premium.id), str(doces.id)],
            "reward_category": premium.id, f"reward_size-{premium.id}": "Inteira",
            f"flavors-{premium.id}": [str(p.id) for p in premium.products[:3]]}
    data.update(over)
    return data


def test_owner_creates_two_cards(panel, tenant):
    promo = Category.query.filter_by(slug="promocionais").one()
    r = panel.post("/snep/admin/fidelidade/cartao/novo", data=program_form())
    assert r.status_code == 302
    panel.post("/snep/admin/fidelidade/cartao/novo", data={
        "name": "Promocional", "goal": "10", "active": "on", "counted": [str(promo.id)], "reward_category": promo.id,
        f"flavors-{promo.id}": [str(p.id) for p in promo.products[:2]]})
    progs = LoyaltyProgram.query.order_by(LoyaltyProgram.id).all()
    assert [p.name for p in progs] == ["Premium", "Promocional"]
    assert progs[0].reward_size == "Inteira" and len(progs[0].reward_products()) == 3
    page = panel.get("/snep/admin/fidelidade").get_data(as_text=True)
    assert "Cartão Premium" in page and "No site" in page
    site = panel.get("/snep/").get_data(as_text=True)
    assert '"reward": "1 pizza Premium Inteira gr' in site  # tojson escreve “á” como \u00e1


@pytest.mark.parametrize("over, msg", [({"goal": "1"}, "de 2 a"), ({"counted": []}, "categorias que valem selo"),
                                       ({"name": ""}, "nome do cartão")])
def test_card_form_validation(panel, tenant, over, msg):
    r = panel.post("/snep/admin/fidelidade/cartao/novo", data=program_form(**over), follow_redirects=True)
    assert msg in r.get_data(as_text=True)
    assert LoyaltyProgram.query.count() == 0


def test_card_needs_flavors_to_be_on(panel, tenant):
    premium = Category.query.filter_by(slug="premium").one()
    r = panel.post("/snep/admin/fidelidade/cartao/novo", data=program_form(**{f"flavors-{premium.id}": []}), follow_redirects=True)
    assert "sabores que o cliente pode escolher" in r.get_data(as_text=True)
    data = program_form(**{f"flavors-{premium.id}": []})
    data.pop("active")
    panel.post("/snep/admin/fidelidade/cartao/novo", data=data)  # desligado: salva incompleto
    assert LoyaltyProgram.query.one().active is False


def test_category_counts_in_one_card_only(panel, tenant):
    panel.post("/snep/admin/fidelidade/cartao/novo", data=program_form())
    r = panel.post("/snep/admin/fidelidade/cartao/novo", data=program_form(name="Outro"), follow_redirects=True)
    assert "Cada categoria conta em um cartão só" in r.get_data(as_text=True)
    assert LoyaltyProgram.query.count() == 1


def test_edit_and_delete_card(panel, tenant):
    panel.post("/snep/admin/fidelidade/cartao/novo", data=program_form())
    p = LoyaltyProgram.query.one()
    panel.post(f"/snep/admin/fidelidade/cartao/{p.id}", data=program_form(goal="8"))
    assert db.session.get(LoyaltyProgram, p.id).goal == 8
    panel.post(f"/snep/admin/fidelidade/cartao/{p.id}/excluir")
    assert LoyaltyProgram.query.count() == 0


def test_owner_configures_first_order(panel, tenant):
    panel.post("/snep/admin/fidelidade/primeiro-pedido", data={"first_order_enabled": "on", "first_order_type": "percent",
                                                              "first_order_value": "15"})
    db.session.expire_all()
    assert (tenant.first_order_enabled, tenant.first_order_value) == (True, Decimal("15.00"))
    r = panel.post("/snep/admin/fidelidade/primeiro-pedido", data={"first_order_enabled": "on", "first_order_type": "percent",
                                                                  "first_order_value": "80"}, follow_redirects=True)
    assert "1% a 50%" in r.get_data(as_text=True)


def test_owner_generates_new_pin(client, tenant):
    register(client)
    make_admin(tenant)
    staff = client.application.test_client()
    login(staff)
    c = Customer.query.one()
    r = staff.post(f"/snep/admin/clientes/{c.id}/senha", follow_redirects=True)
    text = r.get_data(as_text=True)
    assert "Senha nova de Mariana Alves:" in text
    pin = text.split("Senha nova de Mariana Alves: ")[1][:6]
    assert pin.isdigit()
    assert client.application.test_client().post("/snep/api/conta/entrar", json={"phone": PHONE, "pin": pin}).status_code == 200


def test_customers_page_shows_registration_and_stamps(client, open_store):
    make_program(open_store, goal=4)
    register(client)
    set_status(order(client)["order_id"], "confirmado")
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    page = staff.get("/snep/admin/clientes").get_data(as_text=True)
    assert "Cadastro no site" in page and "Cartão Promocional: <b>1/4</b>" in page


def test_receipt_shows_discount(client, open_store):
    enable_first_order(open_store)
    register(client)
    oid = order(client)["order_id"]
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    assert "Desconto (1º pedido)" in staff.get(f"/snep/admin/pedidos/{oid}/etiqueta").get_data(as_text=True)


def test_reward_already_used_is_refused_instead_of_charging_silently(client, open_store):
    """Relatório item 26: o segundo pedido com o mesmo brinde avisa em vez de cobrar o valor cheio calado."""
    prog = make_program(open_store, goal=2)
    register(client)
    set_status(order(client, items=[promo_item(2)])["order_id"], "confirmado")
    assert order(client, items=[promo_item(1)], use_rewards=[prog.id])["ok"]
    r = order(client, items=[promo_item(1)], use_rewards=[prog.id])
    assert r["ok"] is False and "já foi usada" in r["error"]
