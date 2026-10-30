"""Contas (vendido − gastos) e Equipe (pagamento de motoboys e funcionários). Só o dono; plano com “financeiro”.

Mesmo blueprint do painel (login, CSRF, regras de funcionário e de plano em app/routes/admin.py).
"""

from datetime import datetime, timedelta

from flask import abort, flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import COURIER_PAY, EXPENSE_CATEGORIES, MANUAL_CATEGORIES, Courier, Employee, Expense, WorkDay
from app.routes.admin import FormError, _date, _name, _price, _reject, _save, admin_bp
from app.services.finance import couriers_day, employees_status, month_bounds, summary
from app.services.hours import STORE_TZ
from app.services.money import brl

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]
WEEKDAY_NAMES = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _today():
    return datetime.now(STORE_TZ).date()


def _day_arg():
    """Dia escolhido na tela (?dia=AAAA-MM-DD); sem escolha ou no futuro = hoje."""
    day = _date(request.values.get("dia")) or _today()
    return min(day, _today())


def _day_label(day):
    if day == _today():
        return "Hoje"
    if day == _today() - timedelta(days=1):
        return "Ontem"
    return f"{WEEKDAY_NAMES[day.weekday()].capitalize()}, {day.strftime('%d/%m')}"


def _amount(text, what):
    value = _price(text, what, positive=True)
    if value > 100000:
        raise FormError(f"Valor alto demais em {what}. Confira os números.")
    return value


# ---------- contas ----------

@admin_bp.route("/contas")
def accounts():
    day = _day_arg()
    month = request.args.get("periodo") == "mes"
    start, end = month_bounds(day) if month else (day, day)
    end = min(end, _today())
    s = summary(g.tenant, start, end)
    prev = (start - timedelta(days=1)) if not month else (start - timedelta(days=1)).replace(day=1)
    nxt = (day + timedelta(days=1)) if not month else (end + timedelta(days=1))
    return render_template(
        "admin/accounts.html", s=s, day=day, month=month, today=_today(),
        title=f"{MONTHS[start.month - 1].capitalize()} de {start.year}" if month else _day_label(day),
        prev=prev, next=nxt if nxt <= _today() else None,
        categories={k: EXPENSE_CATEGORIES[k] for k in MANUAL_CATEGORIES},
    )


@admin_bp.route("/contas/gasto", methods=["POST"])
def expense_new():
    form = request.form
    try:
        category = form.get("category")
        if category not in MANUAL_CATEGORIES:
            raise FormError("Escolha o tipo do gasto.")
        amount = _amount(form.get("amount"), "o valor do gasto")
        day = _date(form.get("day")) or _today()
        if day > _today():
            raise FormError("A data do gasto não pode ser no futuro.")
        description = " ".join((form.get("description") or "").split())[:160] or None
        db.session.add(Expense(tenant_id=g.tenant.id, day=day, category=category, description=description, amount=amount))
        _save(f"Gasto de {brl(amount)} em {EXPENSE_CATEGORIES[category]} lançado.")
    except FormError as e:
        _reject(e)
    return redirect(request.form.get("next") or url_for("admin.accounts"))


@admin_bp.route("/contas/gasto/<int:expense_id>/excluir", methods=["POST"])
def expense_delete(expense_id):
    e = Expense.query.filter_by(tenant_id=g.tenant.id, id=expense_id).first_or_404()
    db.session.delete(e)
    _save(f"Gasto de {brl(e.amount)} ({e.category_name}) apagado.")
    return redirect(request.form.get("next") or url_for("admin.accounts"))


# ---------- equipe ----------

@admin_bp.route("/equipe")
def team():
    day = _day_arg()
    first, last = month_bounds(day)
    return render_template(
        "admin/team.html", day=day, today=_today(), title=_day_label(day),
        month_name=MONTHS[day.month - 1], prev=day - timedelta(days=1),
        next=day + timedelta(days=1) if day < _today() else None,
        couriers=couriers_day(g.tenant, day), staff=employees_status(g.tenant, day), pay_modes=COURIER_PAY,
    )


def _team_url(day):
    return url_for("admin.team", dia=day.isoformat() if day != _today() else None)


def _courier_or_404(courier_id):
    return Courier.query.filter_by(tenant_id=g.tenant.id, id=courier_id).first_or_404()


def _employee_or_404(employee_id):
    return Employee.query.filter_by(tenant_id=g.tenant.id, id=employee_id).first_or_404()


@admin_bp.route("/equipe/motoboy/<int:courier_id>/forma", methods=["POST"])
def courier_pay_mode(courier_id):
    courier, form = _courier_or_404(courier_id), request.form
    try:
        mode = form.get("pay_mode")
        if mode not in COURIER_PAY:
            raise FormError("Escolha como você paga o motoboy.")
        per = _amount(form.get("pay_per_delivery"), "o valor por entrega") if mode in ("por_entrega", "diaria_entrega") else None
        daily = _amount(form.get("pay_daily"), "a diária") if mode in ("diaria", "diaria_entrega") else None
        courier.pay_mode, courier.pay_per_delivery, courier.pay_daily = mode, per, daily
        _save(f"{courier.name}: {COURIER_PAY[mode].lower()}.")
    except FormError as e:
        _reject(e)
    return redirect(_team_url(_day_arg()) + f"#motoboy-{courier.id}")


