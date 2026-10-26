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


# ---------- fechar depois da meia-noite ----------

def test_closing_after_midnight_is_saved_as_next_day(panel, tenant):
    # sábado das 18:00 à 01:00 (domingo de madrugada)
    r = panel.post("/snep/admin/loja", data=store_form(tenant, **{"open-6": "18:00", "close-6": "01:00"}))
    assert r.status_code == 302
    db.session.expire_all()
    assert json.loads(tenant.hours_json)["6"] == [1080, 1500]
    page = panel.get("/snep/admin/loja").get_data(as_text=True)
    assert 'name="close-6" value="01:00"' in page and "fecha de madrugada" in page


def test_store_is_open_in_the_early_hours_of_the_next_day(tenant):
    tenant.is_open_override = None
    tenant.hours_json = json.dumps({"6": [1080, 1500], "0": None})
    saturday = lambda h, m: datetime(2026, 10, 31, h, m, tzinfo=STORE_TZ)  # noqa: E731
    sunday = lambda h, m: datetime(2026, 11, 1, h, m, tzinfo=STORE_TZ)  # noqa: E731
    assert is_open(tenant, saturday(17, 59)) is False
    assert is_open(tenant, saturday(23, 30)) is True
    assert is_open(tenant, sunday(0, 59)) is True  # domingo fechado, mas a madrugada é do sábado
    assert is_open(tenant, sunday(1, 0)) is False
    from app.services.hours import status_text
    assert "Fecha às 01:00" in status_text(tenant, sunday(0, 30))


def test_closing_at_midnight_works(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, **{"open-5": "18:00", "close-5": "00:00"}))
    db.session.expire_all()
    assert json.loads(tenant.hours_json)["5"] == [1080, 1440]
    tenant.is_open_override = None
    friday = lambda h, m: datetime(2026, 10, 30, h, m, tzinfo=STORE_TZ)  # noqa: E731
    assert is_open(tenant, friday(23, 59)) is True and is_open(tenant, datetime(2026, 10, 31, 0, 0, tzinfo=STORE_TZ)) is False


def test_same_open_and_close_is_rejected(panel, tenant):
    before = tenant.hours_json
    panel.post("/snep/admin/loja", data=store_form(tenant, **{"open-6": "18:00", "close-6": "18:00"}))
    db.session.expire_all()
    assert tenant.hours_json == before


def test_site_lists_after_midnight_hours(app, tenant):
    tenant.hours_json = json.dumps({"6": [1080, 1500]})
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    assert ("Sábado", "18:00 às 01:00") in d["hours_rows"]


# ---------- aberto/fechado sem recarregar ----------

def test_status_endpoint_follows_the_panel(client, tenant):
    tenant.is_open_override = True
    db.session.commit()
    r = client.get("/snep/api/status")
    assert r.json == {"open": True} and r.headers["Cache-Control"] == "no-store"
    tenant.is_open_override = False
    db.session.commit()
    assert client.get("/snep/api/status").json == {"open": False}
    assert client.get("/naoexiste/api/status").status_code == 404
