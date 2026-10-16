"""Bebidas (linha do tipo "bebida") e aba Estoque (liga/desliga rápido de tudo)."""
import json

from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Addon, Border, Category, Order, OrderItem, Product, ProductVariant
from app.services.menu_data import data_from_db
from app.services.pricing import OrderError, price_item
from app.services.reports import sales_report
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


@pytest.fixture
def drinks(tenant):
    """Linha Refrigerantes com Coca-Cola (lata e 2L) e Guaraná (só 2L)."""
    line = Category(tenant_id=tenant.id, name="Refrigerantes", slug="refrigerantes", kind="bebida", sort_order=99,
                    sizes_json=json.dumps([{"label": "Lata 350ml", "max_flavors": 1}, {"label": "2 litros", "max_flavors": 1}]))
    db.session.add(line)
    db.session.flush()
    coca = Product(tenant_id=tenant.id, category_id=line.id, name="Coca-Cola", variants=[
        ProductVariant(label="Lata 350ml", price=Decimal("6"), max_flavors=1),
        ProductVariant(label="2 litros", price=Decimal("14"), max_flavors=1)])
    guarana = Product(tenant_id=tenant.id, category_id=line.id, name="Guaraná", variants=[
        ProductVariant(label="2 litros", price=Decimal("12"), max_flavors=1)])
    db.session.add_all([coca, guarana])
    db.session.commit()
    return line


def drink(line, name, size, qty=1, **extra):
    p = Product.query.filter_by(category_id=line.id, name=name).one()
    return {"category_id": line.id, "variant": size, "flavors": [p.id], "quantity": qty, **extra}


# ---------- bebidas ----------

def test_drink_price_and_title(tenant, drinks):
    line = price_item(tenant, drink(drinks, "Coca-Cola", "2 litros", qty=2))
    assert (line["unit_price"], line["line_total"]) == (Decimal("14.00"), Decimal("28.00"))
    assert line["product_names"] == "Coca-Cola" and line["kind"] == "bebida"


def test_drink_rejects_border_and_second_flavor(tenant, drinks):
    border = Border.query.first()
    with pytest.raises(OrderError):
        price_item(tenant, drink(drinks, "Coca-Cola", "2 litros", border_id=border.id))
    req = drink(drinks, "Coca-Cola", "2 litros")
    req["flavors"].append(Product.query.filter_by(name="Guaraná").one().id)
    with pytest.raises(OrderError):
        price_item(tenant, req)


def test_drink_size_that_product_does_not_have(tenant, drinks):
    with pytest.raises(OrderError):
        price_item(tenant, drink(drinks, "Guaraná", "Lata 350ml"))


def test_create_drink_line_in_panel(panel, tenant):
    panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Bebidas", "kind": "bebida", "size_label": "Lata", "size_max": "3"})
    line = Category.query.filter_by(tenant_id=tenant.id, name="Bebidas").one()
    assert line.kind == "bebida"
    assert json.loads(line.sizes_json) == [{"label": "Lata", "max_flavors": 1}]  # bebida é sempre 1 item


def test_drink_lines_cannot_feed_the_combo(panel, drinks):
    combo = Category.query.filter_by(kind="metro").one()
    panel.post(f"/snep/admin/cardapio/{combo.id}/combo", data={
        "name": combo.name, "sources": ["premium", "refrigerantes"], "max_flavors": "4", "extras": "", "choice_label": "", "choice_options": ""})
    db.session.expire_all()
    assert json.loads(combo.combo_sources) == ["premium"]


def test_empty_lines_are_hidden_from_site(app, tenant):
    db.session.add(Category(tenant_id=tenant.id, name="Vazia", slug="vazia", kind="pizza", sort_order=50,
                            sizes_json=json.dumps([{"label": "Única", "max_flavors": 1}])))
    db.session.commit()
    with app.test_request_context():
        names = [c["name"] for c in data_from_db(tenant, "/x", {})["categories"]]
    assert "Vazia" not in names


def test_reports_separate_drinks_from_pizzas(client, tenant, drinks, open_store):
    paulista = Product.query.filter_by(name="Paulista").one()
    premium = Category.query.filter_by(slug="premium").one()
    r = client.post("/snep/api/pedido", json={
        "withdraw": True, "customer_name": "Ana", "customer_phone": "11999990000", "payment_method": "Pix",
        "items": [{"category_id": premium.id, "variant": "Inteira", "flavors": [paulista.id], "quantity": 1},
                  drink(drinks, "Coca-Cola", "2 litros", qty=2)]})
    assert r.status_code == 200, r.json
    assert {i.kind for i in OrderItem.query} == {"pizza", "bebida"}
    order = Order.query.one()
    order.status = "confirmado"
    db.session.commit()
    from app.services.hours import local_time

    day = local_time(order.created_at).date()
    rep = sales_report(tenant, day, day)
    assert rep["pizzas"] == 1
    assert [(d["name"], d["qty"]) for d in rep["top_drinks"]] == [("Coca-Cola 2 litros", 2)]
    assert all(f["name"] != "Coca-Cola" for f in rep["top_flavors"])


# ---------- estoque ----------

def toggle(client, kind, item_id, active):
    return client.post("/snep/admin/estoque/alternar", json={"type": kind, "id": item_id, "active": active})


