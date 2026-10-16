"""Tela Início do painel: situação da loja, abrir/fechar com um toque, resumo do dia e primeiros passos."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import AdminUser, Category, Order, Product, utcnow
from app.services.hours import STORE_TZ, status_text
from tests.test_admin import PASSWORD, admin, login, make_admin, panel  # noqa: F401


def test_login_goes_to_home(client, admin):
    r = login(client)
    assert r.headers["Location"].endswith("/snep/admin/")
    assert "Início" in client.get("/snep/admin/").get_data(as_text=True)


def test_staff_home_goes_to_orders(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.get("/snep/admin/").headers["Location"].endswith("/snep/admin/pedidos")


def test_home_shows_store_state_pending_and_today(panel, tenant):
    tenant.is_open_override = False
    db.session.add(Order(tenant_id=tenant.id, customer_name="A", customer_phone="11999990000", status="pendente", total=Decimal("50")))
    db.session.add(Order(tenant_id=tenant.id, customer_name="B", customer_phone="11999990000", status="confirmado", total=Decimal("80"), created_at=utcnow()))
    db.session.commit()
    html = panel.get("/snep/admin/").get_data(as_text=True)
    assert "FECHADA" in html
    assert ">1</span>" in html and "pedido esperando confirmação" in html
    assert "R$ 80,00" in html


@pytest.mark.parametrize("status, expected", [("closed", False), ("open", True), ("auto", None)])
def test_quick_open_close(panel, tenant, status, expected):
    r = panel.post("/snep/admin/loja/agora", data={"status": status})
    assert r.status_code == 302
    db.session.expire_all()
    assert tenant.is_open_override is expected


def test_quick_open_close_is_owner_only(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.post("/snep/admin/loja/agora", data={"status": "closed"}).status_code == 403


def test_status_text_follows_schedule(tenant):
    # terça 06/10/2026: abre 18:00, fecha 21:50; segunda fechado
    assert status_text(tenant, datetime(2026, 10, 6, 15, 0, tzinfo=STORE_TZ)) == "Fechada agora. Hoje abre às 18:00."
    assert status_text(tenant, datetime(2026, 10, 6, 19, 0, tzinfo=STORE_TZ)) == "Aberta, seguindo o horário. Fecha às 21:50."
    assert status_text(tenant, datetime(2026, 10, 6, 22, 30, tzinfo=STORE_TZ)) == "Fechada agora. Hoje já encerrou."
    assert status_text(tenant, datetime(2026, 10, 5, 19, 0, tzinfo=STORE_TZ)) == "Fechada agora. Hoje não abre."
    tenant.is_open_override = False
    assert status_text(tenant) == "Fechada por você, até você abrir de novo."
    tenant.is_open_override = True
    assert status_text(tenant) == "Aberta por você, até você fechar ou voltar ao horário."


def test_first_steps_checklist(panel, tenant, admin):
    html = panel.get("/snep/admin/").get_data(as_text=True)
    assert "Primeiros passos" in html
    assert "Trocar a senha" in html and "fotos" in html.lower() and "bebidas" in html.lower()
    panel.post("/snep/admin/senha", data={"current": PASSWORD, "new": "nova-senha-123", "confirm": "nova-senha-123"})
    db.session.expire_all()
    assert admin.password_changed is True
    html = panel.get("/snep/admin/").get_data(as_text=True)
    assert "Trocar a senha temporária" not in html or "feito" in html


def test_reset_by_owner_marks_password_as_temporary(panel, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.password_changed = True
    db.session.commit()
    panel.post(f"/snep/admin/usuarios/{staff.id}/senha", data={"password": "temporaria-1"})
    db.session.expire_all()
    assert staff.password_changed is False


@pytest.mark.parametrize("page", ["", "pedidos", "estoque", "cardapio", "extras", "entrega", "relatorios", "clientes", "loja", "visual", "usuarios"])
def test_every_page_has_help(panel, page):
    assert "Como usar esta tela" in panel.get(f"/snep/admin/{page}").get_data(as_text=True)


def test_header_status_links_to_home(panel):
    html = panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert 'class="pill' in html and 'href="/snep/admin/"' in html
