"""Dados da loja, recados, pedido mínimo, banners, fundo e usuários de funcionário."""
import io
from decimal import Decimal

import pytest
from PIL import Image

from app.extensions import db
from app.models import AdminUser, Banner, Category, Order, Product
from app.services.menu_data import data_from_db
from tests.test_admin import PASSWORD, admin, login, make_admin, panel, store_form  # noqa: F401


@pytest.fixture(autouse=True)
def upload_dir(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    return tmp_path / "uploads"


def image_bytes(size=(1600, 550)):
    buf = io.BytesIO()
    Image.new("RGB", size, (180, 20, 20)).save(buf, "JPEG")
    return buf.getvalue()


# ---------- loja ----------

def test_store_identity_payments_notices_and_min_order(panel, tenant, app):
    panel.post("/snep/admin/loja", data=store_form(
        tenant, name="Snep Pizzaria Itu", address="Rua Nova, 10", instagram="@snep.itu",
        payments=["Pix", "Dinheiro"], other_payments="Vale-refeição",
        notices="Meio a meio cobra o maior valor!\n\nPeça até 22h", min_order="40"))
    db.session.expire_all()
    assert (tenant.name, tenant.address, tenant.instagram) == ("Snep Pizzaria Itu", "Rua Nova, 10", "snep.itu")
    assert tenant.accepted_payments == "Dinheiro,Pix,Vale-refeição"
    assert tenant.min_order == Decimal("40.00")
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    assert d["notices"] == ["Meio a meio cobra o maior valor!", "Peça até 22h"]
    assert d["min_order"] == 40.0


def test_store_needs_one_payment_method(panel, tenant):
    before = tenant.accepted_payments
    panel.post("/snep/admin/loja", data=store_form(tenant, payments=[], other_payments=""))
    db.session.expire_all()
    assert tenant.accepted_payments == before


def test_order_below_minimum_is_refused(client, tenant, open_store):
    tenant.min_order = Decimal("500")
    db.session.commit()
    p = Product.query.filter_by(name="Paulista").one()
    r = client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": Category.query.filter_by(slug="premium").one().id, "variant": "Inteira",
                   "flavors": [p.id], "quantity": 1}]})
    assert r.status_code == 400 and "mínimo" in r.json["error"]
    assert Order.query.count() == 0


# ---------- banners e fundo ----------

def test_upload_reorder_and_delete_banners(panel, tenant, client, app):
    for _ in range(2):
        panel.post("/snep/admin/visual/banner", data={"photo": (io.BytesIO(image_bytes()), "b.jpg")},
                   content_type="multipart/form-data")
    first, second = Banner.query.filter_by(tenant_id=tenant.id).order_by(Banner.sort_order).all()
    panel.post(f"/snep/admin/visual/banner/{second.id}/mover", data={"dir": "up"})
    db.session.expire_all()
    assert [b.id for b in Banner.query.order_by(Banner.sort_order)] == [second.id, first.id]
    html = client.get("/snep/").get_data(as_text=True)
    assert html.index(second.image) < html.index(first.image)
    panel.post(f"/snep/admin/visual/banner/{first.id}/excluir")
    assert Banner.query.count() == 1


def test_site_uses_default_banners_until_owner_uploads(client):
    assert "img/snep/banner1.webp" in client.get("/snep/").get_data(as_text=True)


def test_background_upload_and_remove(panel, tenant, client):
    panel.post("/snep/admin/visual/fundo", data={"photo": (io.BytesIO(image_bytes((1200, 800))), "f.jpg")},
               content_type="multipart/form-data")
    db.session.expire_all()
    assert tenant.background_image
    assert tenant.background_image in client.get("/snep/").get_data(as_text=True)
    panel.post("/snep/admin/visual/fundo/remover")
    db.session.expire_all()
    assert tenant.background_image is None


def test_import_default_banners_command(app, tenant):
    result = app.test_cli_runner().invoke(args=["import-static-banners", "snep"])
    assert result.exit_code == 0, result.output
    assert Banner.query.filter_by(tenant_id=tenant.id).count() == 3


# ---------- usuários ----------

def test_owner_creates_staff_user(panel, tenant):
    r = panel.post("/snep/admin/usuarios", data={"username": "Caixa", "password": "senha-caixa-1", "role": "funcionario"})
    assert r.status_code == 302
    user = AdminUser.query.filter_by(username="caixa").one()
    assert user.role == "funcionario" and user.check_password("senha-caixa-1")


def test_staff_only_sees_orders(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    assert client.get("/snep/admin/pedidos").status_code == 200
    assert client.get("/snep/admin/senha").status_code == 200
    for page in ("cardapio", "relatorios", "clientes", "loja", "usuarios", "fotos", "visual", "entrega", "extras"):
        assert client.get(f"/snep/admin/{page}").status_code == 403, page
    html = client.get("/snep/admin/pedidos").get_data(as_text=True)
    assert "Relatórios" not in html and "Cardápio" not in html


def test_owner_cannot_delete_or_demote_self(panel, admin):
    panel.post(f"/snep/admin/usuarios/{admin.id}/excluir")
    assert db.session.get(AdminUser, admin.id) is not None


def test_owner_resets_staff_password_and_deletes(panel, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    panel.post(f"/snep/admin/usuarios/{staff.id}/senha", data={"password": "nova-senha-99"})
    db.session.expire_all()
    assert staff.check_password("nova-senha-99")
    panel.post(f"/snep/admin/usuarios/{staff.id}/excluir")
    assert AdminUser.query.filter_by(username="caixa").first() is None


def test_short_password_for_new_user_refused(panel):
    panel.post("/snep/admin/usuarios", data={"username": "caixa", "password": "123", "role": "funcionario"})
    assert AdminUser.query.filter_by(username="caixa").first() is None
