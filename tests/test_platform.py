"""Painel da plataforma (/plataforma/): nova pizzaria, planos e suspensão. O dono da loja não entra aqui."""
import re

import pytest

from app.extensions import db
from app.models import AdminUser, Category, LoyaltyProgram, PlatformAdmin, Product, ProductVariant, Tenant
from app.services import push
from app.services.menu_data import data_from_db
from tests.test_admin import admin, login, panel  # noqa: F401
from tests.test_promotions import promo

PASSWORD = "senha-da-plataforma"


@pytest.fixture
def platform(app):
    """Navegador logado na plataforma (separado do navegador do dono da loja)."""
    client = app.test_client()
    user = PlatformAdmin(username="jeferson")
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    r = client.post("/plataforma/entrar", data={"username": "jeferson", "password": PASSWORD})
    assert r.status_code == 302
    return client


def new_store(client, **over):
    data = {"name": "Pizzaria do João", "slug": "", "whatsapp": "5511988887777", "plan": "completo",
            "owner_username": "dono", "copy_from": ""}
    data.update(over)
    return client.post("/plataforma/lojas/nova", data=data)


def shown_password(html):
    return re.search(r"Senha: ([a-z0-9-]+)", html).group(1)


# ---------- acesso ----------

def test_platform_needs_its_own_login(client):
    assert client.get("/plataforma/").headers["Location"].endswith("/plataforma/entrar")


def test_store_owner_cannot_enter_the_platform(panel):
    assert panel.get("/plataforma/").status_code == 302


def test_wrong_password_is_refused_and_locks(client):
    user = PlatformAdmin(username="jeferson")
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    for _ in range(5):
        client.post("/plataforma/entrar", data={"username": "jeferson", "password": "errada"})
    r = client.post("/plataforma/entrar", data={"username": "jeferson", "password": PASSWORD})
    assert "Muitas tentativas" in r.get_data(as_text=True)


def test_list_shows_the_stores(platform):
    html = platform.get("/plataforma/").get_data(as_text=True)
    assert "Snep Pizzaria" in html and "/snep/" in html


# ---------- nova pizzaria ----------

def test_new_store_with_copied_menu_and_owner_login(platform, client, tenant):
    r = new_store(platform, copy_from=str(tenant.id))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    t = Tenant.query.filter_by(slug="pizzaria-do-joao").one()
    assert (t.plan, t.active, t.whatsapp) == ("completo", True, "5511988887777")
    assert Category.query.filter_by(tenant_id=t.id).count() == Category.query.filter_by(tenant_id=tenant.id).count()
    assert Product.query.filter_by(tenant_id=t.id).count() == Product.query.filter_by(tenant_id=tenant.id).count()
    joao_prices = sorted(float(v.price) for v in ProductVariant.query.join(Product).filter(Product.tenant_id == t.id))
    snep_prices = sorted(float(v.price) for v in ProductVariant.query.join(Product).filter(Product.tenant_id == tenant.id))
    assert joao_prices == snep_prices
    # a cópia é independente: mudar o preço numa loja não muda na outra
    assert not {c.id for c in Category.query.filter_by(tenant_id=t.id)} & {c.id for c in Category.query.filter_by(tenant_id=tenant.id)}
    # o dono entra no painel dele com a senha mostrada
    other = client.application.test_client()
    assert login(other, "pizzaria-do-joao", "dono", shown_password(html)).status_code == 302
    assert other.get("/pizzaria-do-joao/admin/").status_code == 200
    assert other.get("/snep/admin/").status_code == 302  # e só no dele


def test_address_is_normalized(platform):
    new_store(platform, slug="Pizzaria São João")
    assert Tenant.query.filter_by(slug="pizzaria-sao-joao").count() == 1


def test_new_store_starts_empty(platform):
    new_store(platform, slug="joao")
    t = Tenant.query.filter_by(slug="joao").one()
    assert Category.query.filter_by(tenant_id=t.id).count() == 0
    assert AdminUser.query.filter_by(tenant_id=t.id, role="dono").count() == 1


