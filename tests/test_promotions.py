"""Promoções: preço no servidor, dias e período, dados do site e telas do painel."""
import json
from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Category, Order, Product, Promotion
from app.services.menu_data import data_from_db
from app.services.pricing import price_item
from app.services.promotions import describe, status, store_today
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def prod(name):
    return Product.query.filter_by(name=name).one()


def price_of(product, label):
    return next(Decimal(str(v.price)) for v in product.variants if v.label == label)


def promo(tenant, slug="premium", **over):
    p = Promotion(tenant_id=tenant.id, name="Promo teste", category_id=cat(slug).id, discount_type="percent",
                  value=Decimal("20"), active=True, show_popup=True)
    for k, v in over.items():
        setattr(p, k, v)
    db.session.add(p)
    db.session.commit()
    return p


def item(slug, label, flavors, **extra):
    return {"category_id": cat(slug).id, "variant": label, "flavors": [p.id for p in flavors], "quantity": 1, **extra}


# ---------- preço no servidor ----------

def test_percent_discount_on_one_size(tenant):
    promo(tenant, size_label="Inteira")
    paulista = prod("Paulista")
    line = price_item(tenant, item("premium", "Inteira", [paulista]))
    assert line["unit_price"] == (price_of(paulista, "Inteira") * Decimal("0.8")).quantize(Decimal("0.01"))
    assert line["promo_name"] == "Promo teste"
    broto = price_item(tenant, item("premium", "Broto", [paulista]))
    assert broto["unit_price"] == price_of(paulista, "Broto") and broto["promo_name"] == ""


def test_fixed_price_only_for_chosen_flavors(tenant):
    paulista, peperone = prod("Paulista"), prod("Peperone")
    promo(tenant, discount_type="price", value=Decimal("50"), size_label="Inteira", product_ids=json.dumps([paulista.id]))
    assert price_item(tenant, item("premium", "Inteira", [paulista]))["unit_price"] == Decimal("50.00")
    assert price_item(tenant, item("premium", "Inteira", [peperone]))["unit_price"] == price_of(peperone, "Inteira")


def test_half_and_half_still_charges_the_dearest_flavor(tenant):
    paulista, peperone = prod("Paulista"), prod("Peperone")
    promo(tenant, discount_type="price", value=Decimal("50"), size_label="Inteira", product_ids=json.dumps([paulista.id]))
    line = price_item(tenant, item("premium", "Inteira", [paulista, peperone]))
    assert line["unit_price"] == price_of(peperone, "Inteira")
    assert line["promo_name"] == ""  # o desconto não mudou o preço desta pizza


def test_promo_price_higher_than_regular_is_ignored(tenant):
    paulista = prod("Paulista")
    promo(tenant, discount_type="price", value=Decimal("999"), size_label="Inteira")
    assert price_item(tenant, item("premium", "Inteira", [paulista]))["unit_price"] == price_of(paulista, "Inteira")


@pytest.mark.parametrize("over", [
    {"active": False},
    {"ends_on": "yesterday"},
    {"starts_on": "tomorrow"},
    {"weekdays": "other_day"},
])
def test_promo_out_of_its_days_does_not_apply(tenant, over):
    today = store_today()
    values = {"yesterday": today - timedelta(days=1), "tomorrow": today + timedelta(days=1),
              "other_day": str((today.weekday() + 2) % 7)}
    promo(tenant, **{k: values.get(v, v) for k, v in over.items()})
    paulista = prod("Paulista")
    assert price_item(tenant, item("premium", "Inteira", [paulista]))["unit_price"] == price_of(paulista, "Inteira")


def test_promo_valid_today(tenant):
    today = store_today()
    p = promo(tenant, weekdays=str((today.weekday() + 1) % 7), starts_on=today, ends_on=today)
    assert status(p)[0] == "no_ar"
    paulista = prod("Paulista")
    assert price_item(tenant, item("premium", "Inteira", [paulista]))["unit_price"] < price_of(paulista, "Inteira")


def test_combo_discount(tenant):
    combo = cat("metro")
    regular = Decimal(str(combo.products[0].variants[0].price))
    promo(tenant, slug="metro", value=Decimal("10"))
    flavors = [p.id for p in cat("premium").products[:4]]
    line = price_item(tenant, {"category_id": combo.id, "flavors": flavors, "quantity": 1})
    assert line["unit_price"] == (regular * Decimal("0.9")).quantize(Decimal("0.01"))


def test_order_saves_promo_and_whatsapp_shows_it(client, open_store):
    promo(open_store, size_label="Inteira", name="Quarta Premium")
    paulista = prod("Paulista")
    r = client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [item("premium", "Inteira", [paulista], unit_price=0.01)]})
    body = r.get_json()
    assert body["ok"]
    order = db.session.get(Order, body["order_id"])
    assert order.items[0].promo_name == "Quarta Premium"
    assert order.total == (price_of(paulista, "Inteira") * Decimal("0.8")).quantize(Decimal("0.01"))
    assert "Promoção: Quarta Premium" in unquote(body["wa_link"])


# ---------- site ----------