@admin_bp.route("/equipe/motoboy/<int:courier_id>/pagar", methods=["POST"])
def courier_pay(courier_id):
    courier, day = _courier_or_404(courier_id), _day_arg()
    try:
        amount = _amount(request.form.get("amount"), "o valor pago")
        deliveries = request.form.get("deliveries", type=int) or 0
        db.session.add(Expense(tenant_id=g.tenant.id, day=day, category="motoboys", courier_id=courier.id, amount=amount,
                               description=f"{courier.name} · {deliveries} entrega{'s' if deliveries != 1 else ''}"))
        _save(f"Pagamento de {brl(amount)} para {courier.name} lançado nos gastos de {day.strftime('%d/%m')}.")
    except FormError as e:
        _reject(e)
    return redirect(_team_url(day) + f"#motoboy-{courier.id}")


def _employee_fields(form):
    name = _name(form.get("name"), "o nome do funcionário", max_length=80)
    pay_type = form.get("pay_type")
    if pay_type not in ("diaria", "mensal"):
        raise FormError("Escolha se é diarista ou mensalista.")
    amount = _amount(form.get("pay_amount"), "a diária" if pay_type == "diaria" else "o salário")
    return name, " ".join((form.get("role") or "").split())[:60] or None, pay_type, amount


@admin_bp.route("/equipe/funcionario", methods=["POST"])
def employee_new():
    try:
        name, role, pay_type, amount = _employee_fields(request.form)
        db.session.add(Employee(tenant_id=g.tenant.id, name=name, role=role, pay_type=pay_type, pay_amount=amount))
        _save(f"Funcionário “{name}” cadastrado.")
    except FormError as e:
        _reject(e)
    return redirect(_team_url(_day_arg()) + "#funcionarios")


@admin_bp.route("/equipe/funcionario/<int:employee_id>", methods=["POST"])
def employee_save(employee_id):
    emp = _employee_or_404(employee_id)
    try:
        emp.name, emp.role, emp.pay_type, emp.pay_amount = _employee_fields(request.form)
        _save(f"{emp.name}: dados salvos.")
    except FormError as e:
        _reject(e)
    return redirect(_team_url(_day_arg()) + f"#func-{emp.id}")


@admin_bp.route("/equipe/funcionario/<int:employee_id>/alternar", methods=["POST"])
def employee_toggle(employee_id):
    emp = _employee_or_404(employee_id)
    emp.active = not emp.active
    _save(f"{emp.name} {'voltou para a equipe' if emp.active else 'saiu da equipe (os pagamentos continuam nas contas)'}.")
    return redirect(_team_url(_day_arg()) + "#funcionarios")


@admin_bp.route("/equipe/funcionario/<int:employee_id>/dia", methods=["POST"])
def work_day(employee_id):
    """Marca ou desmarca o dia trabalhado do diarista (“Quem trabalhou hoje”)."""
    emp, day = _employee_or_404(employee_id), _day_arg()
    if emp.pay_type != "diaria":
        abort(400)
    found = WorkDay.query.filter_by(employee_id=emp.id, day=day).first()
    if found:
        db.session.delete(found)
        msg = f"{emp.name}: {day.strftime('%d/%m')} desmarcado."
    else:
        db.session.add(WorkDay(employee_id=emp.id, day=day))
        msg = f"{emp.name} trabalhou em {day.strftime('%d/%m')}: diária de {brl(emp.pay_amount)}."
    _save(msg)
    return redirect(_team_url(day) + f"#func-{emp.id}")


@admin_bp.route("/equipe/funcionario/<int:employee_id>/pagar", methods=["POST"])
def employee_pay(employee_id):
    """Pagamento ou vale (adiantamento): vira gasto em Funcionários e desconta do que falta pagar no mês."""
    emp, day = _employee_or_404(employee_id), _day_arg()
    advance = request.form.get("kind") == "vale"
    try:
        amount = _amount(request.form.get("amount"), "o valor do vale" if advance else "o valor pago")
        db.session.add(Expense(tenant_id=g.tenant.id, day=day, category="funcionarios", employee_id=emp.id,
                               amount=amount, is_advance=advance,
                               description=f"{'Vale' if advance else 'Pagamento'} · {emp.name}"))
        _save(f"{'Vale' if advance else 'Pagamento'} de {brl(amount)} para {emp.name} lançado nos gastos.")
    except FormError as e:
        _reject(e)
    return redirect(_team_url(day) + f"#func-{emp.id}")
