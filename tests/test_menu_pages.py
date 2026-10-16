"""Cardápio do painel pensado para leigos: resumo, página da categoria e nova categoria em passos."""
import json

from app.extensions import db
from app.models import Category, Product
from tests.test_admin import admin, login, make_admin, panel  # noqa: F401


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def test_overview_shows_each_category_with_visible_actions(panel):
    html = panel.get("/snep/admin/cardapio").get_data(as_text=True)
    for c in Category.query:
        assert c.name in html
        assert f"/snep/admin/cardapio/{c.id}" in html
    assert html.count(">Excluir</button>") == Category.query.filter(Category.kind != "metro").count()
    assert "+ Nova categoria" in html and "Editar itens e preços" in html


def test_category_page_has_add_items_settings_and_delete(panel):
    html = panel.get(f"/snep/admin/cardapio/{cat('premium').id}").get_data(as_text=True)
    assert "+ Adicionar sabor" in html and "Preço Inteira" in html
    assert "Configurações da categoria" in html
    assert "Excluir categoria" in html
    assert "Paulista" in html


def test_combo_page_shows_rules_and_price(panel):
    html = panel.get(f"/snep/admin/cardapio/{cat('metro').id}").get_data(as_text=True)
    assert "Regras do combo" in html and "Preço e descrição do combo" in html
    assert "Excluir categoria" not in html


def test_other_store_category_is_404(panel):
    assert panel.get("/snep/admin/cardapio/999999").status_code == 404


def test_wizard_page_and_create_with_several_sizes(panel, tenant):
    assert "Nova categoria" in panel.get("/snep/admin/cardapio/nova").get_data(as_text=True)
    r = panel.post("/snep/admin/cardapio/linha/nova", data={
        "kind": "pizza", "name": "Pizzas Especiais", "allows_addons": "on",
        "size_label-0": "Broto", "size_max-0": "1", "size_label-1": "Inteira", "size_max-1": "2",
        "size_label-2": "", "size_max-2": "2"})
    c = Category.query.filter_by(tenant_id=tenant.id, name="Pizzas Especiais").one()
    assert r.headers["Location"].endswith(f"/cardapio/{c.id}#adicionar")
    assert json.loads(c.sizes_json) == [{"label": "Broto", "max_flavors": 1}, {"label": "Inteira", "max_flavors": 2}]
    assert c.allows_addons


def test_wizard_drink_ignores_flavors_and_addons(panel, tenant):
    panel.post("/snep/admin/cardapio/linha/nova", data={
        "kind": "bebida", "name": "Sucos", "allows_addons": "on",
        "size_label-0": "300ml", "size_max-0": "4", "size_label-1": "1 litro", "size_max-1": "2"})
    c = Category.query.filter_by(tenant_id=tenant.id, name="Sucos").one()
    assert [s["max_flavors"] for s in json.loads(c.sizes_json)] == [1, 1]
    assert not c.allows_addons


def test_wizard_without_sizes_goes_back_with_message(panel, tenant):
    r = panel.post("/snep/admin/cardapio/linha/nova", data={"kind": "pizza", "name": "Sem tamanho"})
    assert r.headers["Location"].endswith("/cardapio/nova")
    assert Category.query.filter_by(tenant_id=tenant.id, name="Sem tamanho").count() == 0


def test_saving_items_returns_to_category_page(panel):
    c = cat("premium")
    p = Product.query.filter_by(name="Paulista").one()
    form = {f"name-{p.id}": p.name, f"desc-{p.id}": "", f"active-{p.id}": "on", **{f"price-{v.id}": str(v.price) for v in p.variants}}
    r = panel.post(f"/snep/admin/cardapio/{c.id}", data=form)
    assert r.headers["Location"].endswith(f"/snep/admin/cardapio/{c.id}")


def test_delete_category_returns_to_overview(panel):
    r = panel.post(f"/snep/admin/cardapio/{cat('doces').id}/excluir")
    assert r.headers["Location"].endswith("/snep/admin/cardapio")


def test_tabs_are_fewer_and_plain(panel):
    html = panel.get("/snep/admin/pedidos").get_data(as_text=True)
    for label in ("Pedidos", "Estoque", "Cardápio", "Aparência", "Conta"):
        assert f">{label}" in html
    assert ">Fotos</a>" not in html and ">Usuários</a>" not in html and ">Senha</a>" not in html


def test_staff_tabs(client, tenant):
    staff = make_admin(tenant, username="caixa")
    staff.role = "funcionario"
    db.session.commit()
    login(client, username="caixa")
    html = client.get("/snep/admin/pedidos").get_data(as_text=True)
    assert ">Minha senha" in html and ">Cardápio" not in html
