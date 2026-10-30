"""Tipo de loja e categorias para qualquer comida: lanche (item com tamanhos) e monte o seu (açaí, marmita)."""
import json
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Addon, Border, Category, OrderItem, Product, ProductVariant
from app.services.menu_data import data_from_db
from app.services.pricing import OrderError, price_item
from app.services import report_book as book
from tests.test_admin import admin, panel  # noqa: F401
from tests.test_finance import today
from tests.test_pos import post as pos_post


@pytest.fixture
def burgers(tenant):
    line = Category(tenant_id=tenant.id, name="Lanches", slug="lanches", kind="lanche", allows_addons=True, sort_order=50,
                    sizes_json=json.dumps([{"label": "Simples", "max_flavors": 1}, {"label": "Duplo", "max_flavors": 1}]))
    db.session.add(line)
    db.session.flush()
    db.session.add(Product(tenant_id=tenant.id, category_id=line.id, name="X-Salada", variants=[
        ProductVariant(label="Simples", price=Decimal("22"), max_flavors=1),
        ProductVariant(label="Duplo", price=Decimal("30"), max_flavors=1)]))
    db.session.add(Product(tenant_id=tenant.id, category_id=line.id, name="X-Bacon", variants=[
        ProductVariant(label="Simples", price=Decimal("25"), max_flavors=1)]))
    db.session.commit()
    return line


@pytest.fixture
def acai(tenant):
    line = Category(tenant_id=tenant.id, name="Monte seu açaí", slug="acai", kind="montar", allows_addons=True,
                    sort_order=51, pick_label="Complementos", pick_options="Granola\nBanana\nPaçoca\nLeite condensado",
                    sizes_json=json.dumps([{"label": "300 ml", "max_flavors": 2}, {"label": "500 ml", "max_flavors": 3}]))
    db.session.add(line)
    db.session.flush()
    db.session.add(Product(tenant_id=tenant.id, category_id=line.id, name="Açaí tradicional", variants=[
        ProductVariant(label="300 ml", price=Decimal("15"), max_flavors=2),
        ProductVariant(label="500 ml", price=Decimal("20"), max_flavors=3)]))
    db.session.commit()
    return line


def item(line, name, size, **extra):
    p = Product.query.filter_by(category_id=line.id, name=name).one()
    return {"category_id": line.id, "variant": size, "flavors": [p.id], "quantity": 1, **extra}


# ---------- preço no servidor ----------

def test_burger_price_with_addon_at_full_price(tenant, burgers):
    addon = Addon.query.filter_by(tenant_id=tenant.id, active=True).first()
    line = price_item(tenant, item(burgers, "X-Salada", "Duplo", addons=[{"id": addon.id, "qty": 1}]))
    assert line["unit_price"] == Decimal("30") + addon.price_whole  # lanche não tem preço de “meia”
    assert (line["product_names"], line["kind"]) == ("X-Salada", "lanche")


def test_burger_rejects_border_and_two_items(tenant, burgers):
    with pytest.raises(OrderError, match="borda"):
        price_item(tenant, item(burgers, "X-Salada", "Simples", border_id=Border.query.first().id))
    both = item(burgers, "X-Salada", "Simples")
    both["flavors"].append(Product.query.filter_by(name="X-Bacon").one().id)
    with pytest.raises(OrderError):
        price_item(tenant, both)


def test_acai_free_picks_go_to_the_ticket(tenant, acai):
    line = price_item(tenant, item(acai, "Açaí tradicional", "500 ml", picks=["Granola", "Banana", "Paçoca"]))
    assert line["unit_price"] == Decimal("20")
    assert line["extras"] == "Complementos: Granola, Banana, Paçoca"


def test_acai_picks_limit_and_unknown(tenant, acai):
    with pytest.raises(OrderError, match="até 2"):
        price_item(tenant, item(acai, "Açaí tradicional", "300 ml", picks=["Granola", "Banana", "Paçoca"]))
    with pytest.raises(OrderError, match="não está mais disponível"):
        price_item(tenant, item(acai, "Açaí tradicional", "300 ml", picks=["Chocolate suíço"]))
    with pytest.raises(OrderError):
        price_item(tenant, item(acai, "Açaí tradicional", "300 ml", picks=["Banana", "Banana"]))


def test_site_data_has_picks_and_business_words(tenant, acai):
    d = data_from_db(tenant, "/x", {})
    cat = next(c for c in d["categories"] if c["slug"] == "acai")
    assert cat["picks"]["options"] == ["Granola", "Banana", "Paçoca", "Leite condensado"]
    assert d["business"]["key"] == "pizzaria"


def test_pos_order_with_burger_and_acai(panel, tenant, burgers, acai):
    r = pos_post(panel, channel="balcao", items=[item(burgers, "X-Bacon", "Simples"),
                                                  item(acai, "Açaí tradicional", "300 ml", picks=["Banana"])])
    assert r.status_code == 200, r.json
    rows = OrderItem.query.order_by(OrderItem.id).all()[-2:]
    assert [i.product_names for i in rows] == ["X-Bacon", "Açaí tradicional"]
    assert rows[1].extras == "Complementos: Banana"


# ---------- painel ----------

def test_create_burger_and_acai_categories(panel, tenant):
    r = panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Hambúrgueres", "kind": "lanche",
                                                            "size_label-0": "Único", "size_max-0": "9", "allows_addons": "on"})
    assert r.status_code == 302
    burger = Category.query.filter_by(name="Hambúrgueres").one()
    assert burger.kind == "lanche" and burger.allows_addons and burger.sizes() == [{"label": "Único", "max_flavors": 1}]
    panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Açaí", "kind": "montar",
                                                        "size_label-0": "500 ml", "size_max-0": "3"})
    acai_line = Category.query.filter_by(name="Açaí").one()
    assert acai_line.sizes() == [{"label": "500 ml", "max_flavors": 3}]
    r = panel.post(f"/snep/admin/cardapio/{acai_line.id}/complementos",
                   data={"pick_label": "Acompanhamentos", "pick_options": "Granola\n  Banana \n\nMorango"}, follow_redirects=True)
    assert "complementos salvos" in r.get_data(as_text=True)
    assert acai_line.pick_settings() == {"label": "Acompanhamentos", "options": ["Granola", "Banana", "Morango"]}
    html = panel.get(f"/snep/admin/cardapio/{acai_line.id}").get_data(as_text=True)
    assert "Complementos grátis" in html and "aceita borda" not in html


def test_picks_reject_duplicates(panel, acai):
    r = panel.post(f"/snep/admin/cardapio/{acai.id}/complementos", data={"pick_options": "Banana\nbanana"},
                   follow_redirects=True)
    assert "repetidos" in r.get_data(as_text=True)


def test_new_category_page_lists_main_kind_first(panel, tenant):
    tenant.business_type = "acai"
    db.session.commit()
    html = panel.get("/snep/admin/cardapio/nova").get_data(as_text=True)
    assert html.index('value="montar"') < html.index('value="pizza"')


def test_store_type_changes_closing_words(panel, tenant, burgers):
    pos_post(panel, channel="balcao", items=[item(burgers, "X-Salada", "Simples")])
    assert book.closing(tenant, today())["main_label"] == "Pizzas vendidas"
    tenant.business_type = "lanchonete"
    db.session.commit()
    c = book.closing(tenant, today())
    assert c["main_label"] == "Lanches vendidos" and c["pizza_total"] == 1
    assert {l["label"]: l["qty"] for l in c["pizza_lines"]}["Lanches"] == 1
