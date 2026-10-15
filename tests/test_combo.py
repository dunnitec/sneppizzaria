"""Combo de preço fixo (categoria kind="metro"): Combo Pizza Trem, configurável pelo dono."""
import json
from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Border, Category, Order
from app.services.menu_data import data_from_db
from app.services.pricing import OrderError, price_item
from tests.test_admin import panel, admin  # noqa: F401  (fixtures do painel)


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def combo():
    return cat("metro")


def combo_item(flavors, **extra):
    return {"category_id": combo().id, "flavors": [p.id for p in flavors], "quantity": 1, **extra}


def premium_flavors(n):
    return cat("premium").products[:n]


# ---------- configuração inicial (igual ao banner) ----------

def test_seeded_combo_matches_the_banner(tenant):
    c = combo()
    assert c.name == "Combo Pizza Trem"
    assert json.loads(c.combo_sources) == ["premium"]
    variant = c.products[0].variants[0]
    assert (variant.price, variant.max_flavors) == (Decimal("169.90"), 4)
    assert c.combo_extras.splitlines() == ["1 Kuat 2L", "Borda Caracol de Catupiry", "1 Broto Brigadeiro"]


# ---------- preço e regras ----------

def test_combo_price_is_fixed_and_lists_the_extras(tenant):
    flavors = premium_flavors(4)
    line = price_item(tenant, combo_item(flavors))
    assert line["unit_price"] == Decimal("169.90")
    assert line["product_names"] == "Combo Pizza Trem: " + " + ".join(p.name for p in flavors)
    assert line["extras"] == "1 Kuat 2L, Borda Caracol de Catupiry, 1 Broto Brigadeiro"


def test_combo_rejects_flavor_outside_allowed_lines(tenant):
    promo = cat("promocionais").products[0]
    with pytest.raises(OrderError):
        price_item(tenant, combo_item([promo]))


def test_combo_follows_lines_chosen_by_owner(tenant):
    combo().combo_sources = json.dumps(["promocionais", "premium"])
    db.session.commit()
    promo = cat("promocionais").products[0]
    assert price_item(tenant, combo_item([promo]))["unit_price"] == Decimal("169.90")


def test_combo_does_not_take_a_paid_border(tenant):
    border = Border.query.first()
    with pytest.raises(OrderError):
        price_item(tenant, combo_item(premium_flavors(1), border_id=border.id))


def test_combo_choice_is_required_when_owner_sets_options(tenant):
    c = combo()
    c.combo_choice_label = "Sabor do Kuat 2L"
    c.combo_choice_options = "Guaraná, Guaraná Zero"
    db.session.commit()
    with pytest.raises(OrderError):
        price_item(tenant, combo_item(premium_flavors(1)))
    with pytest.raises(OrderError):
        price_item(tenant, combo_item(premium_flavors(1), combo_choice="Uva"))
    line = price_item(tenant, combo_item(premium_flavors(1), combo_choice="Guaraná Zero"))
    assert "Sabor do Kuat 2L: Guaraná Zero" in line["extras"]


def test_combo_without_options_ignores_choice(tenant):
    line = price_item(tenant, combo_item(premium_flavors(1), combo_choice="qualquer coisa"))
    assert "qualquer coisa" not in line["extras"]


# ---------- site e pedido ----------

def test_menu_data_exposes_combo_settings(tenant):
    d = data_from_db(tenant, "/x", {})
    metro = next(c for c in d["categories"] if c["kind"] == "metro")
    assert metro["combo"] == {
        "sources": ["premium"],
        "extras": ["1 Kuat 2L", "Borda Caracol de Catupiry", "1 Broto Brigadeiro"],
        "choice_label": "",
        "choice_options": [],
    }


def test_whatsapp_message_lists_what_comes_with_the_combo(client, open_store):
    r = client.post(
        "/snep/api/pedido",
        json={"withdraw": True, "customer_name": "Ana", "customer_phone": "119", "payment_method": "Pix",
              "items": [combo_item(premium_flavors(2))]},
    )
    assert r.status_code == 200, r.json
    message = unquote(r.json["wa_link"])
    assert "Acompanha: 1 Kuat 2L, Borda Caracol de Catupiry, 1 Broto Brigadeiro" in message
    assert Order.query.one().items[0].extras.startswith("1 Kuat 2L")


# ---------- painel ----------

def combo_form(**over):
    form = {"name": "Combo Pizza Trem", "sources": ["premium"], "max_flavors": "4",
            "extras": "1 Kuat 2L\nBorda Caracol de Catupiry\n1 Broto Brigadeiro",
            "choice_label": "", "choice_options": ""}
    form.update(over)
    return form


def test_owner_edits_combo_in_panel(panel):
    r = panel.post(f"/snep/admin/cardapio/{combo().id}/combo", data=combo_form(
        name="Combo Família", sources=["premium", "promocionais"], max_flavors="3",
        extras="1 Coca 2L\n\n  1 Broto Doce  ", choice_label="Refrigerante", choice_options="Coca, Coca Zero"))
    assert r.status_code == 302
    db.session.expire_all()
    c = combo()
    assert c.name == "Combo Família"
    assert sorted(json.loads(c.combo_sources)) == ["premium", "promocionais"]
    assert c.products[0].variants[0].max_flavors == 3
    assert c.combo_extras.splitlines() == ["1 Coca 2L", "1 Broto Doce"]
    assert (c.combo_choice_label, c.combo_choice_options) == ("Refrigerante", "Coca, Coca Zero")


def test_combo_needs_at_least_one_line(panel):
    panel.post(f"/snep/admin/cardapio/{combo().id}/combo", data=combo_form(sources=[]))
    db.session.expire_all()
    assert json.loads(combo().combo_sources) == ["premium"]


def test_combo_cannot_use_itself_or_unknown_lines(panel):
    panel.post(f"/snep/admin/cardapio/{combo().id}/combo", data=combo_form(sources=["premium", "metro", "inventada"]))
    db.session.expire_all()
    assert json.loads(combo().combo_sources) == ["premium"]


@pytest.mark.parametrize("n", ["0", "9", "abc"])
def test_combo_flavor_count_is_validated(panel, n):
    panel.post(f"/snep/admin/cardapio/{combo().id}/combo", data=combo_form(max_flavors=n))
    db.session.expire_all()
    assert combo().products[0].variants[0].max_flavors == 4


def test_combo_settings_route_refuses_regular_categories(panel):
    r = panel.post(f"/snep/admin/cardapio/{cat('premium').id}/combo", data=combo_form())
    assert r.status_code == 400
