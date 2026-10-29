import json
from datetime import timedelta
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models import Addon, AdminUser, Border, Category, Neighborhood, Order, Product, Tenant, utcnow
from app.services.hours import is_open
from app.services.menu_data import data_from_db
from app.services.money import parse_money
from app.services.pricing import price_item
from tests.conftest import TestConfig

PASSWORD = "senha-forte-1"


def make_admin(tenant, username="dono", password=PASSWORD):
    user = AdminUser(tenant_id=tenant.id, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, slug="snep", username="dono", password=PASSWORD):
    return client.post(f"/{slug}/admin/login", data={"username": username, "password": password})


@pytest.fixture
def admin(tenant):
    return make_admin(tenant)


@pytest.fixture
def panel(client, admin):
    """Cliente HTTP já logado no painel."""
    assert login(client).status_code == 302
    return client


def premium():
    return Category.query.filter_by(slug="premium").one()


def product_form(product, **over):
    form = {f"name-{product.id}": product.name, f"desc-{product.id}": product.description or "", f"active-{product.id}": "on"}
    form.update({f"price-{v.id}": str(v.price) for v in product.variants})
    form.update(over)
    return form


# ---------- acesso ----------

@pytest.mark.parametrize("page", ["", "pedidos", "cardapio", "extras", "entrega", "loja", "senha"])
def test_panel_pages_require_login(client, admin, page):
    r = client.get(f"/snep/admin/{page}")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/snep/admin/login")


@pytest.mark.parametrize("page", ["pedidos", "cardapio", "extras", "entrega", "loja", "senha"])
def test_panel_pages_open_after_login(panel, page):
    assert panel.get(f"/snep/admin/{page}").status_code == 200


def test_wrong_password_is_refused(client, admin):
    r = login(client, password="errada")
    assert r.status_code == 200
    assert client.get("/snep/admin/cardapio").status_code == 302


def test_unknown_user_is_refused(client, admin):
    assert login(client, username="ninguem").status_code == 200
    assert client.get("/snep/admin/cardapio").status_code == 302


def test_wrong_passwords_lock_the_connection_not_the_owner(client, admin):
    """Relatório item 13: quem errou fica bloqueado; o dono, de outra conexão, entra."""
    for _ in range(5):
        login(client, password="errada")
    login(client)  # senha certa, mas esta conexão está bloqueada
    assert client.get("/snep/admin/cardapio").status_code == 302
    owner = client.application.test_client()
    owner.post("/snep/admin/login", data={"username": "dono", "password": PASSWORD},
               environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert owner.get("/snep/admin/cardapio", environ_base={"REMOTE_ADDR": "10.0.0.2"}).status_code == 200


def test_unknown_user_also_gets_blocked(client, admin):
    for _ in range(5):
        login(client, username="naoexiste", password="errada")
    html = login(client, username="naoexiste", password="errada").get_data(as_text=True)
    assert "Muitas tentativas" in html


def test_admin_of_one_store_cannot_open_another(client, admin, cardapio, tmp_path):
    from seed import seed_from_file

    snep_premium = premium()
    victim = snep_premium.products[0]
    original_name = victim.name
    other = dict(cardapio, tenant=dict(cardapio["tenant"], slug="outra", name="Outra Pizzaria"))
    other_file = tmp_path / "outra.json"
    other_file.write_text(json.dumps(other), encoding="utf-8")
    seed_from_file(other_file)
    make_admin(Tenant.query.filter_by(slug="outra").one(), username="rival")

    assert login(client, slug="outra", username="rival").status_code == 302
    assert client.get("/outra/admin/cardapio").status_code == 200
    assert client.get("/snep/admin/cardapio").status_code == 302
    r = client.post(
        f"/snep/admin/cardapio/{snep_premium.id}", data=product_form(victim, **{f"name-{victim.id}": "Invadido"})
    )
    assert r.headers["Location"].endswith("/snep/admin/login")
    # mesmo logado na outra loja, a rota dela não alcança categorias da Snep
    assert client.post(f"/outra/admin/cardapio/{snep_premium.id}", data=product_form(victim)).status_code == 404
    db.session.expire_all()
    assert victim.name == original_name


def test_logout_ends_session(panel):
    panel.post("/snep/admin/logout")
    assert panel.get("/snep/admin/cardapio").status_code == 302


def test_post_without_csrf_token_is_blocked(csrf_app):
    make_admin(Tenant.query.filter_by(slug="snep").one())
    client = csrf_app.test_client()
    r = login(client)
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]  # volta para o login, sem entrar
    html = client.get("/snep/admin/login").get_data(as_text=True)
    assert "sessão do painel expirou" in html
    assert client.get("/snep/admin/cardapio").status_code == 302


def test_expired_form_in_json_gets_portuguese_message(csrf_app):
    r = csrf_app.test_client().post("/snep/admin/pedidos/novo", json={"items": []})
    assert r.status_code == 400 and "sessão do painel expirou" in r.json["error"]


def test_panel_form_does_not_expire_after_one_hour(app):
    assert app.config["WTF_CSRF_TIME_LIMIT"] is None


