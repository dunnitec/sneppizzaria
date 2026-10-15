from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Addon, Border, Category, Product
from app.services.pricing import OrderError, price_item


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def variant_price(product, label):
    return next(Decimal(str(v.price)) for v in product.variants if v.label == label)


def cheapest_and_dearest(slug, label):
    products = sorted(cat(slug).products, key=lambda p: variant_price(p, label))
    assert variant_price(products[0], label) < variant_price(products[-1], label)
    return products[0], products[-1]


def item(slug, label, flavors, **extra):
    return {"category_id": cat(slug).id, "variant": label, "flavors": [p.id for p in flavors], "quantity": 1, **extra}


def test_single_flavor_uses_price_from_database(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    line = price_item(tenant, item("premium", "Inteira", [paulista]))
    assert line["unit_price"] == variant_price(paulista, "Inteira")
    assert line["product_names"] == "Paulista"
    assert line["variant_label"] == "Inteira"


def test_price_sent_by_browser_is_ignored(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    line = price_item(tenant, item("premium", "Inteira", [paulista], unit_price=0.01))
    assert line["unit_price"] == variant_price(paulista, "Inteira")


def test_half_and_half_charges_most_expensive_flavor(tenant):
    cheap, dear = cheapest_and_dearest("premium", "Inteira")
    line = price_item(tenant, item("premium", "Inteira", [cheap, dear]))
    assert line["unit_price"] == variant_price(dear, "Inteira")
    assert line["product_names"] == f"1/2 {cheap.name} + 1/2 {dear.name}"


def test_quantity_multiplies_line_total(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    line = price_item(tenant, item("premium", "Broto", [paulista], quantity=3))
    assert line["quantity"] == 3
    assert line["line_total"] == variant_price(paulista, "Broto") * 3


def test_metro_has_fixed_price_whatever_the_flavors(tenant):
    metro = cat("metro")
    fixed = variant_price(metro.products[0], "Combo")
    cheap, dear = cheapest_and_dearest("premium", "Inteira")
    line = price_item(tenant, {"category_id": metro.id, "flavors": [dear.id, cheap.id], "quantity": 1})
    assert line["unit_price"] == fixed
    assert line["product_names"] == f"{metro.name}: {dear.name} + {cheap.name}"


def test_metro_rejects_sweet_flavors(tenant):
    doce = cat("doces").products[0]
    with pytest.raises(OrderError):
        price_item(tenant, {"category_id": cat("metro").id, "flavors": [doce.id], "quantity": 1})


def test_border_price_is_added_and_group_is_named(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    border = Border.query.filter_by(group_name="Borda Vulcão", name="Catupiry").one()
    line = price_item(tenant, item("premium", "Inteira", [paulista], border_id=border.id))
    assert line["unit_price"] == variant_price(paulista, "Inteira") + Decimal(str(border.price))
    assert line["border_name"] == "Vulcão - Catupiry"


def test_addons_use_whole_price_on_whole_pizza(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    bacon = Addon.query.filter_by(name="Bacon").one()
    line = price_item(tenant, item("premium", "Inteira", [paulista], addons=[{"id": bacon.id, "qty": 2}]))
    assert line["unit_price"] == variant_price(paulista, "Inteira") + 2 * Decimal(str(bacon.price_whole))
    assert line["addon_names"] == "2x Bacon"


def test_addons_use_half_price_on_broto(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    bacon = Addon.query.filter_by(name="Bacon").one()
    line = price_item(tenant, item("premium", "Broto", [paulista], addons=[{"id": bacon.id, "qty": 1}]))
    assert line["unit_price"] == variant_price(paulista, "Broto") + Decimal(str(bacon.price_half))


def test_addons_rejected_outside_premium_line(tenant):
    promo = cat("promocionais").products[0]
    bacon = Addon.query.filter_by(name="Bacon").one()
    with pytest.raises(OrderError):
        price_item(tenant, item("promocionais", "Grande (8 pedaços)", [promo], addons=[{"id": bacon.id, "qty": 1}]))


def test_more_than_five_addons_rejected(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    bacon = Addon.query.filter_by(name="Bacon").one()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", [paulista], addons=[{"id": bacon.id, "qty": 6}]))


def test_negative_addon_quantity_rejected(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    bacon = Addon.query.filter_by(name="Bacon").one()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", [paulista], addons=[{"id": bacon.id, "qty": -3}]))


def test_flavors_from_different_lines_cannot_be_mixed(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    doce = cat("doces").products[0]
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", [paulista, doce]))


def test_too_many_flavors_for_size_rejected(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Broto", [paulista, paulista]))


def test_sold_out_flavor_rejected(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    paulista.active = False
    db.session.commit()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", [paulista]))


def test_unknown_size_rejected(tenant):
    paulista = Product.query.filter_by(name="Paulista").one()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Gigante", [paulista]))


@pytest.mark.parametrize("quantity", [0, -1, 51, "abc"])
def test_invalid_quantity_rejected(tenant, quantity):
    paulista = Product.query.filter_by(name="Paulista").one()
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", [paulista], quantity=quantity))


def test_item_without_flavors_rejected(tenant):
    with pytest.raises(OrderError):
        price_item(tenant, item("premium", "Inteira", []))
