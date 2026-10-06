import json

import pytest

from app.models import Addon, Border, Category, Neighborhood, Order, Product, ProductVariant, Tenant
from seed import SeedError, seed_from_file
from tests.conftest import CARDAPIO


def _expected(cardapio):
    products = [p for c in cardapio["categories"] for p in c["products"]]
    return {
        "categories": len(cardapio["categories"]),
        "products": len(products),
        "variants": sum(len(p["variants"]) for p in products),
        "addons": len(cardapio["addons"]),
        "borders": len(cardapio["borders"]),
        "neighborhoods": len(cardapio["neighborhoods"]),
    }


def _counts():
    return {
        "categories": Category.query.count(),
        "products": Product.query.count(),
        "variants": ProductVariant.query.count(),
        "addons": Addon.query.count(),
        "borders": Border.query.count(),
        "neighborhoods": Neighborhood.query.count(),
    }


def test_first_import_loads_whole_menu(app, cardapio):
    assert _counts() == _expected(cardapio)


def test_reimport_without_reset_is_refused(app, cardapio):
    with pytest.raises(SeedError):
        seed_from_file(CARDAPIO)
    assert _counts() == _expected(cardapio)


def test_reimport_with_reset_does_not_duplicate(app, cardapio):
    seed_from_file(CARDAPIO, reset=True)
    assert _counts() == _expected(cardapio)


def test_reset_leaves_other_tenants_untouched(app, cardapio, tmp_path):
    other = dict(cardapio, tenant=dict(cardapio["tenant"], slug="outra", name="Outra Pizzaria"))
    other_file = tmp_path / "outra.json"
    other_file.write_text(json.dumps(other), encoding="utf-8")
    seed_from_file(other_file)

    seed_from_file(CARDAPIO, reset=True)

    outra = Tenant.query.filter_by(slug="outra").one()
    assert Product.query.filter_by(tenant_id=outra.id).count() == _expected(cardapio)["products"]


def test_reset_keeps_order_history(app, tenant):
    from app.extensions import db

    db.session.add(Order(tenant_id=tenant.id, customer_name="Ana", customer_phone="11999990000"))
    db.session.commit()

    seed_from_file(CARDAPIO, reset=True)

    assert Order.query.count() == 1


def test_only_premium_category_allows_addons(app):
    flags = {c.slug: c.allows_addons for c in Category.query.all()}
    assert flags == {"promocionais": False, "premium": True, "doces": False, "metro": False}
