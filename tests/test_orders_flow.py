"""Parte 1 de comandas: origem do pedido, novas etapas, relatório por canal e etiqueta para a Zebra."""
from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Category, Order, Product, utcnow
from app.services.hours import local_time
from app.services.reports import sales_report
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


def site_order(client, withdraw=True):
    p = Product.query.filter_by(name="Paulista").one()
    c = Category.query.filter_by(slug="premium").one()
    data = {"withdraw": withdraw, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Dinheiro",
            "change_for": "100", "items": [{"category_id": c.id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}]}
    if not withdraw:
        data.update(street="Rua A", number="10", neighborhood="Bairro Alto", reference="Portão azul")
    r = client.post("/snep/api/pedido", json=data)
    assert r.status_code == 200, r.json
    return db.session.get(Order, r.json["order_id"])


def add(tenant, channel="site", status="confirmado", total="50", delivery=False):
    o = Order(tenant_id=tenant.id, customer_name="X", customer_phone="", channel=channel, status=status,
              total=Decimal(total), delivery=delivery, created_at=utcnow())
    db.session.add(o)
    db.session.commit()
    return o


def test_site_order_records_channel_and_delivery(client, open_store):
    assert site_order(client, withdraw=False).channel == "site"
    o = Order.query.order_by(Order.id.desc()).first()
    assert o.delivery is True
    assert site_order(client, withdraw=True).delivery is False


@pytest.mark.parametrize("status", ["confirmado", "saiu", "entregue"])
def test_sold_statuses_count_in_reports(tenant, status):
    o = add(tenant, status=status, total="70")
    day = local_time(o.created_at).date()
    assert sales_report(tenant, day, day)["revenue"] == Decimal("70")


def test_report_splits_online_and_in_store(tenant):
    add(tenant, "site", total="100")
    add(tenant, "balcao", total="40")
    add(tenant, "mesa", total="30")
    add(tenant, "telefone", total="25")
    add(tenant, "balcao", status="pendente", total="999")
    day = local_time(utcnow()).date()
    r = sales_report(tenant, day, day)
    channels = {c["label"]: (c["orders"], c["revenue"]) for c in r["by_channel"]}
    assert channels == {"Site": (1, Decimal("100")), "Balcão": (1, Decimal("40")), "Mesa": (1, Decimal("30")),
                        "Telefone/WhatsApp": (1, Decimal("25"))}
    assert r["online_share"] == pytest.approx(100 / 195 * 100, abs=0.1)


def test_status_buttons_follow_the_flow(panel, tenant):
    o = add(tenant, status="confirmado", delivery=False, channel="balcao")
    panel.post(f"/snep/admin/pedidos/{o.id}/status", data={"status": "entregue"})
    db.session.expire_all()
    assert o.status == "entregue" and o.delivered_at is not None
    assert panel.post(f"/snep/admin/pedidos/{o.id}/status", data={"status": "voando"}).status_code == 400


def test_orders_page_shows_channel_and_type(panel, tenant, client, open_store):
    site_order(client, withdraw=False)
    add(tenant, "mesa", status="confirmado")
    html = panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert "Site" in html and "Entrega" in html and "Mesa" in html


# ---------- etiqueta para a Zebra ----------

def test_label_has_everything_the_kitchen_and_courier_need(panel, client, open_store):
    o = site_order(client, withdraw=False)
    html = panel.get(f"/snep/admin/pedidos/{o.id}/etiqueta").get_data(as_text=True)
    for text in (f"#{o.id}", "Ana", "Rua A, 10", "Bairro Alto", "Portão azul", "Paulista", "Inteira",
                 "Dinheiro", "Troco para R$ 100,00", "ENTREGA"):
        assert text in html, text
    assert "size: 100mm 150mm" in html


def test_label_size_comes_from_store_settings(panel, tenant, client, open_store):
    tenant.label_width_mm, tenant.label_height_mm = 100, 50
    db.session.commit()
    o = site_order(client)
    assert "size: 100mm 50mm" in panel.get(f"/snep/admin/pedidos/{o.id}/etiqueta").get_data(as_text=True)


def test_mark_printed(panel, client, open_store):
    o = site_order(client)
    assert panel.post(f"/snep/admin/pedidos/{o.id}/impresso").status_code == 200
    db.session.expire_all()
    assert o.printed_at is not None


def test_confirm_sends_to_print_when_auto_print_on(panel, tenant, client, open_store):
    o = site_order(client)
    r = panel.post(f"/snep/admin/pedidos/{o.id}/status", data={"status": "confirmado"})
    assert f"imprimir={o.id}" in r.headers["Location"]
    tenant.auto_print = False
    db.session.commit()
    o2 = site_order(client)
    r = panel.post(f"/snep/admin/pedidos/{o2.id}/status", data={"status": "confirmado"})
    assert "imprimir" not in r.headers["Location"]


def test_staff_can_print(client, tenant, open_store):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    o = site_order(client)
    login(client, username="caixa")
    assert client.get(f"/snep/admin/pedidos/{o.id}/etiqueta").status_code == 200


def test_printer_settings_in_store_page(panel, tenant):
    from tests.test_admin import store_form

    panel.post("/snep/admin/loja", data=store_form(tenant, label_size="100x100", auto_print="on"))
    db.session.expire_all()
    assert (tenant.label_width_mm, tenant.label_height_mm, tenant.auto_print) == (100, 100, True)
    panel.post("/snep/admin/loja", data=store_form(tenant, label_size="100x150"))
    db.session.expire_all()
    assert tenant.auto_print is False
