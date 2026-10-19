"""Cupom e mensagem mais claros (um sabor por linha, tipo da pizza) e previsão de chegada do pedido."""
from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Category, Order, Product
from app.services.hours import local_time
from app.services.order_display import item_view
from tests.test_admin import admin, panel  # noqa: F401


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def flavors(slug, n):
    return cat(slug).products[:n]


def site_order(client, items, withdraw=True):
    data = {"withdraw": withdraw, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix", "items": items}
    if not withdraw:
        data.update(street="Rua A", number="1", neighborhood="Bairro Alto")
    r = client.post("/snep/api/pedido", json=data)
    assert r.status_code == 200, r.json
    return r, db.session.get(Order, r.json["order_id"])


def half_half(slug="premium"):
    a, b = flavors(slug, 2)
    return {"category_id": cat(slug).id, "variant": "Inteira", "flavors": [a.id, b.id], "quantity": 1}, a, b


# ---------- um sabor por linha + tipo da pizza ----------

def test_half_and_half_shows_one_flavor_per_line_with_type(client, open_store):
    item, a, b = half_half()
    _, order = site_order(client, [item])
    view = item_view(order.items[0])
    assert view == {"head": f"1/2 {a.name}", "lines": [f"1/2 {b.name}"], "tag": "Premium"}


def test_single_flavor_has_type_and_no_extra_lines(client, open_store):
    p = cat("promocionais").products[0]
    _, order = site_order(client, [{"category_id": cat("promocionais").id, "variant": "Grande (8 pedaços)", "flavors": [p.id], "quantity": 1}])
    assert item_view(order.items[0]) == {"head": p.name, "lines": [], "tag": "Promocionais"}


def test_combo_lists_each_flavor(client, open_store):
    fl = flavors("premium", 3)
    _, order = site_order(client, [{"category_id": cat("metro").id, "flavors": [p.id for p in fl], "quantity": 1}])
    view = item_view(order.items[0])
    assert view["head"] == "Combo Pizza Trem" and view["lines"] == [p.name for p in fl] and view["tag"] is None


def test_type_kept_even_if_category_is_renamed_later(client, open_store):
    item, _, _ = half_half()
    _, order = site_order(client, [item])
    c = cat("premium")
    c.name = "Linha Ouro"
    db.session.commit()
    assert item_view(order.items[0])["tag"] == "Premium"


def test_receipt_prints_flavors_on_separate_lines_with_type(panel, client, open_store):
    item, a, b = half_half()
    _, order = site_order(client, [item])
    html = panel.get(f"/snep/admin/pedidos/{order.id}/etiqueta").get_data(as_text=True)
    assert f"1/2 {a.name}" in html and f"1/2 {b.name}" in html and ">PREMIUM<" in html
    assert html.index(f"1/2 {a.name}") < html.index(f"1/2 {b.name}")


def test_whatsapp_message_has_flavor_lines_and_type(client, open_store):
    item, a, b = half_half()
    r, _ = site_order(client, [item])
    msg = unquote(r.json["wa_link"])
    assert f"1x 1/2 {a.name} — Premium Inteira" in msg and f"\n   1/2 {b.name}" in msg


def test_orders_page_shows_flavor_lines(panel, client, open_store):
    item, a, b = half_half()
    site_order(client, [item])
    html = panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert f"1/2 {b.name}" in html and "Premium" in html


# ---------- previsão de chegada ----------

def test_delivery_eta_uses_delivery_minutes(client, tenant, open_store):
    tenant.eta_minutes, tenant.pickup_minutes = 50, 20
    db.session.commit()
    item, _, _ = half_half()
    r, order = site_order(client, [item], withdraw=False)
    assert order.eta_at - order.created_at == timedelta(minutes=50)
    expected = local_time(order.eta_at).strftime("%H:%M")
    assert r.json["eta"] == expected and r.json["eta_label"] == "Previsão de entrega"
    assert f"Previsão de entrega: {expected}" in unquote(r.json["wa_link"])


def test_pickup_eta_uses_pickup_minutes(client, tenant, open_store):
    tenant.eta_minutes, tenant.pickup_minutes = 50, 20
    db.session.commit()
    item, _, _ = half_half()
    r, order = site_order(client, [item], withdraw=True)
    assert order.eta_at - order.created_at == timedelta(minutes=20)
    assert r.json["eta_label"] == "Pronto para retirar"
    assert "Pronto para retirar às" in unquote(r.json["wa_link"])


def test_counter_order_gets_pickup_eta(panel, tenant):
    tenant.pickup_minutes = 15
    db.session.commit()
    item, _, _ = half_half()
    r = panel.post("/snep/admin/pedidos/novo", json={"channel": "balcao", "payment_method": "Pix", "items": [item]})
    o = db.session.get(Order, r.json["order_id"])
    assert o.eta_at - o.created_at == timedelta(minutes=15)


def test_site_shows_delivery_time(client, tenant):
    tenant.eta_minutes = 45
    db.session.commit()
    assert "~45 min" in client.get("/snep/").get_data(as_text=True)


def test_receipt_and_orders_page_show_eta(panel, client, open_store):
    item, _, _ = half_half()
    _, order = site_order(client, [item], withdraw=False)
    hhmm = local_time(order.eta_at).strftime("%H:%M")
    assert f"PREVISÃO {hhmm}" in panel.get(f"/snep/admin/pedidos/{order.id}/etiqueta").get_data(as_text=True)
    assert f"Previsão {hhmm}" in panel.get("/snep/admin/pedidos").get_data(as_text=True)


@pytest.mark.parametrize("which, delta, expected", [("entrega", "5", 55), ("entrega", "-5", 45), ("retirada", "5", 30)])
def test_quick_time_buttons_on_home(panel, tenant, which, delta, expected):
    tenant.eta_minutes, tenant.pickup_minutes = 50, 25
    db.session.commit()
    panel.post("/snep/admin/loja/tempo", data={"which": which, "delta": delta})
    db.session.expire_all()
    assert (tenant.eta_minutes if which == "entrega" else tenant.pickup_minutes) == expected


def test_quick_time_has_sane_limits(panel, tenant):
    tenant.pickup_minutes = 5
    db.session.commit()
    panel.post("/snep/admin/loja/tempo", data={"which": "retirada", "delta": "-5"})
    db.session.expire_all()
    assert tenant.pickup_minutes == 5


def test_store_page_sets_both_times(panel, tenant):
    from tests.test_admin import store_form

    form = store_form(tenant, eta_minutes="60", pickup_minutes="30")
    form.pop("eta", None)
    panel.post("/snep/admin/loja", data=form)
    db.session.expire_all()
    assert (tenant.eta_minutes, tenant.pickup_minutes) == (60, 30)


def test_home_shows_current_times(panel, tenant):
    tenant.eta_minutes, tenant.pickup_minutes = 50, 25
    db.session.commit()
    html = panel.get("/snep/admin/").get_data(as_text=True)
    assert "50 min" in html and "25 min" in html and "Tempo agora" in html