def test_site_data_has_old_price_badge_and_popup(app, tenant):
    p = promo(tenant, size_label="Inteira", message="Só hoje!")
    promo(tenant, name="Não muda nada", discount_type="price", value=Decimal("999"), size_label="Inteira")
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    premium = next(c for c in d["categories"] if c["slug"] == "premium")
    v = next(v for v in premium["products"][0]["variants"] if v["label"] == "Inteira")
    assert v["regular"] > v["price"] and v["promo"] == "-20%"
    b = next(v for v in premium["products"][0]["variants"] if v["label"] == "Broto")
    assert "regular" not in b
    assert [x["name"] for x in d["promotions"]] == [p.name]
    assert d["promotions"][0]["message"] == "Só hoje!" and d["promotions"][0]["category"] == "premium"


def test_site_page_carries_promotions(client, tenant):
    promo(tenant)
    html = client.get("/snep/").get_data(as_text=True)
    assert '"promotions"' in html and "Promo teste" in html


def test_describe_is_readable(tenant):
    paulista = prod("Paulista")
    p = promo(tenant, discount_type="price", value=Decimal("49.9"), size_label="Inteira",
              product_ids=json.dumps([paulista.id]), weekdays="2,4")
    assert describe(p) == "Paulista (Pizzas Premium), Inteira por R$ 49,90 · às terças e quintas"


# ---------- painel ----------

def form(**over):
    premium = cat("premium")
    base = {"name": "Terça Premium", "category_id": premium.id, f"which-{premium.id}": "all", f"size-{premium.id}": "Inteira",
            "discount_type": "percent", "percent": "15", "days": [str(d) for d in range(7)], "show_popup": "on", "active": "on",
            "message": "Aproveite!"}
    base.update(over)
    return base


def test_owner_creates_promo(panel, tenant):
    r = panel.post("/snep/admin/promocoes/nova", data=form())
    assert r.status_code == 302
    p = Promotion.query.one()
    assert (p.name, p.discount_type, p.value, p.size_label, p.weekdays) == ("Terça Premium", "percent", Decimal("15.00"), "Inteira", None)
    page = panel.get("/snep/admin/promocoes").get_data(as_text=True)
    assert "Terça Premium" in page and "No ar agora" in page


def test_owner_creates_fixed_price_for_some_flavors(panel, tenant):
    paulista = prod("Paulista")
    premium = cat("premium")
    r = panel.post("/snep/admin/promocoes/nova", data=form(**{
        f"which-{premium.id}": "some", f"products-{premium.id}": [str(paulista.id)],
        "discount_type": "price", "price": "49,90", "days": ["2", "4"]}))
    assert r.status_code == 302
    p = Promotion.query.one()
    assert p.product_id_list() == [paulista.id] and p.value == Decimal("49.90") and p.weekdays == "2,4"


@pytest.mark.parametrize("over, msg", [
    ({"percent": "95"}, "vai de 1%"),
    ({"discount_type": "price", "price": "30,00", "size-{premium}": ""}, "um tamanho só"),
    ({"days": []}, "pelo menos um dia"),
    ({"which-{premium}": "some"}, "pelo menos um sabor"),
    ({"name": ""}, "nome da promoção"),
    ({"starts_on": "2026-12-10", "ends_on": "2026-12-01"}, "antes da data"),
])
def test_invalid_promo_is_not_saved(panel, tenant, over, msg):
    premium = cat("premium").id
    data = form(**{k.replace("{premium}", str(premium)): v for k, v in over.items()})
    r = panel.post("/snep/admin/promocoes/nova", data=data)
    assert r.status_code == 400
    assert msg in r.get_data(as_text=True)
    assert Promotion.query.count() == 0


def test_form_keeps_what_was_typed_after_error(panel, tenant):
    r = panel.post("/snep/admin/promocoes/nova", data=form(percent="95", message="Frase digitada"))
    assert "Frase digitada" in r.get_data(as_text=True)


def test_pause_edit_and_delete(panel, tenant):
    p = promo(tenant)
    panel.post(f"/snep/admin/promocoes/{p.id}/pausar")
    assert db.session.get(Promotion, p.id).active is False
    panel.post(f"/snep/admin/promocoes/{p.id}", data=form(name="Novo nome", percent="10"))
    p = db.session.get(Promotion, p.id)
    assert p.name == "Novo nome" and p.value == Decimal("10.00") and p.active is True
    panel.post(f"/snep/admin/promocoes/{p.id}/excluir")
    assert Promotion.query.count() == 0


def test_deleting_the_only_flavor_pauses_the_promo(panel, tenant):
    paulista = prod("Paulista")
    p = promo(tenant, product_ids=json.dumps([paulista.id]))
    panel.post(f"/snep/admin/cardapio/sabor/{paulista.id}/excluir")
    p = db.session.get(Promotion, p.id)
    assert p.active is False  # sem sabor, não pode virar “a categoria inteira”


def test_home_shows_promos_running(panel, tenant):
    promo(tenant)
    page = panel.get("/snep/admin/").get_data(as_text=True)
    assert "promoção no ar" in page


def test_staff_cannot_open_promotions(app, tenant):
    make_admin(tenant, "func").role = "funcionario"
    db.session.commit()
    c = app.test_client()
    login(c, username="func")
    r = c.get("/snep/admin/promocoes")
    assert r.status_code in (302, 403)
