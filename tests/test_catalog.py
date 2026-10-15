"""Edição completa do cardápio pelo painel: linhas, tamanhos, sabores, bordas, adicionais e bairros."""
import json
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Addon, Border, Category, Neighborhood, OrderItemFlavor, Product, ProductVariant
from app.services.menu_data import data_from_db
from app.services.pricing import OrderError, price_item
from tests.test_admin import admin, panel  # noqa: F401  (fixtures do painel)


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def sizes(c):
    return [(s["label"], s["max_flavors"]) for s in json.loads(c.sizes_json)]


# ---------- linhas ----------

def test_seeded_lines_know_their_sizes(app):
    assert sizes(cat("premium")) == [("Broto", 1), ("Inteira", 2)]
    assert sizes(cat("promocionais")) == [("Grande (8 pedaços)", 2)]


def test_create_line_with_first_size(panel, tenant):
    r = panel.post("/snep/admin/cardapio/linha/nova", data={
        "name": "Esfihas", "kind": "pizza", "size_label": "Unidade", "size_max": "1"})
    assert r.status_code == 302
    c = Category.query.filter_by(tenant_id=tenant.id, name="Esfihas").one()
    assert c.kind == "pizza" and c.slug == "esfihas" and not c.allows_addons
    assert sizes(c) == [("Unidade", 1)]
    assert c.sort_order > cat("doces").sort_order


def test_new_line_slug_never_repeats(panel, tenant):
    panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Pizzas Premium", "kind": "pizza", "size_label": "X", "size_max": "1"})
    slugs = [c.slug for c in Category.query.filter_by(tenant_id=tenant.id)]
    assert len(slugs) == len(set(slugs))


def test_edit_line_renames_size_everywhere_and_changes_max(panel):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data={
        "name": "Linha Premium", "allows_addons": "on",
        "size-label-0": "Brotinho", "size-max-0": "1", "size-label-1": "Inteira", "size-max-1": "3"})
    db.session.expire_all()
    c = cat("premium")
    assert c.name == "Linha Premium" and c.allows_addons
    assert sizes(c) == [("Brotinho", 1), ("Inteira", 3)]
    labels = {v.label for p in c.products for v in p.variants}
    assert labels == {"Brotinho", "Inteira"}
    assert {v.max_flavors for p in c.products for v in p.variants if v.label == "Inteira"} == {3}


def test_add_size_to_line(panel):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data={
        "name": c.name, "allows_addons": "on",
        "size-label-0": "Broto", "size-max-0": "1", "size-label-1": "Inteira", "size-max-1": "2",
        "new_size_label": "Gigante", "new_size_max": "4"})
    db.session.expire_all()
    assert sizes(cat("premium"))[-1] == ("Gigante", 4)


def test_remove_size_deletes_its_prices(panel):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data={
        "name": c.name, "allows_addons": "on",
        "size-label-0": "Broto", "size-max-0": "1", "size-del-0": "on",
        "size-label-1": "Inteira", "size-max-1": "2"})
    db.session.expire_all()
    assert sizes(cat("premium")) == [("Inteira", 2)]
    assert ProductVariant.query.filter_by(label="Broto").join(Product).filter(Product.category_id == c.id).count() == 0


def test_cannot_remove_the_only_size(panel):
    c = cat("promocionais")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data={
        "name": c.name, "size-label-0": "Grande (8 pedaços)", "size-max-0": "2", "size-del-0": "on"})
    db.session.expire_all()
    assert sizes(cat("promocionais")) == [("Grande (8 pedaços)", 2)]


def test_duplicate_size_names_refused(panel):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data={
        "name": c.name, "size-label-0": "Inteira", "size-max-0": "1", "size-label-1": "Inteira", "size-max-1": "2"})
    db.session.expire_all()
    assert sizes(cat("premium")) == [("Broto", 1), ("Inteira", 2)]


def test_move_line_up(panel, tenant):
    before = [c.slug for c in Category.query.filter_by(tenant_id=tenant.id).order_by(Category.sort_order)]
    panel.post(f"/snep/admin/cardapio/{cat('doces').id}/mover", data={"dir": "up"})
    db.session.expire_all()
    after = [c.slug for c in Category.query.filter_by(tenant_id=tenant.id).order_by(Category.sort_order)]
    i = before.index("doces")
    assert after[i - 1] == "doces" and after[i] == before[i - 1]


def test_delete_line_removes_flavors_and_combo_reference(panel, tenant):
    combo = cat("metro")
    combo.combo_sources = json.dumps(["premium", "doces"])
    db.session.commit()
    doces_id = cat("doces").id
    panel.post(f"/snep/admin/cardapio/{doces_id}/excluir")
    db.session.expire_all()
    assert Category.query.filter_by(id=doces_id).first() is None
    assert Product.query.filter_by(category_id=doces_id).count() == 0
    assert json.loads(cat("metro").combo_sources) == ["premium"]


def test_combo_line_cannot_be_deleted_here(panel):
    assert panel.post(f"/snep/admin/cardapio/{cat('metro').id}/excluir").status_code == 400


# ---------- sabores ----------

def test_flavor_row_can_add_a_missing_size(panel):
    c = cat("premium")
    p = Product.query.filter_by(name="Paulista").one()
    inteira = next(v for v in p.variants if v.label == "Inteira")
    broto = next(v for v in p.variants if v.label == "Broto")
    db.session.delete(broto)
    db.session.commit()
    form = {f"name-{p.id}": p.name, f"desc-{p.id}": "", f"active-{p.id}": "on",
            f"price-{inteira.id}": "65,00", f"newv-{p.id}-0": "41,00"}
    panel.post(f"/snep/admin/cardapio/{c.id}", data=form)
    db.session.expire_all()
    assert {(v.label, v.price, v.max_flavors) for v in p.variants} == {
        ("Broto", Decimal("41.00"), 1), ("Inteira", Decimal("65.00"), 2)}


