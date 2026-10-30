"""Contas (vendido − gastos) e Equipe (pagamento de motoboys e funcionários)."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import AdminUser, Courier, Dispatch, Employee, Expense, Order, WorkDay, utcnow
from app.services.finance import courier_day, employee_status, summary
from app.services.hours import STORE_TZ
from tests.test_admin import PASSWORD, admin, login, make_admin, panel  # noqa: F401
from tests.test_dispatch import joao, ready  # noqa: F401


def today():
    return datetime.now(STORE_TZ).date()


def sold(tenant, total, payment="Pix", status="confirmado"):
    o = Order(tenant_id=tenant.id, customer_name="X", customer_phone="", status=status, payment_method=payment,
              total=Decimal(total), subtotal=Decimal(total), created_at=utcnow())
    db.session.add(o)
    db.session.commit()
    return o


def dispatch(tenant, courier, *orders):
    d = Dispatch(tenant_id=tenant.id, number=Dispatch.query.count() + 1, courier_id=courier.id, created_at=utcnow())
    db.session.add(d)
    db.session.flush()
    for o in orders:
        o.dispatch_id, o.status = d.id, "saiu"
    db.session.commit()
    return d


# ---------- contas ----------

def test_summary_sold_minus_spent(tenant):
    sold(tenant, "100", "Pix")
    sold(tenant, "50", "Dinheiro")
    sold(tenant, "80", "Pix", status="pendente")
    sold(tenant, "70", "Pix", status="cancelado")
    db.session.add(Expense(tenant_id=tenant.id, day=today(), category="mercado", amount=Decimal("40")))
    db.session.commit()
    s = summary(tenant, today(), today())
    assert (s["sold"], s["spent"], s["left"], s["orders"]) == (Decimal("150"), Decimal("40"), Decimal("110"), 2)
    assert [(r["label"], r["total"]) for r in s["by_payment"]] == [("Pix", Decimal("100")), ("Dinheiro", Decimal("50"))]
    assert s["by_category"][0]["label"] == "Mercado"


def test_owner_adds_and_deletes_expense(panel, tenant):
    r = panel.post("/snep/admin/contas/gasto", data={"category": "gas", "amount": "120,50", "description": "botijão"})
    assert r.status_code == 302
    e = Expense.query.one()
    assert (e.category, e.amount, e.description, e.day) == ("gas", Decimal("120.50"), "botijão", today())
    html = panel.get("/snep/admin/contas").get_data(as_text=True)
    assert "R$ 120,50" in html and "botijão" in html
    assert "R$ 120,50" in panel.get("/snep/admin/contas?periodo=mes").get_data(as_text=True)
    panel.post(f"/snep/admin/contas/gasto/{e.id}/excluir")
    assert Expense.query.count() == 0


def test_expense_rejects_bad_input(panel, tenant):
    panel.post("/snep/admin/contas/gasto", data={"category": "motoboys", "amount": "10"})  # só pela aba Equipe
    panel.post("/snep/admin/contas/gasto", data={"category": "gas", "amount": "0"})
    panel.post("/snep/admin/contas/gasto", data={"category": "gas", "amount": "10", "day": "2999-01-01"})
    assert Expense.query.count() == 0


def test_staff_and_essential_plan_cannot_open(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.get("/snep/admin/contas").status_code in (302, 403)
    assert client.get("/snep/admin/equipe").status_code in (302, 403)


def test_essential_plan_hides_finance(panel, tenant):
    tenant.plan = "essencial"
    db.session.commit()
    r = panel.get("/snep/admin/contas")
    assert r.status_code != 200 or "Contas" not in r.get_data(as_text=True).split("<h1>")[1][:20]
    assert ">Contas<" not in panel.get("/snep/admin/pedidos").get_data(as_text=True)


# ---------- motoboys ----------

@pytest.mark.parametrize("mode,per,daily,expected", [
    ("taxa", None, None, Decimal("14")),
    ("por_entrega", "5", None, Decimal("15")),
    ("diaria", None, "60", Decimal("60")),
    ("diaria_entrega", "3", "50", Decimal("56")),
])
def test_courier_earnings_by_pay_mode(tenant, joao, mode, per, daily, expected):
    a, b, c = ready(tenant, fee="7"), ready(tenant, fee="7"), ready(tenant, fee="9")
    c.status = "cancelado"
    dispatch(tenant, joao, a, b)
    c.dispatch_id = a.dispatch_id
    joao.pay_mode, joao.pay_per_delivery, joao.pay_daily = mode, per and Decimal(per), daily and Decimal(daily)
    db.session.commit()
    if mode == "por_entrega":  # 3 entregas: cancelado não conta
        dispatch(tenant, joao, ready(tenant, fee="7"))
    r = courier_day(tenant, joao, today())
    assert r["earned"] == expected


def test_courier_without_deliveries_gets_no_daily(tenant, joao):
    joao.pay_mode, joao.pay_daily = "diaria", Decimal("60")
    db.session.commit()
    assert courier_day(tenant, joao, today())["earned"] == 0


def test_pay_courier_creates_expense(panel, tenant, joao):
    dispatch(tenant, joao, ready(tenant, fee="7"), ready(tenant, fee="8"))
    html = panel.get("/snep/admin/equipe").get_data(as_text=True)
    assert "João" in html and "R$ 15,00" in html
    panel.post(f"/snep/admin/equipe/motoboy/{joao.id}/pagar", data={"amount": "15,00", "deliveries": "2"})
    e = Expense.query.one()
    assert (e.category, e.courier_id, e.amount) == ("motoboys", joao.id, Decimal("15.00"))
    assert courier_day(tenant, joao, today())["to_pay"] == 0
    assert summary(tenant, today(), today())["spent"] == Decimal("15.00")


def test_change_courier_pay_mode(panel, tenant, joao):
    panel.post(f"/snep/admin/equipe/motoboy/{joao.id}/forma", data={"pay_mode": "diaria_entrega", "pay_daily": "50", "pay_per_delivery": "3"})
    db.session.expire_all()
    assert (joao.pay_mode, joao.pay_daily, joao.pay_per_delivery) == ("diaria_entrega", Decimal("50"), Decimal("3"))
    panel.post(f"/snep/admin/equipe/motoboy/{joao.id}/forma", data={"pay_mode": "diaria"})  # sem a diária: recusa
    db.session.expire_all()
    assert joao.pay_mode == "diaria_entrega"


# ---------- funcionários ----------

def test_day_worker_marks_days_pays_and_advances(panel, tenant):
    panel.post("/snep/admin/equipe/funcionario", data={"name": "Maria", "role": "atendente", "pay_type": "diaria", "pay_amount": "80"})
    maria = Employee.query.one()
    panel.post(f"/snep/admin/equipe/funcionario/{maria.id}/dia")
    st = employee_status(tenant, maria, today())
    assert st["worked_today"] and st["today"] == Decimal("80") and st["suggest"] == Decimal("80")
    panel.post(f"/snep/admin/equipe/funcionario/{maria.id}/pagar", data={"amount": "30", "kind": "vale"})
    panel.post(f"/snep/admin/equipe/funcionario/{maria.id}/pagar", data={"amount": "50", "kind": "pagamento"})
    st = employee_status(tenant, maria, today())
    assert (st["paid"], st["advances"], st["left"], st["suggest"]) == (Decimal("80"), Decimal("30"), 0, 0)
    assert summary(tenant, today(), today())["by_category"][0]["label"] == "Funcionários"
    panel.post(f"/snep/admin/equipe/funcionario/{maria.id}/dia")  # desmarca
    assert WorkDay.query.count() == 0


def test_monthly_worker(panel, tenant):
    panel.post("/snep/admin/equipe/funcionario", data={"name": "José", "pay_type": "mensal", "pay_amount": "2.000,00"})
    jose = Employee.query.one()
    assert panel.post(f"/snep/admin/equipe/funcionario/{jose.id}/dia").status_code == 400  # só diarista marca dia
    panel.post(f"/snep/admin/equipe/funcionario/{jose.id}/pagar", data={"amount": "500", "kind": "vale"})
    st = employee_status(tenant, jose, today())
    assert (st["month"], st["paid"], st["left"]) == (Decimal("2000"), Decimal("500"), Decimal("1500"))
    html = panel.get("/snep/admin/equipe").get_data(as_text=True)
    assert "José" in html and "R$ 1.500,00" in html
    panel.post(f"/snep/admin/equipe/funcionario/{jose.id}/alternar")
    db.session.expire_all()
    assert jose.active is False
