"""Cupom de entrega grátis: desconta a taxa inteira, a taxa segue gravada no pedido (corrida do motoboy)."""
from decimal import Decimal

from app.extensions import db
from app.models import Coupon, Order
from app.services.menu_data import data_from_db
from tests.test_admin import admin, panel  # noqa: F401
from tests.test_coupons import make
from tests.test_delivery_km import km_store, net, site_order  # noqa: F401


def free(tenant, code="FRETE", max_km=None, **over):
    return make(tenant, code=code, kind="frete", value="0", max_km=max_km, **over)


def test_free_delivery_discounts_the_whole_fee(client, km_store, net):
    plain = site_order(client, customer_phone="11955554444").json
    free(km_store)
    r = site_order(client, coupon="FRETE")
    assert r.status_code == 200
    order = db.session.get(Order, r.json["order_id"])
    assert order.delivery_fee == Decimal("5.00") and order.discount == Decimal("5.00")
    assert Decimal(str(r.json["total"])) == Decimal(str(plain["total"])) - Decimal("5.00") == order.subtotal
    assert order.discount_note == "Entrega grátis, cupom FRETE" and order.coupon_code == "FRETE"


def test_free_delivery_not_for_pickup(client, km_store, net):
    free(km_store)
    r = site_order(client, coupon="FRETE", withdraw=True)
    assert r.status_code == 400 and "não vale para retirada" in r.json["error"]


def test_free_delivery_km_limit(client, km_store, net):
    km_store.km_max = Decimal("20")
    free(km_store, max_km=Decimal("5"))
    far = site_order(client, coupon="FRETE", street="Rua Longe")
    assert far.status_code == 400 and "até 5 km" in far.json["error"]
    assert site_order(client, coupon="FRETE").status_code == 200  # 1,3 km: vale


def bairro_order(client, neighborhood):
    from tests.test_pos import pizza
    return client.post("/snep/api/pedido", json={
        "customer_name": "Ana", "customer_phone": "11977776666", "payment_method": "Pix", "items": [pizza()],
        "withdraw": False, "street": "Rua A", "number": "1", "neighborhood": neighborhood, "coupon": "FRETE"})


def test_free_delivery_with_neighborhood_fee(client, tenant, open_store):
    from app.models import Neighborhood
    db.session.add(Neighborhood(tenant_id=tenant.id, name="Vila Teste", fee=Decimal("7.50")))
    db.session.commit()
    free(tenant)
    r = bairro_order(client, "Vila Teste")
    order = db.session.get(Order, r.json["order_id"])
    assert order.delivery_fee == order.discount == Decimal("7.50") and order.total == order.subtotal


def test_unknown_neighborhood_fee_warns_customer(client, tenant, open_store):
    free(tenant)
    r = bairro_order(client, "Bairro Novo")
    assert r.status_code == 400 and "calcular a entrega" in r.json["error"]


def test_showcase_text(tenant):
    free(tenant, max_km=Decimal("5"))
    c = data_from_db(tenant, "/x", {})["coupons"][0]
    assert c["type"] == "frete" and c["max_km"] == 5 and c["text"].startswith("Entrega grátis até 5 km")


def test_owner_creates_free_delivery_coupon(panel, tenant):
    panel.post("/snep/admin/cupons", data={"code": "fretegratis", "discount_type": "frete", "max_km": "5",
                                           "per_customer": "on", "show_on_site": "on"})
    c = Coupon.query.one()
    assert (c.code, c.discount_type, c.value, c.max_km) == ("FRETEGRATIS", "frete", Decimal("0"), Decimal("5.0"))
    html = panel.get("/snep/admin/cupons").get_data(as_text=True)
    assert "Entrega grátis até 5 km" in html and 'value="frete"' in html


def test_bad_km_is_rejected(panel, tenant):
    r = panel.post("/snep/admin/cupons", data={"code": "FRETE", "discount_type": "frete", "max_km": "abc"},
                   follow_redirects=True)
    assert Coupon.query.count() == 0 and "Valor inválido" in r.get_data(as_text=True)
