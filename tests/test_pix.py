"""Pix pelo site: código copia e cola (BR Code), QR Code, configuração e confirmação no painel."""
from decimal import Decimal
from urllib.parse import unquote

import pytest

from app.extensions import db
from app.models import Category, Order, Product
from app.services.menu_data import data_from_db
from app.services.pix import PixKeyError, crc16, normalize_key, payload
from tests.test_admin import admin, login, make_admin, panel, store_form  # noqa: F401

KEY = "pizzaria.teste@email.com"


def with_pix(tenant):
    tenant.pix_key, tenant.pix_key_type, tenant.pix_city = KEY, "email", "Itu"
    db.session.commit()
    return tenant


def order_payload(**over):
    paulista = Product.query.filter_by(name="Paulista").one()
    base = {"withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
            "items": [{"category_id": Category.query.filter_by(slug="premium").one().id, "variant": "Inteira",
                       "flavors": [paulista.id], "quantity": 1}]}
    base.update(over)
    return base


# ---------- código Pix ----------

def test_crc_matches_central_bank_example():
    body = ("00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
            "5913Fulano de Tal6008BRASILIA62070503***6304")
    assert crc16(body) == "1D3D"


def test_payload_has_key_amount_and_valid_crc():
    code = payload(KEY, "Snep Pizzaria", "Itu", Decimal("76.9"), "PEDIDO395")
    assert code.startswith("000201")
    assert "0014br.gov.bcb.pix0124" + KEY in code
    assert "540576.90" in code and "5802BR" in code
    assert "5913SNEP PIZZARIA" in code and "6003ITU" in code
    assert "62130509PEDIDO395" in code
    assert code[-4:] == crc16(code[:-4])


def test_payload_removes_accents_and_limits_sizes():
    code = payload(KEY, "Pizzaria São João do Céu Azul Grande", "São José dos Campos", 10, "x")
    assert "5925PIZZARIA SAO JOAO DO CEU" in code
    assert "6015SAO JOSE DOS CA" in code


@pytest.mark.parametrize("kind, text, expected", [
    ("email", " Pizzaria.Teste@Email.com ", "pizzaria.teste@email.com"),
    ("celular", "(11) 99999-0000", "+5511999990000"),
    ("celular", "+55 11 99999-0000", "+5511999990000"),
    ("cpf", "123.456.789-09", "12345678909"),
    ("cpf", "12.345.678/0001-90", "12345678000190"),
    ("aleatoria", "123E4567-E89B-12D3-A456-426614174000", "123e4567-e89b-12d3-a456-426614174000"),
])
def test_keys_are_normalized(kind, text, expected):
    assert normalize_key(kind, text) == expected


@pytest.mark.parametrize("kind, text", [("email", "sem-arroba"), ("celular", "9999"), ("cpf", "123"), ("aleatoria", "abc"), ("?", "x")])
def test_invalid_keys_are_refused(kind, text):
    with pytest.raises(PixKeyError):
        normalize_key(kind, text)


# ---------- pedido pelo site ----------

def test_pix_order_returns_qr_code_with_exact_total(client, open_store):
    with_pix(open_store)
    body = client.post("/snep/api/pedido", json=order_payload()).get_json()
    assert body["ok"] and body["pix"]
    order = db.session.get(Order, body["order_id"])
    assert body["pix"]["amount"] == float(order.total)
    assert f"54{len(f'{order.total:.2f}'):02d}{order.total:.2f}" in body["pix"]["code"]
    assert f"PEDIDO{order.id}" in body["pix"]["code"]
    assert body["pix"]["qr"].startswith("data:image/svg+xml;base64,")
    assert "mandar o comprovante" in unquote(body["wa_link"])


def test_no_qr_code_without_key_or_for_other_payment(client, open_store):
    assert client.post("/snep/api/pedido", json=order_payload()).get_json()["pix"] is None
    with_pix(open_store)
    assert client.post("/snep/api/pedido", json=order_payload(payment_method="Dinheiro")).get_json()["pix"] is None


def test_no_qr_code_while_delivery_fee_is_unknown(client, open_store):
    with_pix(open_store)
    body = client.post("/snep/api/pedido", json=order_payload(
        withdraw=False, street="Rua A", number="1", neighborhood="Bairro que não existe")).get_json()
    assert body["pix"] is None and body["pix_pending"] is True


def test_site_data_tells_if_pix_is_on(app, tenant):
    with app.test_request_context():
        assert data_from_db(tenant, "/x", {})["pix"] is False
        with_pix(tenant)
        assert data_from_db(tenant, "/x", {})["pix"] is True


# ---------- painel ----------

def test_owner_saves_pix_key(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, status="open", pix_key_type="email",
                                                    pix_key="Pizzaria.Teste@email.com", pix_city="Itu"))
    db.session.expire_all()
    assert (tenant.pix_key, tenant.pix_key_type, tenant.pix_city) == (KEY, "email", "Itu")


def test_invalid_pix_key_is_not_saved(panel, tenant):
    r = panel.post("/snep/admin/loja", data=store_form(tenant, status="open", pix_key_type="celular", pix_key="123", pix_city="Itu"),
                   follow_redirects=True)
    assert "celular com DDD" in r.get_data(as_text=True)
    db.session.expire_all()
    assert tenant.pix_key is None


def test_pix_needs_city(panel, tenant):
    panel.post("/snep/admin/loja", data=store_form(tenant, status="open", pix_key_type="email", pix_key=KEY, pix_city=""))
    db.session.expire_all()
    assert tenant.pix_key is None


def test_blank_key_turns_pix_off(panel, tenant):
    with_pix(tenant)
    panel.post("/snep/admin/loja", data=store_form(tenant, status="open", pix_key_type="email", pix_key=""))
    db.session.expire_all()
    assert tenant.pix_key is None


def test_mark_pix_received_and_receipt(client, open_store):
    with_pix(open_store)
    order_id = client.post("/snep/api/pedido", json=order_payload()).get_json()["order_id"]
    make_admin(open_store)
    login(client)
    assert "Pix pelo site: confira" in client.get("/snep/admin/pedidos").get_data(as_text=True)
    assert "CONFERIR PAGAMENTO" in client.get(f"/snep/admin/pedidos/{order_id}/etiqueta").get_data(as_text=True)
    client.post(f"/snep/admin/pedidos/{order_id}/pix")
    assert db.session.get(Order, order_id).pix_paid_at is not None
    assert "Pix recebido" in client.get("/snep/admin/pedidos").get_data(as_text=True)
    assert "· PAGO" in client.get(f"/snep/admin/pedidos/{order_id}/etiqueta").get_data(as_text=True)
    client.post(f"/snep/admin/pedidos/{order_id}/pix")  # desfazer
    assert db.session.get(Order, order_id).pix_paid_at is None


def test_mark_pix_refused_for_other_payment(client, open_store):
    order_id = client.post("/snep/api/pedido", json=order_payload(payment_method="Dinheiro")).get_json()["order_id"]
    make_admin(open_store)
    login(client)
    assert client.post(f"/snep/admin/pedidos/{order_id}/pix").status_code == 400


def test_staff_can_mark_pix(client, open_store):
    order_id = client.post("/snep/api/pedido", json=order_payload()).get_json()["order_id"]
    make_admin(open_store, "func").role = "funcionario"
    db.session.commit()
    login(client, username="func")
    assert client.post(f"/snep/admin/pedidos/{order_id}/pix").status_code == 302
