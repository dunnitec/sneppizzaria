"""Funções que separam os planos (Cardápio, Delivery, Completo): no plano sem a função, ela some e é recusada."""
from app.extensions import db
from app.models import AdminUser, Category, Product
from tests.test_admin import PASSWORD, admin, login, make_admin, panel  # noqa: F401


def basic(tenant):
    tenant.plan = "essencial"  # na Snep: plano sem nenhuma função extra
    db.session.commit()


def site_order(client):
    p = Product.query.filter_by(name="Paulista").one()
    c = Category.query.filter_by(slug="premium").one()
    return client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": c.id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}]}).get_json()


def test_tracking_link_only_with_feature(client, open_store):
    r = site_order(client)
    assert client.get(r["track_url"]).status_code == 200
    basic(open_store)
    r2 = site_order(client)
    assert r2["track_url"] is None
    assert client.get(r["track_url"]).status_code == 404


def test_km_needs_feature(panel, open_store):
    basic(open_store)
    open_store.delivery_mode = "km"
    db.session.commit()
    assert panel.get("/snep/api/frete?cep=13300000").status_code == 404  # site volta a cobrar por bairro
    panel.post("/snep/admin/entrega/modo", data={"delivery_mode": "km", "km_price": "2", "store_coords": "-23.2, -47.3"})
    html = panel.get("/snep/admin/entrega").get_data(as_text=True)
    assert "Disponível em um plano maior" in html


def test_counter_dispatch_reports_customers_hidden(panel, tenant):
    basic(tenant)
    for url in ("/snep/admin/pedidos/novo", "/snep/admin/entregas", "/snep/admin/relatorios", "/snep/admin/clientes"):
        assert panel.get(url).status_code == 302, url
    html = panel.get("/snep/admin/pedidos").get_data(as_text=True)
    assert "Novo pedido (balcão" not in html and ">Entregas<" not in html and ">Relatórios<" not in html


def test_staff_access_needs_feature(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    basic(tenant)
    login(client, username="caixa")
    r = client.get("/snep/admin/pedidos")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_owner_cannot_create_staff_without_feature(panel, tenant):
    basic(tenant)
    panel.post("/snep/admin/usuarios", data={"username": "caixa", "password": PASSWORD, "role": "funcionario"})
    assert AdminUser.query.filter_by(username="caixa").count() == 0
