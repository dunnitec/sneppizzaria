"""Visual novo do site (tema escuro): o que o dono edita no painel e o que o site mostra."""
import io

import pytest
from PIL import Image

from app.extensions import db
from app.models import Category
from app.services.menu_data import data_from_db
from tests.test_admin import admin, panel, store_form  # noqa: F401


@pytest.fixture(autouse=True)
def upload_dir(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")


def jpg(size=(600, 240)):
    buf = io.BytesIO()
    Image.new("RGB", size, (150, 30, 20)).save(buf, "JPEG")
    return buf.getvalue()


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def line_form(c, **over):
    form = {"name": c.name, "allows_addons": "on" if c.allows_addons else ""}
    for i, s in enumerate(c.sizes()):
        form[f"size-label-{i}"] = s["label"]
        form[f"size-max-{i}"] = str(s["max_flavors"])
    form.update(over)
    return {k: v for k, v in form.items() if v != ""}


def test_category_look_is_saved(panel):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data=line_form(c, subtitle="Ingredientes em maior quantidade",
                                                                    icon="coroa", accent="dourado"))
    db.session.expire_all()
    assert (c.subtitle, c.icon, c.accent) == ("Ingredientes em maior quantidade", "coroa", "dourado")


def test_unknown_icon_or_color_falls_back(panel):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data=line_form(c, icon="foguete", accent="neon"))
    db.session.expire_all()
    assert (c.icon, c.accent) == ("fatia", "vermelho")


def test_combo_look_is_saved(panel):
    c = cat("metro")
    panel.post(f"/snep/admin/cardapio/{c.id}/combo", data={
        "name": c.name, "sources": ["premium"], "max_flavors": "4", "extras": "", "choice_label": "", "choice_options": "",
        "subtitle": "70 cm com 4 sabores", "icon": "trem", "accent": "vermelho"})
    db.session.expire_all()
    assert (c.subtitle, c.icon) == ("70 cm com 4 sabores", "trem")


def test_category_title_image_upload_and_remove(panel):
    c = cat("promocionais")
    panel.post(f"/snep/admin/cardapio/{c.id}/imagem", data={"photo": (io.BytesIO(jpg()), "t.jpg")},
               content_type="multipart/form-data")
    db.session.expire_all()
    assert c.banner_image and c.banner_image.endswith(".webp")
    panel.post(f"/snep/admin/cardapio/{c.id}/imagem/remover")
    db.session.expire_all()
    assert c.banner_image is None


def test_hero_image_and_slogan(panel, tenant):
    panel.post("/snep/admin/visual/topo", data={"photo": (io.BytesIO(jpg((900, 400))), "h.jpg")},
               content_type="multipart/form-data")
    panel.post("/snep/admin/loja", data=store_form(tenant, slogan="A melhor pizzaria de Itu"))
    db.session.expire_all()
    assert tenant.hero_image and tenant.slogan == "A melhor pizzaria de Itu"
    panel.post("/snep/admin/visual/topo/remover")
    db.session.expire_all()
    assert tenant.hero_image is None


def test_site_data_carries_the_look(app, tenant):
    c = cat("premium")
    c.subtitle, c.icon, c.accent = "Mais recheio", "coroa", "dourado"
    tenant.slogan = "A melhor pizzaria de Itu"
    db.session.commit()
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    premium = next(x for x in d["categories"] if x["slug"] == "premium")
    assert (premium["subtitle"], premium["icon"], premium["accent"], premium["banner"]) == ("Mais recheio", "coroa", "dourado", None)
    assert d["tenant"]["slogan"] == "A melhor pizzaria de Itu"


def test_site_page_has_new_header_and_cart_bar(client, tenant):
    tenant.slogan = "A melhor pizzaria de Itu"
    db.session.commit()
    html = client.get("/snep/").get_data(as_text=True)
    assert 'class="brand"' in html and "A melhor pizzaria de" in html and 'id="mbar-count"' in html
    assert 'id="catsel"' in html and 'id="cats"' in html  # o script do cardápio continua achando os pontos de montagem


def test_panel_pages_show_look_fields(panel):
    html = panel.get(f"/snep/admin/cardapio/{cat('premium').id}").get_data(as_text=True)
    assert "Como aparece no site" in html and 'name="subtitle"' in html and 'name="icon"' in html
    assert "Foto do topo" in panel.get("/snep/admin/visual").get_data(as_text=True)
