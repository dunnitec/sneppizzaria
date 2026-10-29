"""Relatório de testes 26/10, itens 16, 19, 20 e 32: mudanças no cardápio que quebravam preço, promoção e fidelidade."""
import json
from decimal import Decimal

from app.extensions import db
from app.models import Addon, Border, Category, LoyaltyProgram, Product, Promotion
from app.services.pricing import OrderError, price_item
from tests.test_admin import admin, panel  # noqa: F401


def cat(slug):
    return Category.query.filter_by(slug=slug).one()


def rename_premium(panel, broto="Broto", inteira="Inteira"):
    c = cat("premium")
    panel.post(f"/snep/admin/cardapio/{c.id}/linha", data={
        "name": c.name, "allows_addons": "on",
        "size-label-0": broto, "size-max-0": "1", "size-label-1": inteira, "size-max-1": "2"})
    db.session.expire_all()


def test_rename_size_updates_promotions_cards_and_borders(panel, tenant):
    c = cat("premium")
    promo = Promotion(tenant_id=tenant.id, name="10% Inteira", category_id=c.id, size_label="Inteira",
                      discount_type="percent", value=Decimal("10"), active=True)
    card = LoyaltyProgram(tenant_id=tenant.id, name="Premium", goal=10, count_category_ids=json.dumps([c.id]),
                          reward_category_id=c.id, reward_size="Inteira",
                          reward_product_ids=json.dumps([c.products[0].id]))
    border = Border.query.first()
    border.rules_json = json.dumps({"no_sizes": ["Broto"], "no_categories": []})
    db.session.add_all([promo, card])
    db.session.commit()
    rename_premium(panel, broto="Pequena", inteira="Grande")
    assert promo.size_label == "Grande" and card.reward_size == "Grande"
    assert "Pequena" in border.rules()["no_sizes"]


def test_delete_category_turns_off_card_that_depends_on_it(panel, tenant):
    c = cat("promocionais")
    card = LoyaltyProgram(tenant_id=tenant.id, name="Promocional", goal=10, count_category_ids=json.dumps([c.id]),
                          reward_category_id=c.id, reward_size="Grande (8 pedaços)",
                          reward_product_ids=json.dumps([c.products[0].id]))
    db.session.add(card)
    db.session.commit()
    html = panel.post(f"/snep/admin/cardapio/{c.id}/excluir", follow_redirects=True).get_data(as_text=True)
    db.session.expire_all()
    assert card.active is False and card.reward_category_id is None
    assert "cartão fidelidade Promocional foi desligado" in html


def test_addon_charges_whole_price_on_any_big_size(tenant):
    """Itens 18/19: “Grande” e “Gigante” pagam o adicional de inteira; só tamanho pequeno paga o de broto."""
    c = cat("premium")
    p = c.products[0]
    for v in p.variants:
        if v.label == "Inteira":
            v.label = "Gigante"
    db.session.commit()
    addon = Addon.query.filter_by(tenant_id=tenant.id, active=True).first()
    big = price_item(tenant, {"category_id": c.id, "variant": "Gigante", "flavors": [p.id], "quantity": 1,
                              "addons": [{"id": addon.id, "qty": 1}]})
    small = price_item(tenant, {"category_id": c.id, "variant": "Broto", "flavors": [p.id], "quantity": 1,
                                "addons": [{"id": addon.id, "qty": 1}]})
    giant = next(v.price for v in p.variants if v.label == "Gigante")
    broto = next(v.price for v in p.variants if v.label == "Broto")
    assert big["unit_price"] == Decimal(str(giant)) + addon.price_whole
    assert small["unit_price"] == Decimal(str(broto)) + addon.price_half


def test_fixed_price_promo_in_single_size_category_saves_the_size(panel, tenant):
    """Item 20: sem gravar o tamanho, um tamanho novo e mais caro entrava no preço fixo."""
    c = cat("promocionais")
    p = c.products[0]
    panel.post("/snep/admin/promocoes/nova", data={
        "name": "Terça", "category_id": c.id, "products": [p.id], "size_label": "", "discount_type": "price",
        "price": "24,99", "days": ["0", "1", "2", "3", "4", "5", "6"], "active": "on"})
    promo = Promotion.query.one()
    assert promo.size_label == "Grande (8 pedaços)"


def test_switched_off_combo_is_refused(tenant):
    """Item 32: combo desligado no estoque com o site aberto não pode mais ser vendido."""
    combo = Category.query.filter_by(tenant_id=tenant.id, kind="metro").first()
    for v in combo.products[0].variants:
        v.active = False
    db.session.commit()
    try:
        price_item(tenant, {"category_id": combo.id, "variant": "x", "flavors": [], "quantity": 1})
        assert False, "deveria recusar"
    except OrderError as e:
        assert "não está mais disponível" in str(e)