def test_public_order_api_does_not_need_csrf_token(csrf_app):
    r = csrf_app.test_client().post("/snep/api/pedido", json={"items": []})
    assert r.is_json and r.json["ok"] is False  # resposta da própria rota, não um bloqueio de CSRF


def test_production_refuses_to_start_with_default_secret_key():
    class Production(TestConfig):
        PRODUCTION = True
        SECRET_KEY = "dev-key-troque-em-producao"

    with pytest.raises(RuntimeError):
        create_app(Production)


def test_create_admin_command(app, tenant):
    result = app.test_cli_runner().invoke(args=["create-admin", "snep", "dono", "--password", PASSWORD])
    assert result.exit_code == 0, result.output
    user = AdminUser.query.filter_by(tenant_id=tenant.id, username="dono").one()
    assert user.check_password(PASSWORD)
    assert PASSWORD not in user.password_hash


def test_create_admin_command_refuses_short_password(app):
    result = app.test_cli_runner().invoke(args=["create-admin", "snep", "dono", "--password", "123"])
    assert result.exit_code != 0
    assert AdminUser.query.count() == 0


# ---------- cardápio ----------

def test_price_change_applies_to_new_orders(panel, tenant):
    product = Product.query.filter_by(name="Paulista").one()
    inteira = next(v for v in product.variants if v.label == "Inteira")
    r = panel.post(f"/snep/admin/cardapio/{premium().id}", data=product_form(product, **{f"price-{inteira.id}": "70,50"}))
    assert r.status_code == 302
    line = price_item(tenant, {"category_id": premium().id, "variant": "Inteira", "flavors": [product.id], "quantity": 1})
    assert line["unit_price"] == Decimal("70.50")


def test_invalid_price_saves_nothing(panel):
    product = Product.query.filter_by(name="Paulista").one()
    broto, inteira = product.variants
    before = (broto.price, inteira.price)
    panel.post(
        f"/snep/admin/cardapio/{premium().id}",
        data=product_form(product, **{f"price-{broto.id}": "45,00", f"price-{inteira.id}": "abc"}),
    )
    db.session.expire_all()
    assert (broto.price, inteira.price) == before


def test_rename_and_description_change(panel):
    product = Product.query.filter_by(name="Paulista").one()
    panel.post(
        f"/snep/admin/cardapio/{premium().id}",
        data=product_form(product, **{f"name-{product.id}": "Paulistana", f"desc-{product.id}": "Nova receita"}),
    )
    db.session.expire_all()
    assert (product.name, product.description) == ("Paulistana", "Nova receita")


def test_sold_out_flavor_disappears_from_menu(panel, tenant):
    product = Product.query.filter_by(name="Paulista").one()
    form = product_form(product)
    del form[f"active-{product.id}"]
    panel.post(f"/snep/admin/cardapio/{premium().id}", data=form)
    names = [p["name"] for c in data_from_db(tenant, "/x", {})["categories"] for p in c["products"]]
    assert "Paulista" not in names


def test_products_left_out_of_form_are_untouched(panel):
    first, second = premium().products[:2]
    panel.post(f"/snep/admin/cardapio/{premium().id}", data=product_form(first))
    db.session.expire_all()
    assert second.active is True


def test_product_of_another_category_is_ignored(panel):
    doce = Category.query.filter_by(slug="doces").one().products[0]
    panel.post(f"/snep/admin/cardapio/{premium().id}", data=product_form(doce, **{f"name-{doce.id}": "Invadido"}))
    db.session.expire_all()
    assert doce.name != "Invadido"


def test_add_flavor_with_sizes_of_the_category(panel):
    r = panel.post(
        f"/snep/admin/cardapio/{premium().id}/novo",
        data={"name": "Da Casa", "desc": "Receita nova", "newprice-0": "42", "newprice-1": "68,90"},
    )
    assert r.status_code == 302
    product = Product.query.filter_by(name="Da Casa").one()
    assert product.category_id == premium().id
    assert {(v.label, v.price, v.max_flavors) for v in product.variants} == {
        ("Broto", Decimal("42.00"), 1),
        ("Inteira", Decimal("68.90"), 2),
    }


def test_new_flavor_needs_at_least_one_price(panel):
    panel.post(f"/snep/admin/cardapio/{premium().id}/novo", data={"name": "Sem Preço", "desc": ""})
    assert Product.query.filter_by(name="Sem Preço").count() == 0


# ---------- bordas, adicionais, entrega ----------

def test_border_and_addon_prices(panel):
    border = Border.query.first()
    addon = Addon.query.first()
    panel.post(
        "/snep/admin/extras",
        data={
            f"border-price-{border.id}": "19,90",
            f"border-active-{border.id}": "on",
            f"addon-whole-{addon.id}": "17",
            f"addon-half-{addon.id}": "9,50",
        },
    )
    db.session.expire_all()
    assert border.price == Decimal("19.90") and border.active is True
    assert (addon.price_whole, addon.price_half, addon.active) == (Decimal("17.00"), Decimal("9.50"), False)


