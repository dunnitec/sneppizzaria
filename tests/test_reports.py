"""Relatórios de vendas: só pedidos confirmados, por período no horário de Brasília."""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Category, Order, OrderItem, OrderItemFlavor, Product
from app.services.reports import sales_report
from tests.test_admin import admin, panel  # noqa: F401  (fixtures do painel)


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).replace(tzinfo=None)


def add_order(tenant, when_utc, status="confirmado", total="100.00", fee="7.00", payment="Pix", hood="Bairro Alto",
              items=()):
    order = Order(tenant_id=tenant.id, customer_name="X", customer_phone="11999990000", status=status,
                  subtotal=Decimal(total) - Decimal(fee), delivery_fee=Decimal(fee), total=Decimal(total),
                  payment_method=payment, neighborhood_name=hood, created_at=when_utc)
    db.session.add(order)
    db.session.flush()
    for qty, flavors in items:
        item = OrderItem(order_id=order.id, product_names="x", unit_price=Decimal("10"), quantity=qty,
                         line_total=Decimal("10") * qty)
        db.session.add(item)
        db.session.flush()
        for product, share in flavors:
            db.session.add(OrderItemFlavor(order_item_id=item.id, product_id=product.id, product_name=product.name,
                                           share=Decimal(share)))
    db.session.commit()
    return order


def products(*names):
    return [Product.query.filter_by(name=n).one() for n in names]


def test_only_confirmed_orders_count_and_pending_is_shown_apart(tenant):
    add_order(tenant, utc(2026, 10, 10, 22), total="100.00", items=[(2, [])])
    add_order(tenant, utc(2026, 10, 10, 23), total="50.00", items=[(1, [])])
    add_order(tenant, utc(2026, 10, 10, 23), status="pendente", total="80.00")
    add_order(tenant, utc(2026, 10, 10, 23), status="cancelado", total="999.00")
    r = sales_report(tenant, date(2026, 10, 10), date(2026, 10, 10))
    assert r["revenue"] == Decimal("150.00")
    assert r["orders"] == 2
    assert r["pizzas"] == 3
    assert r["avg_ticket"] == Decimal("75.00")
    assert r["delivery_fees"] == Decimal("14.00")
    assert (r["pending_orders"], r["pending_value"]) == (1, Decimal("80.00"))
    assert r["cancelled_orders"] == 1


def test_days_follow_sao_paulo_time(tenant):
    # 01:30 UTC de 11/10 = 22:30 de 10/10 em São Paulo
    add_order(tenant, utc(2026, 10, 11, 1, 30))
    assert sales_report(tenant, date(2026, 10, 10), date(2026, 10, 10))["orders"] == 1
    assert sales_report(tenant, date(2026, 10, 11), date(2026, 10, 11))["orders"] == 0


def test_daily_series_covers_every_day_of_the_period(tenant):
    add_order(tenant, utc(2026, 10, 10, 22), total="100.00")
    add_order(tenant, utc(2026, 10, 12, 22), total="40.00")
    days = sales_report(tenant, date(2026, 10, 10), date(2026, 10, 12))["by_day"]
    assert [(d["date"], d["revenue"], d["orders"]) for d in days] == [
        (date(2026, 10, 10), Decimal("100.00"), 1),
        (date(2026, 10, 11), Decimal("0"), 0),
        (date(2026, 10, 12), Decimal("40.00"), 1),
    ]


def test_top_flavors_count_half_pizzas_as_half(tenant):
    paulista, nene, bacon = products("Paulista", "A Moda do Nenê", "Bacon")
    add_order(tenant, utc(2026, 10, 10, 22), items=[(2, [(paulista, "1")]), (1, [(paulista, "0.5"), (nene, "0.5")])])
    add_order(tenant, utc(2026, 10, 10, 22), items=[(1, [(bacon, "1")])])
    add_order(tenant, utc(2026, 10, 10, 22), status="pendente", items=[(5, [(nene, "1")])])
    top = sales_report(tenant, date(2026, 10, 10), date(2026, 10, 10))["top_flavors"]
    assert [(t["name"], t["qty"]) for t in top] == [
        ("Paulista", Decimal("2.5")), ("Bacon", Decimal("1")), ("A Moda do Nenê", Decimal("0.5")),
    ]


def test_breakdowns_by_payment_neighborhood_and_hour(tenant):
    add_order(tenant, utc(2026, 10, 10, 22), total="100.00", payment="Pix", hood="Centro")  # 19h em SP
    add_order(tenant, utc(2026, 10, 10, 22, 40), total="60.00", payment="Dinheiro", hood="Centro")
    add_order(tenant, utc(2026, 10, 10, 23, 5), total="30.00", payment="Pix", hood="Vila Nova")  # 20h em SP
    r = sales_report(tenant, date(2026, 10, 10), date(2026, 10, 10))
    assert r["by_payment"][0] == {"label": "Pix", "orders": 2, "revenue": Decimal("130.00")}
    assert r["by_neighborhood"][0] == {"label": "Centro", "orders": 2, "revenue": Decimal("160.00")}
    assert {h["hour"]: h["orders"] for h in r["by_hour"]} == {19: 2, 20: 1}


def test_order_api_records_flavor_shares(client, open_store):
    paulista, nene = products("Paulista", "A Moda do Nenê")
    premium = Category.query.filter_by(slug="premium").one()
    r = client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": premium.id, "variant": "Inteira", "flavors": [paulista.id, nene.id], "quantity": 1}],
    })
    assert r.status_code == 200, r.json
    shares = {(f.product_name, f.share) for f in OrderItemFlavor.query}
    assert shares == {("Paulista", Decimal("0.5000")), ("A Moda do Nenê", Decimal("0.5000"))}


# ---------- painel ----------

def test_reports_page_requires_login(client, admin):
    assert client.get("/snep/admin/relatorios").status_code == 302


def test_reports_page_shows_period_numbers(panel, tenant):
    add_order(tenant, utc(2026, 10, 10, 22), total="123.45")
    html = panel.get("/snep/admin/relatorios?inicio=2026-10-01&fim=2026-10-31").get_data(as_text=True)
    assert "R$ 123,45" in html
    assert "outubro de 2026" in html.lower()


def test_reports_page_tolerates_bad_dates(panel):
    assert panel.get("/snep/admin/relatorios?inicio=xx&fim=2026-99-99").status_code == 200
    assert panel.get("/snep/admin/relatorios?inicio=2026-10-31&fim=2026-10-01").status_code == 200
