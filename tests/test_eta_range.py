"""Tempo mínimo e máximo de entrega e de retirada: "40 a 60 min" e previsão "19:40 a 20:00"."""
from datetime import timedelta
from urllib.parse import unquote

from app.extensions import db
from app.services.hours import local_time, wait_text
from tests.test_admin import admin, panel, store_form  # noqa: F401
from tests.test_receipt_eta import cat, site_order


def premium_item():
    p = cat("premium").products[0]
    return {"category_id": cat("premium").id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}


def test_store_saves_min_and_max(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, eta_min_minutes="40", eta_minutes="60",
                                                     pickup_min_minutes="20", pickup_minutes="30"))
    db.session.expire_all()
    assert (tenant.eta_min_minutes, tenant.eta_minutes, tenant.pickup_min_minutes, tenant.pickup_minutes) == (40, 60, 20, 30)
    assert wait_text(tenant, False) == "40 a 60 min" and wait_text(tenant, True) == "20 a 30 min"


def test_min_must_be_below_max(panel, tenant):
    r = panel.post("/snep/admin/loja", data=store_form(tenant, eta_min_minutes="70", eta_minutes="60"), follow_redirects=True)
    db.session.expire_all()
    assert tenant.eta_min_minutes is None and "menor que o máximo" in r.get_data(as_text=True)


def test_empty_min_keeps_single_time(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, eta_min_minutes="", eta_minutes="50"))
    db.session.expire_all()
    assert tenant.eta_min_minutes is None and wait_text(tenant, False) == "50 min"


def test_order_gets_range_everywhere(client, panel, open_store):
    open_store.eta_min_minutes, open_store.eta_minutes = 40, 60
    db.session.commit()
    r, order = site_order(client, [premium_item()], withdraw=False)
    assert order.eta_at - order.eta_min_at == timedelta(minutes=20)
    expected = f"{local_time(order.eta_min_at):%H:%M} a {local_time(order.eta_at):%H:%M}"
    assert r.json["eta"] == expected == order.eta_text()
    assert f"Previsão de entrega: {expected}" in unquote(r.json["wa_link"])
    assert f"PREVISÃO {expected}" in panel.get(f"/snep/admin/pedidos/{order.id}/etiqueta").get_data(as_text=True)
    assert "40 a 60 min" in client.get("/snep/").get_data(as_text=True)


def test_pickup_range(client, open_store):
    open_store.pickup_min_minutes, open_store.pickup_minutes = 20, 30
    db.session.commit()
    r, order = site_order(client, [premium_item()])
    assert " a " in r.json["eta"] and "Pronto para retirar: " in unquote(r.json["wa_link"])


def test_home_buttons_move_the_whole_range(panel, tenant):
    tenant.eta_min_minutes, tenant.eta_minutes = 40, 60
    db.session.commit()
    panel.post("/snep/admin/loja/tempo", data={"which": "entrega", "delta": "5"})
    db.session.expire_all()
    assert (tenant.eta_min_minutes, tenant.eta_minutes) == (45, 65)
    assert "45 a 65 min" in panel.get("/snep/admin/").get_data(as_text=True)
