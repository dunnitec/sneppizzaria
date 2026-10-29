"""Item sem borda (calzone): o dono desmarca “aceita borda” e o site, o PDV e o servidor não oferecem borda."""
import pytest

from app.extensions import db
from app.models import Border, Category, Product
from app.services.menu_data import data_from_db
from app.services.pricing import OrderError, price_item
from tests.test_admin import admin, panel  # noqa: F401


def premium():
    return Category.query.filter_by(slug="premium").one()


def test_new_item_without_border(panel, tenant):
    c = premium()
    panel.post(f"/snep/admin/cardapio/{c.id}/novo", data={"name": "Calzone de Frango", "desc": "frango",
                                                         "newprice-0": "30", "border_field": "1"})
    panel.post(f"/snep/admin/cardapio/{c.id}/novo", data={"name": "Frango Especial", "newprice-0": "30",
                                                         "border_field": "1", "border": "on"})
    assert Product.query.filter_by(name="Calzone de Frango").one().accepts_border is False
    assert Product.query.filter_by(name="Frango Especial").one().accepts_border is True


def test_edit_turns_border_off(panel, tenant):
    c = premium()
    p = c.products[0]
    data = {"border_field": "1", f"name-{p.id}": p.name, f"active-{p.id}": "on"}
    panel.post(f"/snep/admin/cardapio/{c.id}", data=data)
    db.session.expire_all()
    assert db.session.get(Product, p.id).accepts_border is False
    panel.post(f"/snep/admin/cardapio/{c.id}", data={**data, f"border-{p.id}": "on"})
    db.session.expire_all()
    assert db.session.get(Product, p.id).accepts_border is True


def test_border_refused_on_calzone_even_half_and_half(app, tenant):
    c = premium()
    calzone, other = c.products[0], c.products[1]
    calzone.accepts_border = False
    db.session.commit()
    big = max(c.sizes(), key=lambda s: s["max_flavors"])["label"]
    border = Border.query.filter_by(tenant_id=tenant.id, active=True).first()
    with pytest.raises(OrderError, match="não aceita borda"):
        price_item(tenant, {"category_id": c.id, "variant": big, "flavors": [other.id, calzone.id],
                            "border_id": border.id, "quantity": 1})
    assert price_item(tenant, {"category_id": c.id, "variant": big, "flavors": [calzone.id], "quantity": 1})
    with app.test_request_context():
        d = data_from_db(tenant, order_url="#", assets={})
    flags = {p["name"]: p.get("no_border", False) for k in d["categories"] for p in k["products"]}
    assert flags[calzone.name] is True and flags[other.name] is False
