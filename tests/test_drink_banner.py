"""Foto do título da categoria de bebidas: opção logo no topo da página e aparece no site."""
import io
import json
from decimal import Decimal

import pytest
from PIL import Image

from app.extensions import db
from app.models import Category, Product, ProductVariant
from tests.test_admin import admin, panel  # noqa: F401


@pytest.fixture
def drinks(tenant):
    line = Category(tenant_id=tenant.id, name="Bebidas", slug="bebidas-foto", kind="bebida", sort_order=0,
                    sizes_json=json.dumps([{"label": "2 litros", "max_flavors": 1}]))
    db.session.add(line)
    db.session.flush()
    db.session.add(Product(tenant_id=tenant.id, category_id=line.id, name="Coca cola",
                           variants=[ProductVariant(label="2 litros", price=Decimal("16"), max_flavors=1)]))
    db.session.commit()
    return line


def image():
    buf = io.BytesIO()
    Image.new("RGB", (800, 300), (200, 30, 30)).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_photo_option_comes_before_the_drink_list(panel, drinks):
    html = panel.get(f"/snep/admin/cardapio/{drinks.id}").get_data(as_text=True)
    assert html.count("Como aparece no site") == 1
    assert html.index("foto do título") < html.index("+ Adicionar")


def test_drink_banner_reaches_the_site_and_can_be_removed(panel, tenant, drinks):
    panel.post(f"/snep/admin/cardapio/{drinks.id}/imagem", data={"photo": (image(), "bebidas.png")},
               content_type="multipart/form-data")
    db.session.expire_all()
    assert drinks.banner_image
    assert drinks.banner_image in panel.get("/snep/").get_data(as_text=True)
    panel.post(f"/snep/admin/cardapio/{drinks.id}/imagem/remover")
    db.session.expire_all()
    assert drinks.banner_image is None
