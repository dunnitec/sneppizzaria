"""Relatórios separados (o dono escolhe na aba Relatórios): fechamento do dia, lucro real, produtos (curva ABC),
pagamentos, clientes, entregas, gastos e equipe, cancelados. O de vendas é o sales_report (services/reports.py).

Conta igual em todos: vendido = pedidos confirmados (SOLD_STATUSES) pelo dia do pedido no horário de Brasília.

Lucro real (como uma DRE simples):
    faturamento (produtos + entregas) − descontos = vendido
    vendido − taxa da maquininha − custo dos produtos = lucro bruto
    lucro bruto − gastos da loja = lucro real
O custo dos produtos vem dos custos cadastrados na aba Custos ("ficha"). Sem nenhum custo cadastrado, usa as
compras lançadas em Contas (mercado, bebidas, embalagens) ("compras"). No modo ficha as compras não entram de novo
nos gastos (seria contar duas vezes): aparecem só para comparar com o custo calculado.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from app.models import (CHANNELS, EXPENSE_CATEGORIES, SOLD_STATUSES, Customer, Dispatch, Expense, Order, OrderItem,
                        OrderItemFlavor, RESIDENCES)
from app.services.costs import Menu, card_fee, estimate, fee_rates
from app.services.hours import local_time
from app.services.reports import _utc_bounds

ZERO = Decimal("0")
CENT = Decimal("0.01")
PURCHASES = ("mercado", "bebidas", "embalagens")  # compras que viram produto vendido (CMV pelas compras)
INACTIVE_DAYS = 30


def _q(value):
    return Decimal(value).quantize(CENT)


def _pct(part, whole):
    return float(part / whole * 100) if whole else 0.0


def orders_in(tenant, start, end):
    lo, hi = _utc_bounds(start, end)
    return Order.query.filter(Order.tenant_id == tenant.id, Order.created_at >= lo, Order.created_at < hi).all()


def _items(orders):
    ids = [o.id for o in orders]
    return OrderItem.query.filter(OrderItem.order_id.in_(ids)).all() if ids else []


def _expenses(tenant, start, end):
    return (Expense.query.filter(Expense.tenant_id == tenant.id, Expense.day >= start, Expense.day <= end)
            .order_by(Expense.day.desc(), Expense.id.desc()).all())


# ---------- lucro real ----------

def profit(tenant, start, end, with_expenses=True, orders=None):
    """Números da DRE do período. with_expenses=False (plano sem Contas): para no lucro bruto."""
    orders = orders if orders is not None else orders_in(tenant, start, end)
    sold_orders = [o for o in orders if o.status in SOLD_STATUSES]
    menu = Menu(tenant)
    items = _items(sold_orders)
    product_sales = sum((o.subtotal for o in sold_orders), ZERO)
    delivery = sum((o.delivery_fee or ZERO for o in sold_orders), ZERO)
    discounts = sum((o.discount or ZERO for o in sold_orders), ZERO)
    sold = sum((o.total for o in sold_orders), ZERO)
    rates = fee_rates(tenant)
    fees = sum((card_fee(rates, o.payment_method, o.total) for o in sold_orders), ZERO)

    cost = covered_sales = uncovered_sales = ZERO
    for i in items:
        unit = estimate(menu, i)
        if unit is None:
            uncovered_sales += i.line_total
        else:
            cost += unit * i.quantity
            covered_sales += i.line_total
    item_sales = covered_sales + uncovered_sales

    expenses = _expenses(tenant, start, end) if with_expenses else []
    by_category = defaultdict(lambda: ZERO)
    for e in expenses:
        by_category[e.category] += e.amount
    purchases = sum((by_category[k] for k in PURCHASES), ZERO)
    mode = "ficha" if covered_sales or not with_expenses else "compras"
    cmv = cost if mode == "ficha" else purchases
    operating = {k: v for k, v in by_category.items() if k not in PURCHASES}  # compras: no custo ou só comparação
    operating_total = sum(operating.values(), ZERO)
    gross_profit = sold - fees - cmv
    net = gross_profit - operating_total
    contribution = (gross_profit / sold) if sold else ZERO
    return {
        "start": start, "end": end, "orders": len(sold_orders),
        "revenue": product_sales + delivery, "products": product_sales, "delivery": delivery, "discounts": discounts,
        "sold": sold, "card_fees": _q(fees), "rates": rates, "mode": mode, "cmv": _q(cmv),
        "cost_ficha": _q(cost), "purchases": purchases,
        "covered_share": _pct(covered_sales, item_sales), "uncovered_sales": uncovered_sales,
        "markup": float(covered_sales / cost) if cost else None,
        "cmv_share": _pct(cmv, product_sales),
        "gross_profit": _q(gross_profit), "gross_margin": _pct(gross_profit, sold),
        "with_expenses": with_expenses,
        "operating": sorted(({"key": k, "label": EXPENSE_CATEGORIES.get(k, k), "total": v}
                             for k, v in operating.items()), key=lambda r: -r["total"]),
        "operating_total": operating_total, "net": _q(net), "net_margin": _pct(net, sold),
        "break_even": _q(operating_total / contribution) if contribution > 0 else None,
        "avg_ticket": _q(sold / len(sold_orders)) if sold_orders else ZERO,
    }


# ---------- fechamento do dia ----------

def closing(tenant, day, with_expenses=True):
    """Fechamento de caixa de um dia: quanto vendeu, em quê, quanto entrou na gaveta, gastos e o que sobrou."""
    orders = orders_in(tenant, day, day)
    p = profit(tenant, day, day, with_expenses, orders)
    sold_orders = [o for o in orders if o.status in SOLD_STATUSES]
    by_payment = defaultdict(lambda: {"orders": 0, "total": ZERO})
    for o in sold_orders:
        g = by_payment[(o.payment_method or "").strip() or "Sem forma de pagamento"]
        g["orders"] += 1
        g["total"] += o.total
    cash_in = by_payment.get("Dinheiro", {}).get("total", ZERO)
    paid_out = sum((e.amount for e in _expenses(tenant, day, day)), ZERO) if with_expenses else ZERO
    by_channel = defaultdict(lambda: {"orders": 0, "total": ZERO})
    for o in sold_orders:
        g = by_channel[CHANNELS.get(o.channel, o.channel)]
        g["orders"] += 1
        g["total"] += o.total
    pending = [o for o in orders if o.status == "pendente"]
    cancelled = [o for o in orders if o.status == "cancelado"]
    return {
        **p, "day": day,
        "by_payment": sorted(({"label": k, **v} for k, v in by_payment.items()), key=lambda r: -r["total"]),
        "by_channel": sorted(({"label": k, **v} for k, v in by_channel.items()), key=lambda r: -r["total"]),
        "cash_in": cash_in, "paid_out": paid_out, "left": p["sold"] - paid_out,
        "pizzas": sum(i.quantity for i in _items(sold_orders) if i.kind not in ("bebida",)),
        "deliveries": sum(1 for o in sold_orders if o.delivery),
        "pending": len(pending), "pending_value": sum((o.total for o in pending), ZERO),
        "cancelled": len(cancelled), "cancelled_value": sum((o.total for o in cancelled), ZERO),
        "first": local_time(min(o.created_at for o in sold_orders)).strftime("%H:%M") if sold_orders else None,
        "last": local_time(max(o.created_at for o in sold_orders)).strftime("%H:%M") if sold_orders else None,
    }


# ---------- produtos (curva ABC) ----------

def products(tenant, start, end):
    """Cada sabor/bebida: quantidade, quanto vendeu, custo, lucro, markup e a classe da curva ABC (pelo vendido)."""
    sold_orders = [o for o in orders_in(tenant, start, end) if o.status in SOLD_STATUSES]
    items = _items(sold_orders)
    menu = Menu(tenant)
    rows = defaultdict(lambda: {"qty": ZERO, "sales": ZERO, "cost": ZERO, "costed": True, "kind": ""})
    cats = defaultdict(lambda: {"qty": 0, "sales": ZERO, "cost": ZERO, "costed": True})
    borders = defaultdict(lambda: {"qty": 0})
    flavors_by_item = defaultdict(list)
    if items:
        for f in OrderItemFlavor.query.filter(OrderItemFlavor.order_item_id.in_([i.id for i in items])):
            flavors_by_item[f.order_item_id].append(f)
    for i in items:
        unit = estimate(menu, i)
        c = cats[i.category_name or "—"]
        c["qty"] += i.quantity
        c["sales"] += i.line_total
        if unit is None:
            c["costed"] = False
        else:
            c["cost"] += unit * i.quantity
        if i.border_name:
            borders[i.border_name]["qty"] += i.quantity
        parts = flavors_by_item.get(i.id) or []
        if not parts:  # combo ou item sem sabor: entra pelo nome do item
            parts = [type("F", (), {"product_name": i.product_names, "share": Decimal(1)})()]
        for f in parts:
            share = Decimal(f.share)
            name = f.product_name if i.kind != "bebida" else f"{f.product_name} {i.variant_label or ''}".strip()
            r = rows[name]
            r["kind"] = i.kind or ""
            r["qty"] += share * i.quantity
            r["sales"] += share * i.line_total
            if unit is None:
                r["costed"] = False
            else:
                r["cost"] += share * unit * i.quantity
    total = sum((r["sales"] for r in rows.values()), ZERO)
    ranked, running = [], ZERO
    for name, r in sorted(rows.items(), key=lambda kv: (-kv[1]["sales"], kv[0])):
        running += r["sales"]
        share = _pct(running, total)
        cls = "A" if share <= 80 or not ranked else ("B" if share <= 95 else "C")
        ranked.append(_product_row(name, r, total, share, cls))
    cat_rows = [_product_row(name, c, total) for name, c in sorted(cats.items(), key=lambda kv: -kv[1]["sales"])]
    return {
        "rows": ranked, "categories": cat_rows, "total": total,
        "borders": sorted(({"name": k, **v} for k, v in borders.items()), key=lambda r: -r["qty"]),
        "classes": {k: sum(1 for r in ranked if r["cls"] == k) for k in "ABC"},
    }


def _product_row(name, r, total, cumulative=None, cls=None):
    sales, cost = _q(r["sales"]), _q(r["cost"])
    costed = r["costed"] and cost > 0
    return {"name": name, "qty": r["qty"], "sales": sales, "share": _pct(sales, total), "cumulative": cumulative,
            "cls": cls, "kind": r.get("kind", ""), "cost": cost if costed else None,
            "profit": sales - cost if costed else None, "margin": _pct(sales - cost, sales) if costed else None,
            "markup": float(sales / cost) if costed else None}


# ---------- pagamentos ----------

def payments(tenant, start, end):
    sold_orders = [o for o in orders_in(tenant, start, end) if o.status in SOLD_STATUSES]
    rates = fee_rates(tenant)
    groups = defaultdict(lambda: {"orders": 0, "total": ZERO, "fee": ZERO})
    for o in sold_orders:
        g = groups[(o.payment_method or "").strip() or "Sem forma de pagamento"]
        g["orders"] += 1
        g["total"] += o.total
        g["fee"] += card_fee(rates, o.payment_method, o.total)
    sold = sum((g["total"] for g in groups.values()), ZERO)
    rows = [{"label": k, **v, "net": v["total"] - v["fee"], "share": _pct(v["total"], sold),
             "rate": rates.get(k)} for k, v in groups.items()]
    promos = defaultdict(lambda: {"qty": 0, "total": ZERO})
    for i in _items(sold_orders):
        if i.promo_name:
            promos[i.promo_name]["qty"] += i.quantity
            promos[i.promo_name]["total"] += i.line_total
    split = sum(1 for o in sold_orders if o.split_people)
    return {
        "rows": sorted(rows, key=lambda r: -r["total"]), "sold": sold,
        "fees": sum((r["fee"] for r in rows), ZERO), "net": sold - sum((r["fee"] for r in rows), ZERO),
        "discount_total": sum((o.discount or ZERO for o in sold_orders), ZERO),
        "first_orders": sum(1 for o in sold_orders if o.first_order and o.discount),
        "loyalty_rewards": sum(1 for o in sold_orders if o.loyalty_reward),
        "discount_orders": sum(1 for o in sold_orders if o.discount),
        "promos": sorted(({"name": k, **v} for k, v in promos.items()), key=lambda r: -r["total"]),
        "pix_waiting": sum(1 for o in sold_orders if o.payment_method == "Pix" and o.channel == "site"
                           and not o.pix_paid_at),
        "split_orders": split,
    }


# ---------- clientes ----------

def customers(tenant, start, end):
    sold_orders = [o for o in orders_in(tenant, start, end) if o.status in SOLD_STATUSES]
    lo, _ = _utc_bounds(start, end)
    ids = {o.customer_id for o in sold_orders if o.customer_id}
    before = set()
    if ids:
        before = {cid for (cid,) in Order.query.with_entities(Order.customer_id).filter(
            Order.tenant_id == tenant.id, Order.customer_id.in_(ids), Order.status.in_(SOLD_STATUSES),
            Order.created_at < lo).distinct()}
    spent = defaultdict(lambda: {"orders": 0, "total": ZERO})
    for o in sold_orders:
        if o.customer_id:
            spent[o.customer_id]["orders"] += 1
            spent[o.customer_id]["total"] += o.total
    names = {c.id: c for c in Customer.query.filter(Customer.id.in_(list(spent) or [0]))}
    top = sorted(spent.items(), key=lambda kv: -kv[1]["total"])[:15]
    new = ids - before
    _, hi = _utc_bounds(end, end)
    cutoff = hi - timedelta(days=INACTIVE_DAYS)
    last = dict(Order.query.with_entities(Order.customer_id, Order.created_at).filter(
        Order.tenant_id == tenant.id, Order.customer_id.isnot(None), Order.status.in_(SOLD_STATUSES),
        Order.created_at < hi).order_by(Order.created_at))
    inactive = sum(1 for when in last.values() if when < cutoff)
    total_customers = len(last)
    anonymous = [o for o in sold_orders if not o.customer_id]
    return {
        "buyers": len(ids), "new": len(new), "returning": len(ids & before),
        "new_sales": sum((v["total"] for cid, v in spent.items() if cid in new), ZERO),
        "returning_sales": sum((v["total"] for cid, v in spent.items() if cid in before), ZERO),
        "repeat_share": _pct(Decimal(len(ids & before)), Decimal(len(ids))) if ids else 0.0,
        "per_customer": _q(sum((v["total"] for v in spent.values()), ZERO) / len(ids)) if ids else ZERO,
        "top": [{"customer": names.get(cid), **v} for cid, v in top],
        "inactive": inactive, "total_customers": total_customers, "inactive_days": INACTIVE_DAYS,
        "anonymous": len(anonymous), "anonymous_sales": sum((o.total for o in anonymous), ZERO),
    }


# ---------- entregas ----------

def deliveries(tenant, start, end):
    sold_orders = [o for o in orders_in(tenant, start, end) if o.status in SOLD_STATUSES]
    delivered = [o for o in sold_orders if o.delivery]
    minutes = [(o.delivered_at - o.created_at).total_seconds() / 60 for o in delivered
               if o.delivered_at and o.delivered_at > o.created_at]
    minutes = [m for m in minutes if m < 6 * 60]  # baixa esquecida no outro dia não conta
    km = [o.distance_km for o in delivered if o.distance_km is not None]
    lo, hi = _utc_bounds(start, end)
    couriers = defaultdict(lambda: {"deliveries": 0, "km": ZERO, "fees": ZERO, "trips": 0})
    for d in Dispatch.query.filter(Dispatch.tenant_id == tenant.id, Dispatch.created_at >= lo, Dispatch.created_at < hi):
        c = couriers[d.courier.name]
        c["trips"] += 1
        for o in d.orders:
            if o.status != "cancelado":
                c["deliveries"] += 1
                c["km"] += o.distance_km or ZERO
                c["fees"] += ZERO if o.fee_pending else (o.delivery_fee or ZERO)
    paid = sum((e.amount for e in Expense.query.filter(Expense.tenant_id == tenant.id, Expense.category == "motoboys",
                                                         Expense.day >= start, Expense.day <= end)), ZERO)
    hoods = defaultdict(lambda: {"orders": 0, "fees": ZERO, "total": ZERO})
    for o in delivered:
        h = hoods[o.neighborhood_name or "—"]
        h["orders"] += 1
        h["fees"] += o.delivery_fee or ZERO
        h["total"] += o.total
    residences = defaultdict(int)
    for o in delivered:
        residences[RESIDENCES.get(o.residence, "Não informado")] += 1
    fees = sum((o.delivery_fee or ZERO for o in delivered), ZERO)
    return {
        "delivered": len(delivered), "pickup": len(sold_orders) - len(delivered),
        "fees": fees, "courier_paid": paid, "fee_balance": fees - paid,
        "avg_minutes": round(sum(minutes) / len(minutes)) if minutes else None,
        "km_total": sum(km, ZERO), "km_avg": (sum(km, ZERO) / len(km)).quantize(Decimal("0.1")) if km else None,
        "pending_fee": sum(1 for o in delivered if o.fee_pending),
        "couriers": sorted(({"name": k, **v} for k, v in couriers.items()), key=lambda r: -r["deliveries"]),
        "hoods": sorted(({"label": k, **v} for k, v in hoods.items()), key=lambda r: -r["orders"])[:15],
        "residences": sorted(residences.items(), key=lambda kv: -kv[1]),
    }


# ---------- gastos e equipe ----------

def spending(tenant, start, end):
    expenses = _expenses(tenant, start, end)
    by_category = defaultdict(lambda: ZERO)
    people = defaultdict(lambda: {"paid": ZERO, "advances": ZERO, "kind": ""})
    by_day = defaultdict(lambda: ZERO)
    for e in expenses:
        by_category[e.category] += e.amount
        by_day[e.day] += e.amount
        if e.courier_id:
            p = people[("Motoboy", e.courier.name if e.courier else "—")]
            p["paid"] += e.amount
        elif e.employee_id:
            p = people[("Funcionário", e.employee.name if e.employee else "—")]
            p["paid"] += e.amount
            if e.is_advance:
                p["advances"] += e.amount
    total = sum(by_category.values(), ZERO)
    return {
        "total": total, "expenses": expenses,
        "by_category": sorted(({"label": EXPENSE_CATEGORIES.get(k, k), "total": v, "share": _pct(v, total)}
                               for k, v in by_category.items()), key=lambda r: -r["total"]),
        "people": sorted(({"kind": k[0], "name": k[1], **v} for k, v in people.items()),
                         key=lambda r: (r["kind"], -r["paid"])),
        "by_day": sorted(by_day.items()),
        "avg_day": _q(total / ((end - start).days + 1)),
    }


# ---------- cancelados e pendentes ----------

def cancelled(tenant, start, end):
    orders = orders_in(tenant, start, end)
    gone = sorted((o for o in orders if o.status == "cancelado"), key=lambda o: o.created_at, reverse=True)
    pending = [o for o in orders if o.status == "pendente"]
    sold = [o for o in orders if o.status in SOLD_STATUSES]
    return {
        "orders": gone, "value": sum((o.total for o in gone), ZERO),
        "rate": _pct(Decimal(len(gone)), Decimal(len(gone) + len(sold))) if gone or sold else 0.0,
        "pending": len(pending), "pending_value": sum((o.total for o in pending), ZERO),
        "by_channel": sorted(defaultdict_count(CHANNELS.get(o.channel, o.channel) for o in gone).items(),
                             key=lambda kv: -kv[1]),
    }


def defaultdict_count(values):
    counts = defaultdict(int)
    for v in values:
        counts[v] += 1
    return counts


def compare(current, previous):
    """Variação em % (None = sem base para comparar)."""
    if not previous:
        return None
    return float((Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100)
