"""Acompanhamento no topo do site: pedido em andamento aparece; entregue, cancelado ou antigo some."""
from datetime import timedelta

from app.extensions import db
from app.models import Order
from tests.test_coupons import send


def token_of(r):
    return r.json["track_url"].rsplit("/", 1)[-1]


def live(client, *tokens):
    return client.get("/snep/api/acompanhar?t=" + ",".join(tokens)).json["orders"]


def test_open_order_shows_until_finished(client, tenant, open_store):
    r = send(client, coupon="")
    token = token_of(r)
    shown = live(client, token)
    assert len(shown) == 1 and shown[0]["ticket"] == r.json["ticket"] and shown[0]["url"].endswith(token)
    assert shown[0]["steps"][0] == {"label": "Recebido", "done": True}
    order = db.session.get(Order, r.json["order_id"])
    order.status = "entregue"
    db.session.commit()
    assert live(client, token) == []


def test_cancelled_and_old_orders_disappear(client, tenant, open_store):
    a, b = token_of(send(client, coupon="")), token_of(send(client, coupon="", phone="11977770000"))
    oa = Order.query.filter_by(track_token=a).one()
    ob = Order.query.filter_by(track_token=b).one()
    oa.status = "cancelado"
    ob.created_at = ob.created_at - timedelta(hours=13)
    db.session.commit()
    assert live(client, a, b) == []


def test_unknown_or_no_token(client, tenant):
    assert live(client, "nada") == [] and client.get("/snep/api/acompanhar").json["orders"] == []


def test_other_store_token_not_shown(client, tenant, open_store):
    from app.models import Tenant
    token = token_of(send(client, coupon=""))
    db.session.add(Tenant(slug="outra", name="Outra"))
    db.session.commit()
    assert client.get("/outra/api/acompanhar?t=" + token).json["orders"] == []


def test_logged_customer_sees_order_without_token(client, tenant, open_store):
    from tests.test_accounts import register
    register(client, phone="11966660000")
    send(client, coupon="", phone="11966660000")
    assert len(live(client)) == 1


def test_site_has_track_box(client, tenant):
    assert 'id="track-live"' in client.get("/snep/").get_data(as_text=True)
