"""Retirada na loja: tela da TV (preparando / pronto) e número grande no celular do cliente."""
from datetime import timedelta

from app.extensions import db
from app.models import utcnow
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401
from tests.test_receipt_eta import cat, site_order


def premium_item():
    p = cat("premium").products[0]
    return {"category_id": cat("premium").id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}


def confirmed_pickup(client, name="Ana Souza"):
    _, order = site_order(client, [premium_item()])
    order.status, order.customer_name = "confirmado", name
    db.session.commit()
    return order


def test_board_splits_preparing_and_ready(client, panel, open_store):
    a, b = confirmed_pickup(client), confirmed_pickup(client, "Bruno Lima")
    _, deliver = site_order(client, [premium_item()], withdraw=False)
    deliver.status = "confirmado"
    db.session.commit()
    panel.post(f"/snep/admin/pedidos/{b.id}/pronto", headers={"X-Requested-With": "fetch"})
    data = panel.get("/snep/admin/retirada/tv/dados").json
    assert data["preparing"] == [{"ticket": a.ticket, "name": "Ana"}]
    assert data["ready"] == [{"ticket": b.ticket, "name": "Bruno"}]  # só primeiro nome; entrega não aparece


def test_board_hides_delivered_old_and_pending(client, panel, open_store):
    done = confirmed_pickup(client)
    done.status = "entregue"
    stale = confirmed_pickup(client)
    stale.ready_at = utcnow() - timedelta(hours=2)
    _, pending = site_order(client, [premium_item()])
    db.session.commit()
    data = panel.get("/snep/admin/retirada/tv/dados").json
    assert data == {"preparing": [], "ready": []}


def test_counter_order_shows_number_only(client, panel, open_store):
    o = confirmed_pickup(client, "Balcão")
    assert panel.get("/snep/admin/retirada/tv/dados").json["preparing"] == [{"ticket": o.ticket, "name": ""}]


def test_tv_page_needs_login_and_staff_can_open(client, tenant):
    assert client.get("/snep/admin/retirada/tv").status_code == 302
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert "Preparando" in client.get("/snep/admin/retirada/tv").get_data(as_text=True)


def test_orders_page_links_tv(panel):
    assert "/snep/admin/retirada/tv" in panel.get("/snep/admin/pedidos").get_data(as_text=True)


def test_track_page_big_number_and_ready(client, panel, open_store):
    order = confirmed_pickup(client)
    url = f"/snep/pedido/{order.track_token}"
    html = client.get(url).get_data(as_text=True)
    assert f"#{order.ticket}" in html and "Preparando" in html and 'data-ready="0"' in html
    panel.post(f"/snep/admin/pedidos/{order.id}/pronto", headers={"X-Requested-With": "fetch"})
    html = client.get(url).get_data(as_text=True)
    assert "PRONTO! Pode retirar no balcão" in html and 'data-ready="1"' in html


def test_track_page_delivery_has_no_pickup_number(client, open_store):
    _, order = site_order(client, [premium_item()], withdraw=False)
    assert "Seu número de retirada" not in client.get(f"/snep/pedido/{order.track_token}").get_data(as_text=True)
