"""Contas e Equipe: quanto vendeu, quanto gastou, quanto sobrou e quanto pagar a cada um.

- Vendido = pedidos confirmados (SOLD_STATUSES) do período, pelo dia do pedido no horário de Brasília,
  igual ao Relatório. Gasto = Expense do período (lançado na mão ou pelo “Pagar” da aba Equipe).
- Motoboy: o dia de trabalho é o dia da saída da comanda. Pedido cancelado não conta.
- Funcionário diarista ganha a diária em cada dia marcado em “Quem trabalhou hoje”; mensalista ganha o
  salário do mês. Pagamentos e vales (Expense com employee_id) descontam do que falta.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from app.models import EXPENSE_CATEGORIES, SOLD_STATUSES, Courier, Dispatch, Employee, Expense, Order, WorkDay
from app.services.reports import _utc_bounds

ZERO = Decimal("0")
CARD = ("Débito", "Crédito", "Cartão")


def month_bounds(day):
    first = day.replace(day=1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return first, last


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# ---------- contas ----------

def summary(tenant, start, end):
    """Vendido (por forma de pagamento), gastos (por categoria) e o que sobrou, de start a end (datas)."""
    lo, hi = _utc_bounds(start, end)
    orders = Order.query.filter(Order.tenant_id == tenant.id, Order.created_at >= lo, Order.created_at < hi,
                                Order.status.in_(SOLD_STATUSES)).all()
    by_payment = defaultdict(lambda: {"orders": 0, "total": ZERO})
    for o in orders:
        method = (o.payment_method or "").strip() or "Sem forma de pagamento"
        by_payment[method]["orders"] += 1
        by_payment[method]["total"] += o.total
    sold = sum((o.total for o in orders), ZERO)

    expenses = (Expense.query.filter(Expense.tenant_id == tenant.id, Expense.day >= start, Expense.day <= end)
                .order_by(Expense.day.desc(), Expense.id.desc()).all())
    by_category = defaultdict(lambda: ZERO)
    for e in expenses:
        by_category[e.category] += e.amount
    spent = sum((e.amount for e in expenses), ZERO)
    return {
        "start": start, "end": end, "sold": sold, "orders": len(orders), "spent": spent, "left": sold - spent,
        "by_payment": sorted(({"label": k, **v} for k, v in by_payment.items()), key=lambda r: -r["total"]),
        "by_category": sorted(({"key": k, "label": EXPENSE_CATEGORIES.get(k, k), "total": v}
                               for k, v in by_category.items()), key=lambda r: -r["total"]),
        "expenses": expenses,
    }


# ---------- motoboys ----------

def courier_day(tenant, courier, day):
    """O que o motoboy fez no dia e quanto ganhou pela forma de pagamento dele."""
    lo, hi = _utc_bounds(day, day)
    dispatches = Dispatch.query.filter(Dispatch.tenant_id == tenant.id, Dispatch.courier_id == courier.id,
                                       Dispatch.created_at >= lo, Dispatch.created_at < hi).all()
    orders = [o for d in dispatches for o in d.orders if o.status != "cancelado"]
    fees = sum((ZERO if o.fee_pending else o.delivery_fee for o in orders), ZERO)
    km = sum((o.distance_km for o in orders if o.distance_km is not None), ZERO)
    per, daily = money(courier.pay_per_delivery), money(courier.pay_daily)
    worked = bool(orders)
    earned = {
        "taxa": fees,
        "por_entrega": per * len(orders),
        "diaria": daily if worked else ZERO,
        "diaria_entrega": (daily if worked else ZERO) + per * len(orders),
    }.get(courier.pay_mode, fees)
    paid = sum((e.amount for e in Expense.query.filter_by(tenant_id=tenant.id, courier_id=courier.id, day=day)), ZERO)
    return {"courier": courier, "deliveries": len(orders), "fees": fees, "km": km, "earned": earned, "paid": paid,
            "to_pay": max(earned - paid, ZERO), "trips": len(dispatches)}


def couriers_day(tenant, day):
    couriers = Courier.query.filter_by(tenant_id=tenant.id).order_by(Courier.active.desc(), Courier.name).all()
    rows = [courier_day(tenant, c, day) for c in couriers]
    return [r for r in rows if r["courier"].active or r["deliveries"] or r["paid"]]


# ---------- funcionários ----------

def employee_status(tenant, employee, day):
    """Quanto o funcionário ganhou no dia e no mês, quanto já recebeu (pagamentos + vales) e quanto falta."""
    first, last = month_bounds(day)
    days = {w.day for w in WorkDay.query.filter(WorkDay.employee_id == employee.id,
                                                WorkDay.day >= first, WorkDay.day <= last)}
    pay = money(employee.pay_amount)
    if employee.pay_type == "mensal":
        today, month = ZERO, pay
    else:
        today, month = (pay if day in days else ZERO), pay * len(days)
    month_paid = Expense.query.filter(Expense.tenant_id == tenant.id, Expense.employee_id == employee.id,
                                      Expense.day >= first, Expense.day <= last).all()
    paid = sum((e.amount for e in month_paid), ZERO)
    advances = sum((e.amount for e in month_paid if e.is_advance), ZERO)
    paid_today = sum((e.amount for e in month_paid if e.day == day), ZERO)
    return {"employee": employee, "worked_today": day in days, "days_worked": len(days), "today": today,
            "paid_today": paid_today, "month": month, "paid": paid, "advances": advances,
            "left": max(month - paid, ZERO), "suggest": max((today - paid_today) if employee.pay_type == "diaria"
                                                             else month - paid, ZERO)}


def employees_status(tenant, day):
    staff = Employee.query.filter_by(tenant_id=tenant.id).order_by(Employee.active.desc(), Employee.name).all()
    return [employee_status(tenant, e, day) for e in staff]

