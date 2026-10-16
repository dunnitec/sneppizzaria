"""Relatório de vendas de um período (datas no horário de Brasília).

Só pedidos confirmados entram no faturamento; pendentes e cancelados aparecem
à parte. Os cálculos são feitos em Python sobre os pedidos do período, o que é
simples e suficiente para o volume de uma pizzaria.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from app.models import CHANNELS, SOLD_STATUSES, Dispatch, Order, OrderItem, OrderItemFlavor
from app.services.hours import STORE_TZ, local_time

TOP_FLAVORS = 15


def _utc_bounds(start, end):
    """[start 00:00, end+1 00:00) em São Paulo -> limites em UTC sem fuso (como o banco guarda)."""
    def to_utc(d):
        return datetime.combine(d, time(), STORE_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(start), to_utc(end + timedelta(days=1))


def _breakdown(orders, key):
    groups = defaultdict(lambda: {"orders": 0, "revenue": Decimal("0")})
    for o in orders:
        g = groups[key(o) or "—"]
        g["orders"] += 1
        g["revenue"] += o.total
    rows = [{"label": label, **g} for label, g in groups.items()]
    return sorted(rows, key=lambda r: (-r["revenue"], r["label"]))


def sales_report(tenant, start, end):
    lo, hi = _utc_bounds(start, end)
    in_period = Order.query.filter(Order.tenant_id == tenant.id, Order.created_at >= lo, Order.created_at < hi).all()
    confirmed = [o for o in in_period if o.status in SOLD_STATUSES]
    pending = [o for o in in_period if o.status == "pendente"]

    revenue = sum((o.total for o in confirmed), Decimal("0"))
    confirmed_ids = [o.id for o in confirmed]
    items = OrderItem.query.filter(OrderItem.order_id.in_(confirmed_ids)).all() if confirmed_ids else []

    by_day = {start + timedelta(days=i): {"revenue": Decimal("0"), "orders": 0} for i in range((end - start).days + 1)}
    by_hour = defaultdict(lambda: {"orders": 0, "revenue": Decimal("0")})
    for o in confirmed:
        when = local_time(o.created_at)
        day = by_day.get(when.date())
        if day is not None:
            day["revenue"] += o.total
            day["orders"] += 1
        by_hour[when.hour]["orders"] += 1
        by_hour[when.hour]["revenue"] += o.total

    pizzas = [i for i in items if i.kind != "bebida"]
    drinks = defaultdict(int)
    for i in items:
        if i.kind == "bebida":
            drinks[f"{i.product_names} {i.variant_label}".strip()] += i.quantity
    flavors = defaultdict(Decimal)
    if pizzas:
        qty_by_item = {i.id: i.quantity for i in pizzas}
        for f in OrderItemFlavor.query.filter(OrderItemFlavor.order_item_id.in_(list(qty_by_item))):
            flavors[f.product_name] += f.share * qty_by_item[f.order_item_id]
    top = sorted(flavors.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_FLAVORS]

    couriers = defaultdict(lambda: {"deliveries": 0, "fees": Decimal("0")})
    for d in Dispatch.query.filter(Dispatch.tenant_id == tenant.id, Dispatch.created_at >= lo, Dispatch.created_at < hi):
        for o in d.orders:
            if o.status == "entregue":
                couriers[d.courier.name]["deliveries"] += 1
                couriers[d.courier.name]["fees"] += o.delivery_fee or Decimal("0")

    return {
        "start": start,
        "end": end,
        "revenue": revenue,
        "orders": len(confirmed),
        "pizzas": sum(i.quantity for i in pizzas),
        "avg_ticket": (revenue / len(confirmed)).quantize(Decimal("0.01")) if confirmed else Decimal("0"),
        "delivery_fees": sum((o.delivery_fee or Decimal("0") for o in confirmed), Decimal("0")),
        "pending_orders": len(pending),
        "pending_value": sum((o.total for o in pending), Decimal("0")),
        "cancelled_orders": sum(1 for o in in_period if o.status == "cancelado"),
        "by_day": [{"date": d, **v} for d, v in by_day.items()],
        "by_hour": [{"hour": h, **v} for h, v in sorted(by_hour.items())],
        "by_payment": _breakdown(confirmed, lambda o: o.payment_method),
        "by_channel": _breakdown(confirmed, lambda o: CHANNELS.get(o.channel, o.channel)),
        "by_courier": sorted(({"name": n, "deliveries": v["deliveries"], "fees": v["fees"].quantize(Decimal("0.01"))}
                              for n, v in couriers.items()), key=lambda r: (-r["deliveries"], r["name"])),
        "online_share": (float(sum((o.total for o in confirmed if o.channel == "site"), Decimal("0")) / revenue * 100)
                         if revenue else 0.0),
        "by_neighborhood": _breakdown(confirmed, lambda o: o.neighborhood_name)[:10],
        "top_flavors": [{"name": n, "qty": q} for n, q in top],
        "top_drinks": [{"name": n, "qty": q} for n, q in sorted(drinks.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
    }


def month_calendar(tenant, year, month):
    """Semanas do mês (domingo a sábado), cada dia com faturamento e nº de pedidos confirmados."""
    first = datetime(year, month, 1).date()
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    days = {d["date"]: d for d in sales_report(tenant, first, last)["by_day"]}
    grid_start = first - timedelta(days=(first.weekday() + 1) % 7)
    weeks, day = [], grid_start
    while day <= last or len(weeks) == 0 or day.weekday() != 6:
        week = []
        for _ in range(7):
            week.append({"date": day, "in_month": day.month == month, **days.get(day, {"revenue": Decimal("0"), "orders": 0})})
            day += timedelta(days=1)
        weeks.append(week)
        if day > last:
            break
    return weeks
