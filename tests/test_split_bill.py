"""Dividir a conta: partes iguais, mesma forma de pagamento, no WhatsApp, no cupom, no painel e no acompanhamento."""
from decimal import Decimal

from app.extensions import db
from app.models import Category, Order, Product
from app.services.split import describe, parts, people
from tests.test_admin import admin, panel  # noqa: F401


def test_parts_always_add_up_to_the_total():
    assert parts(Decimal("100"), 3) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert parts(Decimal("100.01"), 4) == [Decimal("25.01"), Decimal("25"), Decimal("25"), Decimal("25")]
    for total in ("0.07", "57.9", "123.45"):
        for n in range(2, 11):
            assert sum(parts(Decimal(total), n)) == Decimal(total)
    assert describe(Decimal("100"), 4) == "4 pessoas: R$ 25,00 cada"
    assert describe(Decimal("100"), 3) == "3 pessoas: 1 de R$ 33,34 e 2 de R$ 33,33"


def test_people_accepts_only_2_to_10():
    assert [people(v) for v in (None, "", "1", 2, "10", 11, "x", -3)] == [None, None, None, 2, 10, None, None, None]


def split_order(client, n, withdraw=True):
    p = Product.query.filter_by(name="Paulista").one()
    c = Category.query.filter_by(slug="premium").one()
    data = {"withdraw": withdraw, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Dinheiro",
            "split_people": n, "items": [{"category_id": c.id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}]}
    if not withdraw:
        data.update(street="Rua A", number="10", neighborhood="Bairro que não existe")
    r = client.post("/snep/api/pedido", json=data)
    assert r.status_code == 200, r.json
    return db.session.get(Order, r.json["order_id"]), r.json


def test_split_shows_everywhere(panel, client, open_store):
    o, r = split_order(client, 3)
    assert o.split_people == 3
    text = describe(o.total, 3)
    assert f"Dividir a conta em {text}" in o.whatsapp_message
    label = panel.get(f"/snep/admin/pedidos/{o.id}/etiqueta").get_data(as_text=True)
    assert "DIVIDIR EM 3 PESSOAS" in label and "1 x R$" in label and "2 x R$" in label
    assert text in panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert text in client.get(r["track_url"]).get_data(as_text=True)


def test_split_without_delivery_fee_says_so(client, open_store):
    o, _ = split_order(client, 2, withdraw=False)
    assert o.fee_pending and o.split_text().endswith("(sem a entrega)")
    assert "(sem a entrega)" in o.whatsapp_message


def test_no_split_by_default(client, open_store):
    o, _ = split_order(client, None)
    assert o.split_people is None and o.split_text() == "" and "Dividir" not in o.whatsapp_message
