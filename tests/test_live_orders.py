"""Pedidos ao vivo no painel, contador de pendentes, busca no cardápio e aviso de alterações não salvas."""
from decimal import Decimal

from app.extensions import db
from app.models import Order
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


def add_order(tenant, status="pendente", name="Ana", total="65.00"):
    order = Order(tenant_id=tenant.id, customer_name=name, customer_phone="11999990000", status=status,
                  total=Decimal(total))
    db.session.add(order)
    db.session.commit()
    return order


def test_poll_requires_login(client, admin):
    assert client.get("/snep/admin/pedidos/novos?desde=0").status_code == 302


def test_poll_returns_orders_after_given_id(panel, tenant):
    first = add_order(tenant, name="Primeiro")
    second = add_order(tenant, name="Segundo", total="80.50")
    r = panel.get(f"/snep/admin/pedidos/novos?desde={first.id}")
    assert r.status_code == 200
    assert r.json["latest"] == second.id
    assert r.json["pending"] == 2
    assert r.json["new"] == [{"id": second.id, "name": "Segundo", "total": "R$ 80,50"}]


def test_poll_with_bad_param_returns_nothing_new(panel, tenant):
    add_order(tenant)
    r = panel.get("/snep/admin/pedidos/novos?desde=abc")
    assert r.status_code == 200 and r.json["new"] == []


def test_poll_only_sees_own_store(panel, tenant, cardapio, tmp_path):
    import json

    from app.models import Tenant
    from seed import seed_from_file

    other = dict(cardapio, tenant=dict(cardapio["tenant"], slug="outra", name="Outra"))
    f = tmp_path / "o.json"
    f.write_text(json.dumps(other), encoding="utf-8")
    seed_from_file(f)
    add_order(Tenant.query.filter_by(slug="outra").one(), name="De outra loja")
    assert panel.get("/snep/admin/pedidos/novos?desde=0").json["new"] == []


def test_staff_can_poll(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.get("/snep/admin/pedidos/novos?desde=0").status_code == 200


def test_pending_badge_in_tabs(panel, tenant):
    add_order(tenant)
    add_order(tenant)
    add_order(tenant, status="confirmado")
    html = panel.get("/snep/admin/cardapio").get_data(as_text=True)
    assert 'class="badge"' in html and ">2<" in html


def test_orders_page_has_live_settings(panel):
    html = panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert 'id="live"' in html and "data-poll=" in html and "admin.js" in html


def test_menu_page_has_search_and_tracked_forms(panel):
    from app.models import Category

    premium = Category.query.filter_by(slug="premium").one()
    assert 'id="search"' in panel.get("/snep/admin/cardapio").get_data(as_text=True)
    html = panel.get(f"/snep/admin/cardapio/{premium.id}").get_data(as_text=True)
    assert 'id="search"' in html
    assert "data-track" in html
