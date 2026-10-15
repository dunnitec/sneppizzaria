"""Fotos dos sabores: envio pelo painel, exibição no site e importação em lote."""
import io
import json

import pytest
from PIL import Image

from app.extensions import db
from app.models import Category, Product, Tenant
from app.services.menu_data import data_from_db
from tests.test_admin import admin, make_admin, panel  # noqa: F401  (fixtures do painel)


def jpeg_bytes(size=(1200, 900), color=(200, 60, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def upload_dir(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    return tmp_path / "uploads"


def paulista():
    return Product.query.filter_by(name="Paulista").one()


def send_photo(client, product, data, filename="foto.jpg"):
    return client.post(
        f"/snep/admin/fotos/{product.id}",
        data={"photo": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def test_photos_page_requires_login(client, admin):
    assert client.get("/snep/admin/fotos").status_code == 302


def test_photos_page_lists_flavors(panel):
    assert "Paulista" in panel.get("/snep/admin/fotos").get_data(as_text=True)


def test_upload_saves_a_small_webp(panel, upload_dir):
    r = send_photo(panel, paulista(), jpeg_bytes())
    assert r.status_code == 302
    db.session.expire_all()
    name = paulista().image
    assert name and name.endswith(".webp")
    with Image.open(upload_dir / name) as im:
        assert im.format == "WEBP"
        assert max(im.size) <= 800


def test_uploaded_photo_is_served_and_listed_in_menu(app, panel, tenant):
    send_photo(panel, paulista(), jpeg_bytes())
    db.session.expire_all()
    with app.test_request_context():  # a URL da foto é montada durante a requisição da página
        d = data_from_db(tenant, "/x", {})
    product = next(p for c in d["categories"] for p in c["products"] if p["name"] == "Paulista")
    assert product["image"].startswith("/uploads/")
    r = panel.get(product["image"])
    assert r.status_code == 200 and r.mimetype == "image/webp"


def test_flavor_without_photo_has_no_image(tenant):
    d = data_from_db(tenant, "/x", {})
    assert all(p["image"] is None for c in d["categories"] for p in c["products"])


def test_replacing_photo_deletes_the_old_file(panel, upload_dir):
    send_photo(panel, paulista(), jpeg_bytes(color=(1, 2, 3)))
    db.session.expire_all()
    first = paulista().image
    send_photo(panel, paulista(), jpeg_bytes(color=(9, 9, 9)))
    db.session.expire_all()
    assert paulista().image != first
    assert not (upload_dir / first).exists()


def test_not_an_image_is_refused(panel):
    send_photo(panel, paulista(), b"isto nao e uma imagem", filename="foto.jpg")
    db.session.expire_all()
    assert paulista().image is None


def test_remove_photo(panel, upload_dir):
    send_photo(panel, paulista(), jpeg_bytes())
    db.session.expire_all()
    name = paulista().image
    panel.post(f"/snep/admin/fotos/{paulista().id}/remover")
    db.session.expire_all()
    assert paulista().image is None
    assert not (upload_dir / name).exists()


def test_cannot_upload_to_another_stores_flavor(panel, cardapio, tmp_path):
    from seed import seed_from_file

    other = dict(cardapio, tenant=dict(cardapio["tenant"], slug="outra", name="Outra"))
    f = tmp_path / "outra.json"
    f.write_text(json.dumps(other), encoding="utf-8")
    seed_from_file(f)
    outra = Tenant.query.filter_by(slug="outra").one()
    foreign = Product.query.filter_by(tenant_id=outra.id, name="Paulista").one()
    assert send_photo(panel, foreign, jpeg_bytes()).status_code == 404


def test_uploads_route_does_not_leave_the_folder(client):
    assert client.get("/uploads/../snep.db").status_code == 404


# ---------- importação em lote pelo nome do arquivo ----------

def run_import(app, folder):
    return app.test_cli_runner().invoke(args=["import-photos", "snep", str(folder)])


def test_import_matches_file_names_to_flavors(app, tmp_path):
    folder = tmp_path / "fotos"
    folder.mkdir()
    (folder / "paulista.jpg").write_bytes(jpeg_bytes())
    (folder / "Pizzas Promocionais - Calabresa Acebolada.png").write_bytes(jpeg_bytes())
    (folder / "Premium - A Moda do Nene.jpeg").write_bytes(jpeg_bytes())
    (folder / "sabor que nao existe.jpg").write_bytes(jpeg_bytes())
    result = run_import(app, folder)
    assert result.exit_code == 0, result.output
    db.session.expire_all()
    assert paulista().image
    assert Product.query.filter_by(name="Calabresa Acebolada").one().image
    assert Product.query.filter_by(name="A Moda do Nenê").one().image
    assert "sabor que nao existe.jpg" in result.output


def test_import_refuses_ambiguous_name(app, tmp_path):
    # "Portuguesa" só existe nas Promocionais, mas um nome repetido em duas linhas precisa da categoria
    promo = Category.query.filter_by(slug="promocionais").one()
    db.session.add(Product(tenant_id=promo.tenant_id, category_id=Category.query.filter_by(slug="premium").one().id,
                           name="Portuguesa"))
    db.session.commit()
    folder = tmp_path / "fotos"
    folder.mkdir()
    (folder / "Portuguesa.jpg").write_bytes(jpeg_bytes())
    result = run_import(app, folder)
    assert "Portuguesa.jpg" in result.output
    assert all(p.image is None for p in Product.query.filter_by(name="Portuguesa"))
