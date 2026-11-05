"""Expediente que passa da meia-noite: o pedido da madrugada conta no dia em que a loja abriu."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Order
from app.services import report_book as book
from app.services.finance import summary
from app.services.hours import STORE_TZ, work_day
from app.services.reports import sales_report
from tests.test_admin import admin, panel  # noqa: F401

FRIDAY, SATURDAY = date(2026, 10, 9), date(2026, 10, 10)


def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=STORE_TZ)


def utc(when):
    return when.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def late_friday(tenant):
    """Sexta das 18:00 à 01:00 de sábado; sábado das 18:00 às 23:00."""
    tenant.hours_json = json.dumps({"5": [1080, 1500], "6": [1080, 1380]})
    db.session.commit()
    return tenant


def order(tenant, when, total="65.00", status="confirmado"):
    o = Order(tenant_id=tenant.id, customer_name="Ana", customer_phone="11999990000", channel="balcao", status=status,
              subtotal=Decimal(total), total=Decimal(total), payment_method="Dinheiro", created_at=utc(when))
    db.session.add(o)
    db.session.commit()
    return o


def test_work_day_stays_on_the_day_the_store_opened(late_friday):
    assert work_day(late_friday, at(SATURDAY, 0, 30)) == FRIDAY
    assert work_day(late_friday, at(SATURDAY, 1, 0)) == SATURDAY  # fechou: já é o dia seguinte
    assert work_day(late_friday, at(FRIDAY, 23, 30)) == FRIDAY
    assert work_day(late_friday, at(SATURDAY, 23, 59)) == SATURDAY


def test_closing_counts_the_whole_shift(late_friday):
    order(late_friday, at(FRIDAY, 23, 30))
    order(late_friday, at(SATURDAY, 0, 30))
    friday = book.closing(late_friday, FRIDAY)
    assert (friday["orders"], friday["sold"]) == (2, Decimal("130.00"))
    assert book.closing(late_friday, SATURDAY)["orders"] == 0


def test_every_report_agrees_with_the_closing(late_friday):
    order(late_friday, at(FRIDAY, 23, 30))
    order(late_friday, at(SATURDAY, 0, 30))
    order(late_friday, at(SATURDAY, 19, 0))
    sales = sales_report(late_friday, FRIDAY, FRIDAY)
    assert (sales["orders"], sales["revenue"]) == (2, Decimal("130.00"))
    assert sales["by_day"] == [{"date": FRIDAY, "revenue": Decimal("130.00"), "orders": 2}]
    assert summary(late_friday, FRIDAY, FRIDAY)["sold"] == Decimal("130.00")
    assert book.payments(late_friday, FRIDAY, FRIDAY)["sold"] == Decimal("130.00")
    assert sales_report(late_friday, SATURDAY, SATURDAY)["orders"] == 1
    assert sales_report(late_friday, FRIDAY, SATURDAY)["orders"] == 3  # nada some nem conta duas vezes


def test_store_closing_before_midnight_keeps_the_calendar_day(tenant):
    tenant.hours_json = json.dumps({"5": [1080, 1380], "6": [1080, 1380]})
    db.session.commit()
    order(tenant, at(SATURDAY, 0, 30))
    assert book.closing(tenant, FRIDAY)["orders"] == 0
    assert book.closing(tenant, SATURDAY)["orders"] == 1
    assert work_day(tenant, at(SATURDAY, 0, 30)) == SATURDAY


def test_panel_closing_shows_the_whole_shift(panel, late_friday):
    order(late_friday, at(FRIDAY, 23, 30))
    order(late_friday, at(SATURDAY, 0, 30))
    page = panel.get("/snep/admin/relatorios?tipo=fechamento&dia=2026-10-09").get_data(as_text=True)
    assert "130,00" in page
