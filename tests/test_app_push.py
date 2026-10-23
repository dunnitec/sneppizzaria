"""App no celular (PWA) e avisos (Web Push): manifesto, ícones, inscrição, avisos automáticos e do dono."""
import io
import json
from datetime import timedelta

import pytest
from PIL import Image

import app.services.push as push
from app.extensions import db
from app.models import Category, Customer, LoyaltyProgram, Order, PushCampaign, PushSubscription, utcnow
from app.routes.push_admin import MAX_PER_WEEK, run_due
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401
from tests.test_accounts import order, promo_item, register

SUB = {"endpoint": "https://push.example.com/abc123", "keys": {"p256dh": "chave-publica", "auth": "segredo"}}


@pytest.fixture
def sent(app, monkeypatch):
    """Liga os avisos com chaves de teste e guarda o que seria enviado, sem sair para a internet."""
    app.config.update(VAPID_PUBLIC_KEY="BPublica", VAPID_PRIVATE_KEY="privada", PUSH_SYNC=True)
    out = []

    def fake_post(info, data, key, claims):
        out.append({"endpoint": info["endpoint"], **json.loads(data)})
        return "gone" if "morto" in info["endpoint"] else "ok"

    monkeypatch.setattr(push, "_post", fake_post)
    return out


def subscribe(client, sub=SUB, **extra):
    return client.post("/snep/api/push", json={"subscription": sub, **extra})


# ---------- PWA ----------

def test_manifest(client, tenant):
    m = client.get("/snep/manifest.webmanifest")
    assert m.headers["Content-Type"].startswith("application/manifest+json")
    data = m.get_json(force=True)
    assert data["name"] == tenant.name and data["start_url"].startswith("/snep/") and data["display"] == "standalone"
    assert {i["sizes"] for i in data["icons"]} == {"192x192", "512x512"}
    assert any(i["purpose"] == "maskable" for i in data["icons"])


@pytest.mark.parametrize("url, size", [("/snep/icone-192.png", 192), ("/snep/icone-512-maskable.png", 512), ("/snep/icone-180.png", 180)])
def test_icons(client, tenant, url, size):
    r = client.get(url)
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(r.data)).size == (size, size)


def test_unknown_icon_size_404(client, tenant):
    assert client.get("/snep/icone-77.png").status_code == 404


