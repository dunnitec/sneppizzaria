"""Horário da loja: dia fechado guarda o horário digitado (o dono troca a hora sem desmarcar “fechado”)."""
import json
from datetime import datetime

from app.extensions import db
from app.services.hours import STORE_TZ, is_open, open_hours
from app.services.menu_data import data_from_db
from tests.test_admin import admin, panel, store_form  # noqa: F401


def monday(h, m):
    return datetime(2026, 10, 26, h, m, tzinfo=STORE_TZ)  # 26/10/2026 é segunda


def test_closed_day_keeps_the_typed_hours(panel, tenant):
    # segunda marcada como fechada; o dono troca a hora dela sem desmarcar “fechado”
    panel.post("/snep/admin/loja", data=store_form(tenant, **{"closed-1": "on", "open-1": "17:00", "close-1": "23:00"}))
    db.session.expire_all()
    assert json.loads(tenant.hours_json)["1"] == [1020, 1380, 0]
    page = panel.get("/snep/admin/loja").get_data(as_text=True)
    assert 'name="open-1" value="17:00"' in page and 'name="close-1" value="23:00"' in page
    assert open_hours(tenant)["1"] is None  # continua fechada
    tenant.is_open_override = None
    assert is_open(tenant, monday(20, 0)) is False


def test_reopening_the_day_uses_the_saved_hours(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, **{"closed-1": "on", "open-1": "17:00", "close-1": "23:00"}))
    db.session.expire_all()
    form = store_form(tenant)
    form.pop("closed-1", None)
    form.update({"open-1": "17:00", "close-1": "23:00"})
    panel.post("/snep/admin/loja", data=form)
    db.session.expire_all()
    assert open_hours(tenant)["1"] == [1020, 1380]
    tenant.is_open_override = None
    assert is_open(tenant, monday(17, 30)) is True and is_open(tenant, monday(23, 0)) is False


def test_site_shows_closed_day_as_closed(app, panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, **{"closed-1": "on", "open-1": "17:00", "close-1": "23:00"}))
    db.session.expire_all()
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    assert d["hours"]["1"] is None
    assert ("Segunda", "Fechado") in d["hours_rows"]


def test_old_closed_format_still_works(tenant):
    tenant.hours_json = json.dumps({"1": None, "2": [1080, 1310]})
    assert open_hours(tenant) == {"1": None, "2": [1080, 1310]}


def test_store_page_warns_when_closed_by_owner(panel, tenant):
    tenant.is_open_override = False
    db.session.commit()
    page = panel.get("/snep/admin/loja").get_data(as_text=True)
    assert "FECHADA por você" in page and "Seguir o horário" in page
