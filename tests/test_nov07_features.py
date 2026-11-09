"""Pedidos de 07/11: meio a meio com doce, pedaços no tamanho, retirada chamativa, letra do cupom,
comanda do motoboy opcional e aviso de “pronto para retirar”."""
import json
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Category, Order
from app.services.order_display import slices
from tests.test_admin import admin, panel, store_form  # noqa: F401
from tests.test_receipt_eta import cat, site_order


def mix_premium_with_doces():
    premium = cat("premium")
    premium.mix_sources = json.dumps(["doces"])
    db.session.commit()
    return premium, cat("doces")


# ---------- meio a meio Premium + Doce ----------

def test_half_premium_half_sweet_when_owner_allows(client, open_store):
    premium, doces = mix_premium_with_doces()
    salty, sweet = premium.products[0], doces.products[0]
    _, order = site_order(client, [{"category_id": premium.id, "variant": "Inteira", "flavors": [salty.id, sweet.id], "quantity": 1}])
    item = order.items[0]
    prices = [v.price for p in (salty, sweet) for v in p.variants if v.label == "Inteira"]
    assert item.unit_price == max(prices)  # vale o mais caro, como no meio a meio comum
    assert sweet.name in item.product_names and salty.name in item.product_names


def test_mix_off_rejects_sweet_flavor(client, open_store):
    premium, doces = cat("premium"), cat("doces")
    r = client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": premium.id, "variant": "Inteira", "flavors": [premium.products[0].id, doces.products[0].id], "quantity": 1}]})
    assert r.status_code == 400


def test_mix_needs_one_flavor_of_own_line(client, open_store):
    premium, doces = mix_premium_with_doces()
    a, b = doces.products[:2]
    r = client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": premium.id, "variant": "Inteira", "flavors": [a.id, b.id], "quantity": 1}]})
    assert r.status_code == 400 and "Premium" in r.json["error"]


def test_menu_json_exposes_mix(client, open_store):
    mix_premium_with_doces()
    html = client.get("/snep/").get_data(as_text=True)
    assert '"mix": ["doces"]' in html or '"mix":["doces"]' in html


# ---------- pedaços: Broto 4, Inteira 8 ----------

@pytest.mark.parametrize("label,expected", [("Broto", 4), ("Inteira", 8), ("Grande", 8), ("Grande (8 pedaços)", None), ("Média", None)])
def test_slices_default(label, expected):
    assert slices("pizza", label) == expected


def test_slices_owner_choice_wins():
    assert slices("pizza", "Broto", [{"label": "Broto", "slices": 6}]) == 6
    assert slices("pizza", "Broto", [{"label": "Broto", "slices": 0}]) is None  # 0 = não mostrar
    assert slices("bebida", "Broto") is None


def test_receipt_and_whatsapp_show_slices(client, panel, open_store):
    premium = cat("premium")
    r, order = site_order(client, [{"category_id": premium.id, "variant": "Broto", "flavors": [premium.products[0].id], "quantity": 1}])
    html = panel.get(f"/snep/admin/pedidos/{order.id}/etiqueta").get_data(as_text=True)
    assert "Broto (4 pedaços)" in html
    assert "Broto (4 pedaços)" in order.whatsapp_message


# ---------- retirada chamativa no cupom ----------

def test_pickup_receipt_has_banner(client, panel, open_store):
    premium = cat("premium")
    _, pickup = site_order(client, [{"category_id": premium.id, "variant": "Inteira", "flavors": [premium.products[0].id], "quantity": 1}])
    _, deliver = site_order(client, [{"category_id": premium.id, "variant": "Inteira", "flavors": [premium.products[0].id], "quantity": 1}], withdraw=False)
    assert "RETIRADA NA LOJA" in panel.get(f"/snep/admin/pedidos/{pickup.id}/etiqueta").get_data(as_text=True)
    assert "RETIRADA NA LOJA" not in panel.get(f"/snep/admin/pedidos/{deliver.id}/etiqueta").get_data(as_text=True)


# ---------- letra do cupom e comanda do motoboy ----------

def test_store_saves_receipt_font_and_dispatch_print(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, label_size="80x0", receipt_font="130", print_dispatch="on"))
    db.session.expire_all()
    assert tenant.receipt_font == 130 and tenant.print_dispatch is True
    panel.post("/snep/admin/loja", data=store_form(tenant, label_size="80x0", receipt_font="999"))
    db.session.expire_all()
    assert tenant.receipt_font == 130 and tenant.print_dispatch is False  # tamanho fora da lista é ignorado


def test_receipt_uses_font_size(client, panel, open_store):
    open_store.receipt_font = 120
    db.session.commit()
    premium = cat("premium")
    _, order = site_order(client, [{"category_id": premium.id, "variant": "Inteira", "flavors": [premium.products[0].id], "quantity": 1}])
    assert "--fs: 1.2" in panel.get(f"/snep/admin/pedidos/{order.id}/etiqueta").get_data(as_text=True)


# ---------- pronto para retirar ----------

def test_ready_marks_pickup_order(client, panel, open_store):
    premium = cat("premium")
    _, order = site_order(client, [{"category_id": premium.id, "variant": "Inteira", "flavors": [premium.products[0].id], "quantity": 1}])
    assert panel.post(f"/snep/admin/pedidos/{order.id}/pronto").status_code == 400  # ainda não confirmado
    order.status = "confirmado"
    db.session.commit()
    assert panel.post(f"/snep/admin/pedidos/{order.id}/pronto", headers={"X-Requested-With": "fetch"}).status_code == 204
    db.session.expire_all()
    assert db.session.get(Order, order.id).ready_at is not None


def test_ready_refused_for_delivery(client, panel, open_store):
    premium = cat("premium")
    _, order = site_order(client, [{"category_id": premium.id, "variant": "Inteira", "flavors": [premium.products[0].id], "quantity": 1}], withdraw=False)
    order.status = "confirmado"
    db.session.commit()
    assert panel.post(f"/snep/admin/pedidos/{order.id}/pronto").status_code == 400
