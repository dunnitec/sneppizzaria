from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.hours import is_open

SP = ZoneInfo("America/Sao_Paulo")
# 06/10/2026 é uma terça-feira (18:00 às 21:50); 05/10/2026 é segunda (fechado)


def test_open_inside_schedule(tenant):
    assert is_open(tenant, datetime(2026, 10, 6, 19, 0, tzinfo=SP)) is True


def test_closed_before_opening_time(tenant):
    assert is_open(tenant, datetime(2026, 10, 6, 17, 59, tzinfo=SP)) is False


def test_closed_at_closing_minute(tenant):
    assert is_open(tenant, datetime(2026, 10, 6, 21, 50, tzinfo=SP)) is False


def test_closed_on_day_off(tenant):
    assert is_open(tenant, datetime(2026, 10, 5, 19, 0, tzinfo=SP)) is False


def test_uses_sao_paulo_time_not_server_time(tenant):
    # 22:00 UTC = 19:00 em São Paulo
    assert is_open(tenant, datetime(2026, 10, 6, 22, 0, tzinfo=timezone.utc)) is True
    # 01:00 UTC de quarta = 22:00 de terça em São Paulo (já fechado)
    assert is_open(tenant, datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)) is False


def test_manual_override_forces_open(tenant):
    tenant.is_open_override = True
    assert is_open(tenant, datetime(2026, 10, 5, 19, 0, tzinfo=SP)) is True


def test_manual_override_forces_closed(tenant):
    tenant.is_open_override = False
    assert is_open(tenant, datetime(2026, 10, 6, 19, 0, tzinfo=SP)) is False