def test_copied_photo_is_a_separate_file(platform, tenant, app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    (tmp_path / "snep-foto.webp").write_bytes(b"foto")
    p = Product.query.filter_by(tenant_id=tenant.id, name="Paulista").one()
    p.image = "snep-foto.webp"
    db.session.commit()
    new_store(platform, slug="joao", copy_from=str(tenant.id))
    copy = Product.query.join(Tenant).filter(Tenant.slug == "joao", Product.name == "Paulista").one()
    assert copy.image and copy.image != "snep-foto.webp" and (tmp_path / copy.image).read_bytes() == b"foto"


@pytest.mark.parametrize("slug", ["snep", "plataforma", "ab", "--"])
def test_bad_or_taken_address_is_refused(platform, slug):
    before = Tenant.query.count()
    r = new_store(platform, slug=slug)
    assert "Endereço" in r.get_data(as_text=True) or "endereço" in r.get_data(as_text=True)
    assert Tenant.query.count() == before


def test_bad_whatsapp_is_refused(platform):
    new_store(platform, whatsapp="123")
    assert Tenant.query.count() == 1


def test_owner_password_reset(platform, client):
    html = new_store(platform, slug="joao").get_data(as_text=True)
    t = Tenant.query.filter_by(slug="joao").one()
    old = shown_password(html)
    new = shown_password(platform.post(f"/plataforma/lojas/{t.id}/senha-do-dono").get_data(as_text=True))
    other = client.application.test_client()
    assert login(other, "joao", "dono", old).status_code == 200  # senha antiga não entra mais
    assert login(other, "joao", "dono", new).status_code == 302


def test_open_store_panel_as_owner(platform):
    new_store(platform, slug="joao")
    t = Tenant.query.filter_by(slug="joao").one()
    r = platform.post(f"/plataforma/lojas/{t.id}/abrir-painel")
    assert r.headers["Location"].endswith("/joao/admin/")
    assert platform.get("/joao/admin/").status_code == 200


# ---------- planos ----------

def set_plan(platform, tenant, plan, active="1"):
    platform.post(f"/plataforma/lojas/{tenant.id}", data={"plan": plan, "active": active, "platform_notes": "vence dia 10"})
    db.session.expire_all()


def test_essential_plan_hides_complete_features(platform, panel, tenant, app):
    promo(tenant)
    db.session.add(LoyaltyProgram(tenant_id=tenant.id, name="Promocional", goal=10, active=True,
                                  reward_category_id=Category.query.filter_by(slug="premium").one().id))
    tenant.first_order_enabled = True
    db.session.commit()
    set_plan(platform, tenant, "essencial")
    assert (tenant.plan, tenant.platform_notes) == ("essencial", "vence dia 10")

    # painel da loja: abas somem e as telas voltam para o Início
    home = panel.get("/snep/admin/").get_data(as_text=True)
    assert ">Promoções<" not in home and ">Fidelidade<" not in home and ">Avisos<" not in home
    for path in ("/snep/admin/promocoes", "/snep/admin/fidelidade", "/snep/admin/avisos"):
        assert panel.get(path).headers["Location"].endswith("/snep/admin/")

    # site: sem promoção, sem cadastro, sem app
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    assert d["promotions"] == [] and d["loyalty"] == [] and d["first_order"] is None
    assert d["account_url"] == "" and d["app"] is False and d["push_key"] == ""
    assert panel.post("/snep/api/conta/cadastro", json={"name": "Ana", "phone": "11999990000", "pin": "1234"}).status_code == 404
    assert push.send(tenant, [object()], "t", "b", "/") == 0

    # volta para o Completo: tudo reaparece (nada foi apagado)
    set_plan(platform, tenant, "completo")
    with app.test_request_context():
        d = data_from_db(tenant, "/x", {})
    assert d["promotions"] and d["first_order"] and d["account_url"] and d["app"] is True


# ---------- suspensão ----------

def test_suspended_store_is_off_the_air(platform, panel, tenant):
    set_plan(platform, tenant, "completo", active="0")
    r = panel.get("/snep/")
    assert r.status_code == 503 and "fora do ar" in r.get_data(as_text=True)
    assert panel.post("/snep/api/pedido", json={}).status_code == 503
    assert panel.get("/snep/admin/").status_code == 503
    assert "Suspensa" in platform.get("/plataforma/").get_data(as_text=True)
    set_plan(platform, tenant, "completo", active="1")
    assert panel.get("/snep/").status_code == 200