def test_neighborhood_fee_change(panel):
    hood = Neighborhood.query.first()
    panel.post("/snep/admin/entrega", data={f"fee-{hood.id}": "12,00", f"active-{hood.id}": "on"})
    db.session.expire_all()
    assert hood.fee == Decimal("12.00")


def test_add_neighborhood(panel, tenant):
    panel.post("/snep/admin/entrega/novo", data={"name": "Bairro Novo", "fee": "9"})
    assert Neighborhood.query.filter_by(tenant_id=tenant.id, name="Bairro Novo").one().fee == Decimal("9.00")


def test_duplicate_neighborhood_is_refused(panel, tenant):
    existing = Neighborhood.query.first()
    panel.post("/snep/admin/entrega/novo", data={"name": existing.name.upper(), "fee": "9"})
    assert Neighborhood.query.filter(db.func.lower(Neighborhood.name) == existing.name.lower()).count() == 1


# ---------- loja ----------

def store_form(tenant, **over):
    form = {"eta_minutes": tenant.eta_minutes, "pickup_minutes": tenant.pickup_minutes, "whatsapp": tenant.whatsapp, "status": "auto"}
    for day, span in json.loads(tenant.hours_json).items():
        if span:
            form[f"open-{day}"] = f"{span[0] // 60:02d}:{span[0] % 60:02d}"
            form[f"close-{day}"] = f"{span[1] // 60:02d}:{span[1] % 60:02d}"
        else:
            form[f"closed-{day}"] = "on"
    form.update(over)
    return form


def test_close_store_manually(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, status="closed"))
    db.session.expire_all()
    assert is_open(tenant) is False


def test_back_to_automatic_schedule(panel, tenant):
    tenant.is_open_override = True
    db.session.commit()
    panel.post("/snep/admin/loja", data=store_form(tenant, status="auto"))
    db.session.expire_all()
    assert tenant.is_open_override is None


def test_change_opening_hours_and_eta(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, eta_minutes="40", **{"open-2": "17:30", "close-2": "23:00"}))
    db.session.expire_all()
    assert tenant.eta_minutes == 40
    assert json.loads(tenant.hours_json)["2"] == [17 * 60 + 30, 23 * 60]
    assert json.loads(tenant.hours_json)["1"] is None  # segunda continua fechado


def test_closing_before_opening_is_refused(panel, tenant):
    before = tenant.hours_json
    panel.post("/snep/admin/loja", data=store_form(tenant, **{"open-2": "22:00", "close-2": "18:00"}))
    db.session.expire_all()
    assert tenant.hours_json == before


def test_invalid_whatsapp_is_refused(panel, tenant):
    before = tenant.whatsapp
    panel.post("/snep/admin/loja", data=store_form(tenant, whatsapp="abc"))
    db.session.expire_all()
    assert tenant.whatsapp == before


# ---------- pedidos ----------

def make_order(tenant, name="Ana"):
    order = Order(tenant_id=tenant.id, customer_name=name, customer_phone="11999990000", total=Decimal("65"))
    db.session.add(order)
    db.session.commit()
    return order


def test_orders_page_lists_orders(panel, tenant):
    make_order(tenant, name="Cliente Visível")
    assert "Cliente Visível" in panel.get("/snep/admin/pedidos").get_data(as_text=True)


def test_confirm_order(panel, tenant):
    order = make_order(tenant)
    panel.post(f"/snep/admin/pedidos/{order.id}/status", data={"status": "confirmado"})
    db.session.expire_all()
    assert order.status == "confirmado"


def test_unknown_status_is_refused(panel, tenant):
    order = make_order(tenant)
    r = panel.post(f"/snep/admin/pedidos/{order.id}/status", data={"status": "hackeado"})
    db.session.expire_all()
    assert r.status_code == 400
    assert order.status == "pendente"


# ---------- senha ----------

def test_change_password(panel, client, admin):
    panel.post("/snep/admin/senha", data={"current": PASSWORD, "new": "outra-senha-9", "confirm": "outra-senha-9"})
    panel.post("/snep/admin/logout")
    login(client, password=PASSWORD)
    assert client.get("/snep/admin/cardapio").status_code == 302
    login(client, password="outra-senha-9")
    assert client.get("/snep/admin/cardapio").status_code == 200


def test_change_password_needs_current_password(panel, admin):
    panel.post("/snep/admin/senha", data={"current": "errada", "new": "outra-senha-9", "confirm": "outra-senha-9"})
    db.session.expire_all()
    assert admin.check_password(PASSWORD)


# ---------- valores em reais ----------

@pytest.mark.parametrize(
    "text, value",
    [("65", "65.00"), ("65,5", "65.50"), ("65.90", "65.90"), ("R$ 1.234,56", "1234.56"), (" 0 ", "0.00")],
)
def test_parse_money_accepts_brazilian_formats(text, value):
    assert parse_money(text) == Decimal(value)


@pytest.mark.parametrize("text", ["", "abc", "-5", "1.234", "12,345", "99999999", "NaN", "1e3"])
def test_parse_money_rejects_invalid_values(text):
    with pytest.raises(ValueError):
        parse_money(text)
