"""Número do pedido volta a 1 a cada mês (por loja) e impressão automática do cupom."""
from datetime import datetime

from app.extensions import db
from app.models import Order, Tenant
from app.services import order_create
from tests.test_admin import admin, panel  # noqa: F401
from tests.test_orders_flow import site_order


def at(monkeypatch, *when):
    monkeypatch.setattr(order_create, "utcnow", lambda: datetime(*when))


def test_ticket_counts_inside_the_month(client, open_store):
    assert [site_order(client).ticket for _ in range(3)] == [1, 2, 3]


def test_ticket_restarts_when_the_month_turns_in_store_time(client, open_store, monkeypatch):
    at(monkeypatch, 2026, 12, 1, 2, 59)  # 23h59 de 30/11 em São Paulo: ainda novembro
    first, second = site_order(client), site_order(client)
    assert (first.ticket_month, first.ticket, second.ticket) == ("2026-11", 1, 2)
    at(monkeypatch, 2026, 12, 1, 3, 0)  # 00h00 de 01/12 em São Paulo
    third = site_order(client)
    assert (third.ticket_month, third.ticket) == ("2026-12", 1)
    assert third.id > second.id  # o número interno continua único


def test_ticket_is_per_store(client, tenant, open_store):
    site_order(client)
    other = Tenant(name="Outra", slug="outra", whatsapp="5511999999999")
    db.session.add(other)
    db.session.flush()
    db.session.add(Order(tenant_id=other.id, customer_name="X", customer_phone="", ticket_month="2026-11", ticket_number=7))
    db.session.commit()
    assert site_order(client).ticket == 2


def test_old_order_without_ticket_shows_its_id(tenant):
    o = Order(tenant_id=tenant.id, customer_name="X", customer_phone="")
    db.session.add(o)
    db.session.commit()
    assert o.ticket == o.id


def test_customer_and_panel_see_the_ticket_not_the_id(client, panel, open_store, monkeypatch):
    db.session.add(Order(tenant_id=Tenant.query.first().id, customer_name="Antigo", customer_phone=""))  # id 1
    db.session.commit()
    r = client.post("/snep/api/pedido", json=_payload())
    assert r.json["ticket"] == 1 and r.json["order_id"] == 2
    o = db.session.get(Order, 2)
    assert "Pedido #1\n" in o.whatsapp_message
    assert "#1</b>" in panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert 'class="num">#1<' in panel.get("/snep/admin/pedidos/2/etiqueta").get_data(as_text=True)
    assert panel.get("/snep/admin/pedidos/novos?desde=1").json["new"][0]["ticket"] == 1


def _payload():
    from app.models import Category, Product
    p, c = Product.query.filter_by(name="Paulista").one(), Category.query.filter_by(slug="premium").one()
    return {"withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Dinheiro",
            "change_for": "100", "items": [{"category_id": c.id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}]}


# ---------- impressão automática ----------

def test_receipts_can_open_inside_the_panel_for_auto_print(client, panel, open_store):
    o = site_order(client)
    assert panel.get(f"/snep/admin/pedidos/{o.id}/etiqueta").headers["X-Frame-Options"] == "SAMEORIGIN"
    assert panel.get("/snep/admin/pedidos").headers["X-Frame-Options"] == "DENY"  # o resto do painel segue protegido
