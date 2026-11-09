"""Cupom de desconto: painel, vitrine do site, validação e desconto calculado no servidor."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Coupon, Order
from app.services.hours import work_day
from app.services.menu_data import data_from_db
from tests.test_admin import admin, panel  # noqa: F401
from tests.test_receipt_eta import cat


def make(tenant, code="SEXTOU10", kind="percent", value="10", **over):
    c = Coupon(tenant_id=tenant.id, code=code, discount_type=kind, value=Decimal(value), **over)
    db.session.add(c)
    db.session.commit()
    return c


def send(client, coupon="SEXTOU10", phone="11999990000"):
    p = cat("premium").products[0]
    return client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": phone, "payment_method": "Pix", "coupon": coupon,
        "items": [{"category_id": cat("premium").id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}]})


def plain_total(client, open_store):
    return Decimal(str(send(client, coupon="", phone="11988880000").json["total"]))


def test_percent_coupon_discounts_order(client, tenant, open_store):
    full = plain_total(client, open_store)
    make(tenant)
    r = send(client)
    assert r.status_code == 200
    expected = (full * Decimal("0.9")).quantize(Decimal("0.01"))
    assert Decimal(str(r.json["total"])) == expected and "Cupom SEXTOU10" in r.json["discount_note"]
    order = db.session.get(Order, r.json["order_id"])
    assert order.coupon_code == "SEXTOU10" and order.coupon_id is not None


def test_amount_coupon_never_passes_total(client, tenant, open_store):
    make(tenant, kind="amount", value="9999")
    assert send(client).json["total"] == 0


def test_code_is_case_and_space_insensitive(client, tenant, open_store):
    make(tenant)
    assert send(client, coupon=" sextou 10 ").status_code == 200


@pytest.mark.parametrize("over,msg", [
    ({"active": False}, "não encontrado"),
    ({"min_order": Decimal("9999")}, "a partir de"),
    ({"max_uses": 0}, "esgotou"),
])
def test_invalid_coupons_are_refused(client, tenant, open_store, over, msg):
    make(tenant, **over)
    r = send(client)
    assert r.status_code == 400 and msg in r.json["error"]


def test_dates(client, tenant, open_store):
    today = work_day(tenant)
    make(tenant, code="VELHO", ends_on=today - timedelta(days=1))
    make(tenant, code="FUTURO", starts_on=today + timedelta(days=1))
    assert "venceu" in send(client, coupon="VELHO").json["error"]
    assert "a partir" in send(client, coupon="FUTURO").json["error"]


def test_unknown_code(client, open_store):
    assert "não encontrado" in send(client, coupon="NADA").json["error"]


def test_one_use_per_customer_and_cancel_gives_it_back(client, tenant, open_store):
    make(tenant)
    r = send(client)
    assert r.status_code == 200
    second = send(client)
    assert second.status_code == 400 and "já usou" in second.json["error"]
    assert send(client, phone="11977770000").status_code == 200  # outro cliente pode
    db.session.get(Order, r.json["order_id"]).status = "cancelado"
    db.session.commit()
    assert send(client).status_code == 200


def test_many_uses_when_not_per_customer(client, tenant, open_store):
    make(tenant, per_customer=False)
    assert send(client).status_code == 200 and send(client).status_code == 200


def test_max_uses_counts_all_customers(client, tenant, open_store):
    make(tenant, max_uses=1)
    assert send(client).status_code == 200
    assert "esgotou" in send(client, phone="11977770000").json["error"]


def test_coupon_is_only_for_site(client, tenant, panel, open_store):
    make(tenant)
    p = cat("premium").products[0]
    panel.post("/snep/admin/pedidos/novo", json={
        "channel": "balcao", "payment_method": "Pix", "coupon": "SEXTOU10",
        "items": [{"category_id": cat("premium").id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}]})
    assert Order.query.filter(Order.coupon_id.isnot(None)).count() == 0


def test_showcase_lists_only_valid_visible(tenant):
    today = work_day(tenant)
    make(tenant, code="VISIVEL", min_order=Decimal("50"), ends_on=today)
    make(tenant, code="OCULTO", show_on_site=False)
    make(tenant, code="PAUSADO", active=False)
    make(tenant, code="VENCIDO", ends_on=today - timedelta(days=1))
    shown = data_from_db(tenant, "/x", {})["coupons"]
    assert [c["code"] for c in shown] == ["VISIVEL"]
    assert "10% de desconto" in shown[0]["text"] and "pedido mínimo R$ 50,00" in shown[0]["text"]


def test_check_endpoint(client, tenant, open_store):
    make(tenant, min_order=Decimal("50"))
    ok = client.post("/snep/api/cupom", json={"code": "sextou10", "subtotal": 60})
    assert ok.status_code == 200 and ok.json["coupon"]["code"] == "SEXTOU10" and ok.json["coupon"]["value"] == 10
    low = client.post("/snep/api/cupom", json={"code": "SEXTOU10", "subtotal": 10})
    assert low.status_code == 400 and "a partir de" in low.json["error"]
    assert client.post("/snep/api/cupom", json={"code": "SEXTOU10", "subtotal": "abc"}).status_code == 400


def test_other_store_coupon_does_not_work(client, tenant, open_store):
    from app.models import Tenant
    other = Tenant(slug="outra", name="Outra")
    db.session.add(other)
    db.session.commit()
    make(other, code="DAOUTRA")
    assert send(client, coupon="DAOUTRA").status_code == 400


# ---------- painel ----------

def test_owner_creates_coupon(panel, tenant):
    panel.post("/snep/admin/cupons", data={"code": "volta 15", "discount_type": "amount", "value": "15,00", "min_order": "80,00",
                                           "max_uses": "100", "per_customer": "on", "show_on_site": "on", "title": "Volta logo"})
    c = Coupon.query.one()
    assert (c.code, c.discount_type, c.value, c.min_order, c.max_uses, c.per_customer, c.show_on_site) == (
        "VOLTA15", "amount", Decimal("15"), Decimal("80"), 100, True, True)
    assert "VOLTA15" in panel.get("/snep/admin/cupons").get_data(as_text=True)


@pytest.mark.parametrize("form,msg", [
    ({"code": "AB", "value": "10"}, "pelo menos 3"),
    ({"code": "ABC", "value": "95"}, "no máximo"),
    ({"code": "ABC", "value": "0"}, ""),
    ({"code": "ABC", "value": "10", "starts_on": "2026-12-10", "ends_on": "2026-12-01"}, "depois do início"),
    ({"code": "ABC", "value": "10", "max_uses": "x"}, "Limite de usos"),
])
def test_bad_forms_are_rejected(panel, form, msg):
    r = panel.post("/snep/admin/cupons", data={"discount_type": "percent", **form}, follow_redirects=True)
    assert Coupon.query.count() == 0 and msg in r.get_data(as_text=True)


def test_duplicate_code(panel, tenant):
    make(tenant)
    r = panel.post("/snep/admin/cupons", data={"code": "sextou10", "value": "5", "discount_type": "percent"}, follow_redirects=True)
    assert Coupon.query.count() == 1 and "Já existe" in r.get_data(as_text=True)


def test_pause_and_delete(panel, tenant, client, open_store):
    c = make(tenant)
    panel.post(f"/snep/admin/cupons/{c.id}/pausar")
    db.session.expire_all()
    assert c.active is False
    r = send(client)
    assert r.status_code == 400
    panel.post(f"/snep/admin/cupons/{c.id}/pausar")
    db.session.expire_all()
    order_id = send(client).json["order_id"]
    panel.post(f"/snep/admin/cupons/{c.id}/excluir")
    assert Coupon.query.count() == 0
    assert db.session.get(Order, order_id).coupon_code == "SEXTOU10"


def test_staff_cannot_open_coupons(client, tenant):
    from tests.test_admin import login, make_admin
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.get("/snep/admin/cupons").status_code == 403


def test_plan_without_promos_blocks_coupons(client, panel, tenant, open_store):
    make(tenant)
    tenant.plan = "essencial"
    db.session.commit()
    from app.services.plans import has
    if has(tenant, "promocoes"):
        pytest.skip("plano essencial tem promoções")
    assert send(client).status_code == 400
    assert data_from_db(tenant, "/x", {})["coupons"] == []
    assert panel.get("/snep/admin/cupons").status_code == 302


# ---------- cupom x desconto do 1º pedido: não juntam, vale o maior ----------

def first_order_account(client, tenant, percent):
    from tests.test_accounts import register

    tenant.first_order_enabled, tenant.first_order_type, tenant.first_order_value = True, "percent", Decimal(percent)
    db.session.commit()
    register(client, phone="11966660000")


def test_bigger_coupon_replaces_first_order(client, tenant, open_store):
    full = plain_total(client, open_store)
    first_order_account(client, tenant, "5")
    make(tenant, value="20")
    r = send(client, phone="11966660000")
    order = db.session.get(Order, r.json["order_id"])
    assert Decimal(str(r.json["total"])) == (full * Decimal("0.8")).quantize(Decimal("0.01"))
    assert order.coupon_code == "SEXTOU10" and order.first_order is False and "1º pedido" not in order.discount_note


def test_bigger_first_order_keeps_coupon_unused(client, tenant, open_store):
    full = plain_total(client, open_store)
    first_order_account(client, tenant, "30")
    make(tenant, value="10")
    r = send(client, phone="11966660000")
    order = db.session.get(Order, r.json["order_id"])
    assert Decimal(str(r.json["total"])) == (full * Decimal("0.7")).quantize(Decimal("0.01"))
    assert order.coupon_id is None and order.first_order is True
