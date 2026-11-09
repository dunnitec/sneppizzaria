"""Combo do dia: item com dias da semana; aparece no topo do site nos dias dele e some nos outros."""
import json
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Category, Product, ProductVariant
from app.services.hours import store_weekday
from app.services.menu_data import data_from_db
from tests.test_admin import admin, panel  # noqa: F401


@pytest.fixture
def combos(tenant):
    line = Category(tenant_id=tenant.id, name="Combos", slug="combos", kind="lanche", sort_order=0,
                    sizes_json=json.dumps([{"label": "Único", "max_flavors": 1}]))
    db.session.add(line)
    db.session.flush()
    combo = Product(tenant_id=tenant.id, category_id=line.id, name="Calabresa + Coca 2L",
                    variants=[ProductVariant(label="Único", price=Decimal("59.90"), max_flavors=1)])
    db.session.add(combo)
    db.session.commit()
    return line, combo


def order(client, line, combo):
    return client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": line.id, "variant": "Único", "flavors": [combo.id], "quantity": 1}]})


def site_product(tenant, combo):
    return next((p for c in data_from_db(tenant, "/x", {})["categories"] for p in c["products"] if p["id"] == combo.id), None)


def test_today_combo_is_on_site_and_sells(client, tenant, open_store, combos):
    line, combo = combos
    combo.daily_days = str(store_weekday(tenant))
    db.session.commit()
    assert site_product(tenant, combo)["daily"] is True
    r = order(client, line, combo)
    assert r.status_code == 200 and r.json["total"] == 59.9


def test_other_day_combo_is_hidden_and_refused(client, tenant, open_store, combos):
    line, combo = combos
    combo.daily_days = str((store_weekday(tenant) + 1) % 7)
    db.session.commit()
    assert site_product(tenant, combo) is None
    r = order(client, line, combo)
    assert r.status_code == 400 and "combo do dia" in r.json["error"]


def test_regular_item_has_no_daily_flag(tenant, combos):
    _, combo = combos
    assert "daily" not in site_product(tenant, combo)


def test_owner_marks_days(panel, combos):
    line, combo = combos
    page = panel.get(f"/snep/admin/cardapio/{line.id}").get_data(as_text=True)
    assert f'name="daily-{combo.id}"' in page
    panel.post(f"/snep/admin/cardapio/{line.id}", data={
        "daily_field": "1", f"name-{combo.id}": combo.name, f"active-{combo.id}": "on",
        f"price-{combo.variants[0].id}": "59,90", f"daily-{combo.id}": ["6", "5", "9", "x"]})
    db.session.expire_all()
    assert combo.daily_days == "5,6"
    panel.post(f"/snep/admin/cardapio/{line.id}", data={
        "daily_field": "1", f"name-{combo.id}": combo.name, f"active-{combo.id}": "on", f"price-{combo.variants[0].id}": "59,90"})
    db.session.expire_all()
    assert combo.daily_days is None


def test_pizza_category_has_no_daily_option(panel):
    premium = Category.query.filter_by(slug="premium").one()
    assert "daily_field" not in panel.get(f"/snep/admin/cardapio/{premium.id}").get_data(as_text=True)


def test_site_has_daily_box(client, open_store):
    assert 'id="daily"' in client.get("/snep/").get_data(as_text=True)
