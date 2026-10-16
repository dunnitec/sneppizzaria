"""Onde cada tipo de borda aparece: por tamanho (ex.: Vulcão não vai em Broto) e por categoria."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Border, Category, Product
from app.services.menu_data import data_from_db
from app.services.pricing import OrderError, price_item
from tests.test_admin import admin, panel  # noqa: F401


def vulcao():
    return Border.query.filter_by(group_name="Borda Vulcão").all()


def item(slug, size, border):
    c = Category.query.filter_by(slug=slug).one()
    p = c.products[0]
    return {"category_id": c.id, "variant": size, "flavors": [p.id], "quantity": 1, "border_id": border.id}


def extras_form(**group_rules):
    """Formulário da aba Bordas e adicionais com tudo como está, mais as regras de um grupo."""
    form = {}
    for b in Border.query:
        form.update({f"border-group-{b.id}": b.group_name, f"border-name-{b.id}": b.name,
                     f"border-price-{b.id}": str(b.price), f"border-active-{b.id}": "on"})
    groups = sorted({b.group_name for b in Border.query})
    for i, g in enumerate(groups):
        form[f"grp-ids-{i}"] = ",".join(str(b.id) for b in Border.query.filter_by(group_name=g))
        rules = group_rules.get(g, {})
        form[f"grp-size-{i}"] = rules.get("sizes", ["Broto", "Inteira", "Grande (8 pedaços)"])
        form[f"grp-cat-{i}"] = rules.get("cats", ["promocionais", "premium", "doces"])
    return form


def test_by_default_border_works_everywhere(tenant):
    assert price_item(tenant, item("premium", "Broto", vulcao()[0]))["border_name"].startswith("Vulcão")


def test_owner_removes_vulcao_from_broto(panel, tenant):
    r = panel.post("/snep/admin/extras", data=extras_form(**{"Borda Vulcão": {"sizes": ["Inteira", "Grande (8 pedaços)"]}}))
    assert r.status_code == 302
    db.session.expire_all()
    assert all(b.allowed_for("premium", "Broto") is False for b in vulcao())
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Broto", vulcao()[0]))
    assert price_item(tenant, item("premium", "Inteira", vulcao()[0]))["unit_price"] > 0
    caracol = Border.query.filter_by(group_name="Borda Caracol").first()
    assert price_item(tenant, item("premium", "Broto", caracol))["border_name"].startswith("Caracol")


def test_owner_limits_border_to_a_category(panel, tenant):
    panel.post("/snep/admin/extras", data=extras_form(**{"Borda Tradicional": {"cats": ["doces"]}}))
    db.session.expire_all()
    trad = Border.query.filter_by(group_name="Borda Tradicional").first()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", trad))
    assert price_item(tenant, item("doces", "Inteira", trad))["border_name"].startswith("Tradicional")


def test_site_data_carries_rules(panel, tenant, app):
    panel.post("/snep/admin/extras", data=extras_form(**{"Borda Vulcão": {"sizes": ["Inteira"]}}))
    with app.test_request_context():
        borders = data_from_db(tenant, "/x", {})["borders"]
    v = next(b for b in borders if b["group"] == "Borda Vulcão")
    assert "Broto" in v["no_sizes"] and "Inteira" not in v["no_sizes"]
    assert v["no_categories"] == []


def test_new_border_in_existing_group_follows_group_rules(panel):
    panel.post("/snep/admin/extras", data=extras_form(**{"Borda Vulcão": {"sizes": ["Inteira"]}}))
    panel.post("/snep/admin/extras/borda/nova", data={"group": "Borda Vulcão", "name": "Doce de Leite", "price": "20"})
    b = Border.query.filter_by(name="Doce de Leite").one()
    assert b.allowed_for("premium", "Broto") is False and b.allowed_for("premium", "Inteira") is True


def test_new_size_created_later_is_allowed_by_default(panel):
    panel.post("/snep/admin/extras", data=extras_form(**{"Borda Vulcão": {"sizes": ["Inteira"]}}))
    db.session.expire_all()
    assert vulcao()[0].allowed_for("premium", "Gigante") is True


def test_extras_page_shows_where_each_group_appears(panel):
    html = panel.get("/snep/admin/extras").get_data(as_text=True)
    assert "Onde aparece" in html and "Broto" in html and "Pizzas Premium" in html


def test_rename_border_type_once_for_all_fillings(panel):
    form = extras_form()
    i = sorted({b.group_name for b in Border.query}).index("Borda Vulcão")
    for k in [k for k in form if k.startswith("border-group-")]:
        del form[k]
    form[f"grp-name-{i}"] = "Borda Vulcão Especial"
    panel.post("/snep/admin/extras", data=form)
    db.session.expire_all()
    assert Border.query.filter_by(group_name="Borda Vulcão").count() == 0
    assert Border.query.filter_by(group_name="Borda Vulcão Especial").count() == 5
