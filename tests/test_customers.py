"""Cadastro automático de clientes pelo telefone e aba Clientes do painel."""
import pytest

from app.extensions import db
from app.models import Category, Customer, Order, Product
from tests.test_admin import admin, panel  # noqa: F401  (fixtures do painel)


def order_payload(phone="(11) 99999-0000", name="Ana", **over):
    paulista = Product.query.filter_by(name="Paulista").one()
    premium = Category.query.filter_by(slug="premium").one()
    data = {
        "withdraw": False, "customer_name": name, "customer_phone": phone,
        "street": "Rua A", "number": "10", "neighborhood": "Bairro Alto", "payment_method": "Pix",
        "items": [{"category_id": premium.id, "variant": "Inteira", "flavors": [paulista.id], "quantity": 1}],
    }
    data.update(over)
    return data


def test_first_order_creates_customer(client, open_store):
    r = client.post("/snep/api/pedido", json=order_payload())
    assert r.status_code == 200, r.json
    customer = Customer.query.one()
    assert (customer.name, customer.phone_key, customer.neighborhood) == ("Ana", "11999990000", "Bairro Alto")
    assert Order.query.one().customer_id == customer.id


def test_same_phone_in_another_format_is_the_same_customer(client, open_store):
    client.post("/snep/api/pedido", json=order_payload(phone="11 99999-0000"))
    client.post("/snep/api/pedido", json=order_payload(phone="+55 (11) 99999-0000", name="Ana Paula", street="Rua B"))
    customer = Customer.query.one()
    assert customer.name == "Ana Paula" and customer.street == "Rua B"
    assert {o.customer_id for o in Order.query} == {customer.id}


def test_pickup_order_keeps_last_known_address(client, open_store):
    client.post("/snep/api/pedido", json=order_payload())
    client.post("/snep/api/pedido", json=order_payload(withdraw=True, street="", number="", neighborhood=""))
    assert Customer.query.one().street == "Rua A"


@pytest.mark.parametrize("phone", ["123", "abc", "1199999000011223"])
def test_invalid_phone_is_refused(client, open_store, phone):
    r = client.post("/snep/api/pedido", json=order_payload(phone=phone))
    assert r.status_code == 400
    assert "telefone" in r.json["error"].lower()
    assert Order.query.count() == 0


# ---------- painel ----------

def test_customers_page_requires_login(client, admin):
    assert client.get("/snep/admin/clientes").status_code == 302


def test_customers_page_lists_and_searches(panel, open_store):
    panel.post("/snep/api/pedido", json=order_payload(name="Maria Souza", phone="11911112222"))
    panel.post("/snep/api/pedido", json=order_payload(name="João Lima", phone="11933334444"))
    html = panel.get("/snep/admin/clientes").get_data(as_text=True)
    assert "Maria Souza" in html and "João Lima" in html
    html = panel.get("/snep/admin/clientes?q=maria").get_data(as_text=True)
    assert "Maria Souza" in html and "João Lima" not in html
    html = panel.get("/snep/admin/clientes?q=3333").get_data(as_text=True)
    assert "João Lima" in html and "Maria Souza" not in html


def test_customer_totals_count_only_confirmed_orders(panel, open_store):
    panel.post("/snep/api/pedido", json=order_payload())
    panel.post("/snep/api/pedido", json=order_payload())
    first = Order.query.order_by(Order.id).first()
    first.status = "confirmado"
    db.session.commit()
    from app.routes.admin import customer_rows

    row = customer_rows(Customer.query.one().tenant_id)[0]
    assert row["orders"] == 1
    assert row["spent"] == first.total


def test_delete_customer_erases_personal_data_but_keeps_sales(panel, open_store):
    panel.post("/snep/api/pedido", json=order_payload(name="Maria Souza", phone="11911112222"))
    order = Order.query.one()
    total = order.total
    customer = Customer.query.one()
    r = panel.post(f"/snep/admin/clientes/{customer.id}/apagar")
    assert r.status_code == 302
    db.session.expire_all()
    assert Customer.query.count() == 0
    order = Order.query.one()
    assert order.customer_name == "Cliente removido"
    assert order.customer_phone == "" and order.street == "" and order.number == ""
    assert "Maria" not in (order.whatsapp_message or "")
    assert order.total == total


@pytest.mark.parametrize("key, shown", [("11999990000", "(11) 99999-0000"), ("1133334444", "(11) 3333-4444")])
def test_phone_is_shown_formatted(key, shown):
    from app.services.customers import format_phone

    assert format_phone(key) == shown
