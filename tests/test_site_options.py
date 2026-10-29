"""Tipo de endereço (casa, apartamento, condomínio) com acréscimo na entrega e opções do site (Aparência)."""
import json
from decimal import Decimal

from app.extensions import db
from app.models import Category, Customer, Neighborhood, Order, Product, Tenant
from app.services.site_options import DEFAULTS, color_css, options
from tests.test_admin import admin, panel  # noqa: F401


def order(client, **extra):
    p = Product.query.filter_by(name="Paulista").one()
    c = Category.query.filter_by(slug="premium").one()
    hood = Neighborhood.query.filter_by(active=True).first()
    data = {"withdraw": False, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
            "street": "Rua A", "number": "10", "neighborhood": hood.name,
            "items": [{"category_id": c.id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}], **extra}
    r = client.post("/snep/api/pedido", json=data)
    assert r.status_code == 200, r.json
    return db.session.get(Order, r.json["order_id"]), hood


def test_apartment_pays_the_extra_and_shows_the_building(panel, client, open_store):
    panel.post("/snep/admin/entrega/endereco", data={"fee_apartment": "2,00", "fee_condo": ""})
    o, hood = order(client, residence="apartamento", building="Edifício Solar", complement="Bloco B apto 12")
    assert o.delivery_fee == hood.fee + Decimal("2.00")
    assert o.residence_text() == "Apartamento · Edifício Solar"
    assert "*Apartamento:* Edifício Solar" in o.whatsapp_message
    label = panel.get(f"/snep/admin/pedidos/{o.id}/etiqueta").get_data(as_text=True)
    assert "APARTAMENTO · EDIFÍCIO SOLAR" in label
    c = Customer.query.one()
    assert (c.residence, c.building) == ("apartamento", "Edifício Solar")


def test_house_and_condo_without_extra(client, open_store):
    o, hood = order(client, residence="casa", building="ignorado")
    assert o.delivery_fee == hood.fee and o.building == "" and o.residence_text() == ""
    o, hood = order(client, residence="condominio", building="Vila Verde")
    assert o.delivery_fee == hood.fee and o.residence_text() == "Condomínio · Vila Verde"
    o, _ = order(client, residence="castelo")
    assert o.residence is None


def test_site_options_saved_from_panel(panel, tenant):
    r = panel.post("/snep/admin/visual/site", data={"layout": "lista", "flavors": "steps", "color": "#1E88E5"})
    assert r.status_code == 302
    opts = options(db.session.get(Tenant, tenant.id))
    assert opts == {"show_filter": False, "flavors_one_page": False, "borders_grouped": False,
                    "layout": "lista", "color": "#1e88e5"}
    html = panel.get("/snep/").get_data(as_text=True)
    assert 'class="layout-lista"' in html and "--red:#1e88e5" in html
    assert '<label class="filter" hidden>' in html
    panel.post("/snep/admin/visual/site", data={"reset": "1"})
    assert options(db.session.get(Tenant, tenant.id)) == DEFAULTS


def test_bad_options_fall_back_to_default(tenant):
    tenant.site_options = json.dumps({"layout": "x", "color": "red", "unknown": 1})
    assert options(tenant) == DEFAULTS
    tenant.site_options = "{quebrado"
    assert options(tenant) == DEFAULTS
    assert color_css(DEFAULTS) == ""