def test_stock_page_lists_everything(panel, drinks):
    html = panel.get("/snep/admin/estoque").get_data(as_text=True)
    for text in ("Paulista", "Coca-Cola", "Lata 350ml", "Catupiry", "Calabresa"):
        assert text in html


@pytest.mark.parametrize("kind, model, finder", [
    ("product", Product, lambda: Product.query.filter_by(name="Paulista").one()),
    ("border", Border, lambda: Border.query.first()),
    ("addon", Addon, lambda: Addon.query.first()),
])
def test_toggle_off_and_on(panel, kind, model, finder):
    item = finder()
    r = toggle(panel, kind, item.id, False)
    assert r.status_code == 200 and r.json == {"ok": True, "active": False}
    db.session.expire_all()
    assert finder().active is False
    toggle(panel, kind, item.id, True)
    db.session.expire_all()
    assert finder().active is True


def test_sold_out_size_disappears_and_is_refused(panel, tenant, drinks, app):
    coca = Product.query.filter_by(name="Coca-Cola").one()
    two_liters = next(v for v in coca.variants if v.label == "2 litros")
    toggle(panel, "variant", two_liters.id, False)
    db.session.expire_all()
    with app.test_request_context():
        cats = data_from_db(tenant, "/x", {})["categories"]
    sizes = next(p for c in cats for p in c["products"] if p["name"] == "Coca-Cola")["variants"]
    assert [v["label"] for v in sizes] == ["Lata 350ml"]
    with pytest.raises(OrderError):
        price_item(tenant, drink(drinks, "Coca-Cola", "2 litros"))
    assert price_item(tenant, drink(drinks, "Coca-Cola", "Lata 350ml"))["unit_price"] == Decimal("6.00")


def test_product_with_every_size_sold_out_is_hidden(panel, tenant, drinks, app):
    guarana = Product.query.filter_by(name="Guaraná").one()
    toggle(panel, "variant", guarana.variants[0].id, False)
    with app.test_request_context():
        names = [p["name"] for c in data_from_db(tenant, "/x", {})["categories"] for p in c["products"]]
    assert "Guaraná" not in names


def test_bulk_toggle_by_ingredient(panel):
    ids = [p.id for p in Product.query if "calabresa" in (p.description or "").lower()]
    assert len(ids) > 3
    r = panel.post("/snep/admin/estoque/lote", json={"ids": ids, "active": False})
    assert r.json == {"ok": True, "changed": len(ids)}
    db.session.expire_all()
    assert all(not db.session.get(Product, i).active for i in ids)


def test_toggle_rejects_unknown_type_and_other_store(panel, cardapio, tmp_path):
    assert toggle(panel, "pedido", 1, False).status_code == 400
    from app.models import Tenant
    from seed import seed_from_file

    other = dict(cardapio, tenant=dict(cardapio["tenant"], slug="outra", name="Outra"))
    f = tmp_path / "o.json"
    f.write_text(json.dumps(other), encoding="utf-8")
    seed_from_file(f)
    foreign = Product.query.filter_by(tenant_id=Tenant.query.filter_by(slug="outra").one().id).first()
    assert toggle(panel, "product", foreign.id, False).status_code == 404


def test_staff_can_use_stock(client, tenant):
    staff = make_admin(tenant, username="cozinha")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="cozinha")
    assert client.get("/snep/admin/estoque").status_code == 200
    p = Product.query.filter_by(name="Paulista").one()
    assert toggle(client, "product", p.id, False).status_code == 200


def test_stock_toggle_needs_csrf_token(csrf_app):
    from app.models import Tenant

    make_admin(Tenant.query.filter_by(slug="snep").one())
    c = csrf_app.test_client()
    page = c.get("/snep/admin/login").get_data(as_text=True)
    import re

    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    c.post("/snep/admin/login", data={"username": "dono", "password": "senha-forte-1", "csrf_token": token})
    # depois do login a sessão é nova: o navegador usa o token que vem na própria página.
    # (nos testes o contexto da aplicação é o mesmo entre requisições; limpa o token guardado em g)
    from flask import g

    g.pop("csrf_token", None)
    token = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/snep/admin/estoque").get_data(as_text=True)).group(1)
    p = Product.query.filter_by(name="Paulista").one()
    assert c.post("/snep/admin/estoque/alternar", json={"type": "product", "id": p.id, "active": False}).status_code == 400
    assert c.post("/snep/admin/estoque/alternar", json={"type": "product", "id": p.id, "active": False},
                  headers={"X-CSRFToken": token}).status_code == 200


def test_empty_drink_line_opens_add_form_with_prices(panel, tenant):
    r = panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Refrigerantes", "kind": "bebida", "size_label": "Lata 350ml", "size_max": "2"})
    line = Category.query.filter_by(tenant_id=tenant.id, name="Refrigerantes").one()
    assert r.headers["Location"].endswith(f"/snep/admin/cardapio/{line.id}#adicionar")
    html = panel.get(f"/snep/admin/cardapio/{line.id}").get_data(as_text=True)
    assert "+ Adicionar bebida" in html and "Preço Lata 350ml" in html
    assert "ainda está vazia" in html
