"""Comandas de saída: motoboys, despacho de vários pedidos, conferência do dinheiro e baixa na volta."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Courier, Dispatch, Order, utcnow
from app.services.hours import local_time
from app.services.reports import sales_report
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


def ready(tenant, total="60", payment="Dinheiro", change=None, fee="7", hood="Centro"):
    o = Order(tenant_id=tenant.id, customer_name="Cliente", customer_phone="11999990000", status="confirmado",
              delivery=True, street="Rua A", number="1", neighborhood_name=hood, payment_method=payment,
              change_for=Decimal(change) if change else None, delivery_fee=Decimal(fee),
              subtotal=Decimal(total) - Decimal(fee), total=Decimal(total), created_at=utcnow())
    db.session.add(o)
    db.session.commit()
    return o


@pytest.fixture
def joao(tenant):
    c = Courier(tenant_id=tenant.id, name="João", phone="11988887777")
    db.session.add(c)
    db.session.commit()
    return c


def test_add_and_deactivate_courier(panel, tenant):
    panel.post("/snep/admin/entregas/motoboys", data={"name": "Pedro", "phone": "11977776666"})
    c = Courier.query.filter_by(name="Pedro").one()
    panel.post(f"/snep/admin/entregas/motoboys/{c.id}/alternar")
    db.session.expire_all()
    assert c.active is False


def test_page_lists_orders_ready_to_go(panel, tenant, joao):
    o = ready(tenant)
    not_delivery = ready(tenant)
    not_delivery.delivery = False
    db.session.commit()
    html = panel.get("/snep/admin/entregas").get_data(as_text=True)
    assert f"#{o.id}" in html and f"#{not_delivery.id}" not in html
    assert "João" in html


def test_create_dispatch_with_several_orders(panel, tenant, joao):
    a, b = ready(tenant), ready(tenant)
    r = panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id, b.id]})
    d = Dispatch.query.one()
    assert d.number == 1 and d.courier_id == joao.id
    assert f"imprimir_comanda={d.id}" in r.headers["Location"]
    db.session.expire_all()
    assert {a.status, b.status} == {"saiu"} and a.dispatch_id == d.id
    ready(tenant)
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [Order.query.order_by(Order.id.desc()).first().id]})
    assert Dispatch.query.order_by(Dispatch.id.desc()).first().number == 2


def test_dispatch_needs_courier_and_orders(panel, tenant, joao):
    o = ready(tenant)
    panel.post("/snep/admin/entregas/nova", data={"orders": [o.id]})
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id})
    assert Dispatch.query.count() == 0


def test_cash_to_collect_and_change_to_take(panel, tenant, joao):
    a = ready(tenant, total="60", payment="Dinheiro", change="100")
    b = ready(tenant, total="45", payment="Crédito")
    c = ready(tenant, total="30", payment="Pix")
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id, b.id, c.id]})
    from app.routes.dispatch import money_summary

    s = money_summary(Dispatch.query.one())
    assert s == {"cash": Decimal("60.00"), "change": Decimal("40.00"), "card": Decimal("45.00"), "pix": Decimal("30.00"),
                 "fees": Decimal("21.00")}
    html = panel.get("/snep/admin/entregas").get_data(as_text=True)
    assert "R$ 60,00" in html and "R$ 40,00" in html


def test_return_closes_dispatch_and_delivers_orders(panel, tenant, joao):
    a, b = ready(tenant), ready(tenant)
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id, b.id]})
    d = Dispatch.query.one()
    panel.post(f"/snep/admin/entregas/{d.id}/baixa")
    db.session.expire_all()
    assert d.returned_at is not None
    assert {a.status, b.status} == {"entregue"} and a.delivered_at is not None


def test_take_one_order_back_before_return(panel, tenant, joao):
    a, b = ready(tenant), ready(tenant)
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id, b.id]})
    d = Dispatch.query.one()
    panel.post(f"/snep/admin/entregas/{d.id}/tirar/{b.id}")
    db.session.expire_all()
    assert b.status == "confirmado" and b.dispatch_id is None
    panel.post(f"/snep/admin/entregas/{d.id}/baixa")
    db.session.expire_all()
    assert a.status == "entregue" and b.status == "confirmado"


def test_dispatch_slip_prints_addresses_and_money(panel, tenant, joao):
    a = ready(tenant, payment="Dinheiro", change="100", hood="Vila Nova")
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id]})
    html = panel.get(f"/snep/admin/entregas/{Dispatch.query.one().id}/etiqueta").get_data(as_text=True)
    for text in ("COMANDA 1", "João", "Vila Nova", "Rua A, 1", "Trazer em dinheiro", "R$ 60,00"):
        assert text in html, text


def test_report_by_courier(panel, tenant, joao):
    a, b = ready(tenant, fee="7"), ready(tenant, fee="9")
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id, b.id]})
    panel.post(f"/snep/admin/entregas/{Dispatch.query.one().id}/baixa")
    day = local_time(a.created_at).date()
    rows = sales_report(tenant, day, day)["by_courier"]
    assert rows == [{"name": "João", "deliveries": 2, "fees": Decimal("16.00")}]


def test_staff_can_dispatch(client, tenant, joao):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    o = ready(tenant)
    assert client.get("/snep/admin/entregas").status_code == 200
    client.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [o.id]})
    assert Dispatch.query.count() == 1


def test_other_store_orders_cannot_be_dispatched(panel, tenant, joao, cardapio, tmp_path):
    import json

    from app.models import Tenant
    from seed import seed_from_file

    other = dict(cardapio, tenant=dict(cardapio["tenant"], slug="outra", name="Outra"))
    f = tmp_path / "o.json"
    f.write_text(json.dumps(other), encoding="utf-8")
    seed_from_file(f)
    foreign = ready(Tenant.query.filter_by(slug="outra").one())
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [foreign.id]})
    db.session.expire_all()
    assert foreign.status == "confirmado" and Dispatch.query.count() == 0


def test_dispatch_left_empty_is_removed(panel, tenant, joao):
    a = ready(tenant)
    panel.post("/snep/admin/entregas/nova", data={"courier_id": joao.id, "orders": [a.id]})
    d = Dispatch.query.one()
    panel.post(f"/snep/admin/entregas/{d.id}/tirar/{a.id}")
    assert Dispatch.query.count() == 0
    db.session.expire_all()
    assert a.status == "confirmado"