def test_blank_price_removes_that_size_from_flavor(panel):
    c = cat("premium")
    p = Product.query.filter_by(name="Paulista").one()
    broto, inteira = sorted(p.variants, key=lambda v: v.label)
    form = {f"name-{p.id}": p.name, f"desc-{p.id}": "", f"active-{p.id}": "on",
            f"price-{broto.id}": "", f"price-{inteira.id}": "65,00"}
    panel.post(f"/snep/admin/cardapio/{c.id}", data=form)
    db.session.expire_all()
    assert [v.label for v in p.variants] == ["Inteira"]


def test_flavor_must_keep_one_size(panel):
    c = cat("premium")
    p = Product.query.filter_by(name="Paulista").one()
    form = {f"name-{p.id}": p.name, f"desc-{p.id}": "", f"active-{p.id}": "on",
            **{f"price-{v.id}": "" for v in p.variants}}
    panel.post(f"/snep/admin/cardapio/{c.id}", data=form)
    db.session.expire_all()
    assert len(p.variants) == 2


def test_delete_flavor_keeps_sales_history(panel, tenant, client):
    p = Product.query.filter_by(name="Paulista").one()
    item_flavor = OrderItemFlavor(order_item_id=1, product_id=p.id, product_name="Paulista", share=Decimal(1))
    db.session.add(item_flavor)
    db.session.commit()
    pid = p.id
    panel.post(f"/snep/admin/cardapio/sabor/{pid}/excluir")
    db.session.expire_all()
    assert db.session.get(Product, pid) is None
    assert ProductVariant.query.filter_by(product_id=pid).count() == 0
    kept = OrderItemFlavor.query.one()
    assert kept.product_id is None and kept.product_name == "Paulista"


def test_new_flavor_in_empty_line_uses_line_sizes(panel, tenant):
    panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Esfihas", "kind": "pizza", "size_label": "Unidade", "size_max": "1"})
    c = Category.query.filter_by(tenant_id=tenant.id, name="Esfihas").one()
    panel.post(f"/snep/admin/cardapio/{c.id}/novo", data={"name": "Carne", "desc": "", "newprice-0": "8"})
    p = Product.query.filter_by(name="Carne").one()
    assert [(v.label, v.price) for v in p.variants] == [("Unidade", Decimal("8.00"))]
    assert price_item(tenant, {"category_id": c.id, "variant": "Unidade", "flavors": [p.id], "quantity": 3})["line_total"] == Decimal("24.00")


# ---------- bordas e adicionais ----------

def test_create_rename_and_delete_border(panel, tenant):
    panel.post("/snep/admin/extras/borda/nova", data={"group": "Borda Recheada", "name": "Requeijão", "price": "16"})
    b = Border.query.filter_by(name="Requeijão").one()
    assert (b.group_name, b.price) == ("Borda Recheada", Decimal("16.00"))
    form = {}
    for x in Border.query:
        form.update({f"border-group-{x.id}": x.group_name, f"border-name-{x.id}": x.name,
                     f"border-price-{x.id}": str(x.price), f"border-active-{x.id}": "on"})
    form[f"border-name-{b.id}"] = "Requeijão Cremoso"
    panel.post("/snep/admin/extras", data=form)
    db.session.expire_all()
    assert b.name == "Requeijão Cremoso"
    panel.post(f"/snep/admin/extras/borda/{b.id}/excluir")
    assert Border.query.filter_by(id=b.id).first() is None


def test_create_and_delete_addon(panel):
    panel.post("/snep/admin/extras/adicional/novo", data={"name": "Gorgonzola Especial", "price_whole": "12", "price_half": "7"})
    a = Addon.query.filter_by(name="Gorgonzola Especial").one()
    assert (a.price_whole, a.price_half) == (Decimal("12.00"), Decimal("7.00"))
    panel.post(f"/snep/admin/extras/adicional/{a.id}/excluir")
    assert Addon.query.filter_by(id=a.id).first() is None


# ---------- bairros ----------

def test_rename_and_delete_neighborhood(panel):
    h = Neighborhood.query.first()
    form = {}
    for x in Neighborhood.query:
        form.update({f"name-{x.id}": x.name, f"fee-{x.id}": str(x.fee), f"active-{x.id}": "on"})
    form[f"name-{h.id}"] = "Bairro Renomeado"
    panel.post("/snep/admin/entrega", data=form)
    db.session.expire_all()
    assert h.name == "Bairro Renomeado"
    panel.post(f"/snep/admin/entrega/{h.id}/excluir")
    assert Neighborhood.query.filter_by(id=h.id).first() is None


# ---------- site ----------

def test_site_sees_new_line_and_sizes(panel, tenant, app):
    panel.post("/snep/admin/cardapio/linha/nova", data={"name": "Esfihas", "kind": "pizza", "size_label": "Unidade", "size_max": "1"})
    c = Category.query.filter_by(tenant_id=tenant.id, name="Esfihas").one()
    panel.post(f"/snep/admin/cardapio/{c.id}/novo", data={"name": "Carne", "desc": "", "newprice-0": "8"})
    with app.test_request_context():
        names = [x["name"] for x in data_from_db(tenant, "/x", {})["categories"]]
    assert "Esfihas" in names