def test_service_worker(client, tenant):
    r = client.get("/snep/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["Content-Type"]
    assert r.headers["Service-Worker-Allowed"] == "/snep/" and "showNotification" in r.get_data(as_text=True)


def test_site_links_manifest_and_push_key(client, tenant, app):
    html = client.get("/snep/").get_data(as_text=True)
    assert 'rel="manifest"' in html and "apple-touch-icon" in html and '"push_key": ""' in html
    app.config.update(VAPID_PUBLIC_KEY="BPublica", VAPID_PRIVATE_KEY="privada")
    assert '"push_key": "BPublica"' in client.get("/snep/").get_data(as_text=True)


def test_owner_uploads_app_icon(panel, tenant, app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (150, 150), (200, 30, 30)).save(buf, "PNG")
    buf.seek(0)
    panel.post("/snep/admin/visual/icone", data={"photo": (buf, "logo.png")}, content_type="multipart/form-data")
    db.session.expire_all()
    assert tenant.app_icon
    img = Image.open(io.BytesIO(panel.get("/snep/icone-512.png").data)).convert("RGB")
    assert img.getpixel((256, 256))[0] > 150  # logo vermelho no meio


# ---------- inscrição ----------

def test_subscribe_and_preferences(client, tenant):
    assert subscribe(client, {"endpoint": "http://x", "keys": {}}).status_code == 400
    assert subscribe(client).get_json()["ok"]
    s = PushSubscription.query.one()
    assert s.endpoint == SUB["endpoint"] and s.customer_id is None and s.wants_promos
    client.post("/snep/api/push/preferencias", json={"endpoint": SUB["endpoint"], "promos": False})
    assert db.session.get(PushSubscription, s.id).wants_promos is False
    client.post("/snep/api/push/preferencias", json={"endpoint": SUB["endpoint"], "off": True})
    assert PushSubscription.query.count() == 0


def test_subscription_links_to_customer(client, open_store):
    register(client)
    subscribe(client)
    assert PushSubscription.query.one().customer_id == Customer.query.one().id


def test_order_links_device_to_customer(client, open_store):
    subscribe(client)
    order(client, push_endpoint=SUB["endpoint"])
    assert PushSubscription.query.one().customer_id == Customer.query.one().id


def test_subscribe_with_track_token(client, open_store):
    r = order(client)
    subscribe(client, track=r["track_url"].split("/")[-1])
    assert PushSubscription.query.one().customer_id == db.session.get(Order, r["order_id"]).customer_id


# ---------- avisos automáticos ----------

def test_order_status_notifications(client, open_store, sent):
    subscribe(client)
    r = order(client, push_endpoint=SUB["endpoint"], withdraw=False, street="Rua A", number="1",
              neighborhood=open_store.neighborhoods[0].name)
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    staff.post(f"/snep/admin/pedidos/{r['order_id']}/status", data={"status": "confirmado"})
    assert sent[-1]["title"] == f"Pedido #{r['order_id']} confirmado ✓" and "Previsão de entrega" in sent[-1]["body"]
    assert sent[-1]["url"] == r["track_url"]
    from app.models import Courier

    courier = Courier(tenant_id=open_store.id, name="Zé")
    db.session.add(courier)
    db.session.commit()
    staff.post("/snep/admin/entregas/nova", data={"orders": [r["order_id"]], "courier_id": courier.id})
    assert sent[-1]["title"] == "Seu pedido saiu para entrega 🛵"


def test_pix_received_notification(client, open_store, sent):
    open_store.pix_key, open_store.pix_city = "a@b.com", "Itu"
    db.session.commit()
    subscribe(client)
    r = order(client, push_endpoint=SUB["endpoint"], payment_method="Pix")
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    staff.post(f"/snep/admin/pedidos/{r['order_id']}/pix")
    assert sent[-1]["title"] == "Pix recebido ✓"


def test_dead_device_is_removed(client, open_store, sent):
    subscribe(client, {"endpoint": "https://push.example.com/morto", "keys": SUB["keys"]})
    r = order(client, push_endpoint="https://push.example.com/morto")
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    staff.post(f"/snep/admin/pedidos/{r['order_id']}/status", data={"status": "confirmado"})
    assert PushSubscription.query.count() == 0


def test_loyalty_notification_when_card_completes(client, open_store, sent):
    cat = Category.query.filter_by(slug="promocionais").one()
    db.session.add(LoyaltyProgram(tenant_id=open_store.id, name="Promocional", active=True, goal=2,
                                  count_category_ids=json.dumps([cat.id]), reward_category_id=cat.id,
                                  reward_product_ids=json.dumps([p.id for p in cat.products])))
    db.session.commit()
    register(client)
    subscribe(client)
    r = order(client, items=[promo_item(2)])
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    staff.post(f"/snep/admin/pedidos/{r['order_id']}/status", data={"status": "confirmado"})
    assert any(s["title"] == "🎁 Você ganhou uma pizza Promocional grátis!" for s in sent)


def test_no_notification_without_keys(client, open_store, app, monkeypatch):
    calls = []
    monkeypatch.setattr(push, "_post", lambda *a: calls.append(a) or "ok")
    subscribe(client)
    r = order(client, push_endpoint=SUB["endpoint"])
    make_admin(open_store)
    staff = client.application.test_client()
    login(staff)
    staff.post(f"/snep/admin/pedidos/{r['order_id']}/status", data={"status": "confirmado"})
    assert calls == []


# ---------- avisos do dono ----------

def campaign_form(**over):
    data = {"title": "Terça da Calabresa", "body": "Calabresa por R$ 32,90 hoje!", "url": "", "audience": "todos", "when": "agora"}
    data.update(over)
    return data


def test_owner_sends_campaign_now(panel, tenant, sent, client):
    subscribe(client.application.test_client())
    r = panel.post("/snep/admin/avisos", data=campaign_form(), follow_redirects=True)
    assert "Aviso enviado para 1 celular(es)" in r.get_data(as_text=True)
    assert sent[-1]["title"] == "Terça da Calabresa" and sent[-1]["url"] == "/snep/"
    assert PushCampaign.query.one().sent_count == 1


def test_campaign_respects_promo_opt_out_and_audience(panel, tenant, sent, client):
    other = client.application.test_client()
    subscribe(other)
    other.post("/snep/api/push/preferencias", json={"endpoint": SUB["endpoint"], "promos": False})
    panel.post("/snep/admin/avisos", data=campaign_form())
    assert sent == []
    subscribe(other, {"endpoint": "https://push.example.com/outro", "keys": SUB["keys"]})
    panel.post("/snep/admin/avisos", data=campaign_form(audience="cadastro"))
    assert sent == []  # sem cadastro


def test_schedule_and_repeat_weekly(panel, tenant, sent, client, app):
    subscribe(client.application.test_client())
    panel.post("/snep/admin/avisos", data=campaign_form(when="agendar", date="2099-01-06", time="18:00", repeat="on"))
    c = PushCampaign.query.one()
    assert c.sent_at is None and c.repeat_weekly and c.scheduled_at.hour == 21  # 18h em Brasília = 21h UTC
    c.scheduled_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    with app.test_request_context():
        run_due()
        run_due()  # não manda duas vezes
    assert len(sent) == 1
    nxt = PushCampaign.query.filter(PushCampaign.sent_at.is_(None)).one()
    assert nxt.scheduled_at - c.scheduled_at == timedelta(days=7)


def test_weekly_limit(panel, tenant, sent, client):
    subscribe(client.application.test_client())
    for _ in range(MAX_PER_WEEK):
        panel.post("/snep/admin/avisos", data=campaign_form())
    r = panel.post("/snep/admin/avisos", data=campaign_form(), follow_redirects=True)
    assert "Limite de" in r.get_data(as_text=True)
    assert PushCampaign.query.count() == MAX_PER_WEEK


def test_past_schedule_and_cancel(panel, tenant, sent):
    r = panel.post("/snep/admin/avisos", data=campaign_form(when="agendar", date="2020-01-01", time="10:00"), follow_redirects=True)
    assert "já passou" in r.get_data(as_text=True)
    panel.post("/snep/admin/avisos", data=campaign_form(when="agendar", date="2099-01-01", time="10:00"))
    c = PushCampaign.query.one()
    panel.post(f"/snep/admin/avisos/{c.id}/cancelar")
    assert PushCampaign.query.count() == 0


def test_staff_cannot_send_campaigns(client, tenant):
    make_admin(tenant, "func").role = "funcionario"
    db.session.commit()
    login(client, username="func")
    assert client.get("/snep/admin/avisos").status_code in (302, 403)
