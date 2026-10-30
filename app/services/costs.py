"""Custo dos produtos (CMV) e taxa da maquininha, para o relatório de lucro.

- Custo de um sabor num tamanho: o valor em R$ da aba Custos (ProductVariant.cost); sem ele, o % estimado da
  linha (Category.cost_percent) sobre o preço de tabela. Meio a meio soma a fração de cada sabor.
- Borda: Border.cost; sem ele, o % da linha sobre o preço da borda. Adicionais: o % da linha sobre o preço.
- Sem custo do sabor (nem em R$ nem em %), o item fica sem custo (None) e o relatório avisa quanto das vendas
  está sem custo cadastrado. Borda ou adicional sem custo contam zero.
- O custo é gravado no item na hora da venda (OrderItem.unit_cost); pedidos de antes do cadastro usam os custos
  de hoje (estimate).
"""

import json
import re
from decimal import Decimal

from app.models import Addon, Border, Category, Product, ProductVariant

CENT = Decimal("0.01")
PAY_METHODS = ("Débito", "Crédito", "Pix", "Dinheiro")
MAX_FEE = Decimal("30")


def _pct(category):
    return Decimal(category.cost_percent) / 100 if category and category.cost_percent is not None else None


class Menu:
    """Cardápio da loja carregado uma vez (para calcular o custo de muitos itens sem uma consulta por item)."""

    def __init__(self, tenant):
        self.categories = {c.id: c for c in Category.query.filter_by(tenant_id=tenant.id)}
        products = Product.query.filter_by(tenant_id=tenant.id).all()
        self.products = {p.id: p for p in products}
        self.variants = {(v.product_id, v.label): v for v in ProductVariant.query.filter(
            ProductVariant.product_id.in_(list(self.products) or [0]))}
        self.borders = {f"{re.sub(r'^Borda ', '', b.group_name)} - {b.name}"[:60]: b
                        for b in Border.query.filter_by(tenant_id=tenant.id)}
        self.addons = {a.name: a for a in Addon.query.filter_by(tenant_id=tenant.id)}


def _flavor_cost(menu, product_id, label, pct):
    variant = menu.variants.get((product_id, label))
    if variant is None:
        return None
    if variant.cost is not None:
        return Decimal(variant.cost)
    return Decimal(variant.price) * pct if pct is not None else None


def cost_of(menu, category_id, label, flavors, border_name="", addon_names=""):
    """Custo de UMA unidade do item; flavors = [(product_id, fração)]. None = sem custo cadastrado."""
    category = menu.categories.get(category_id)
    pct = _pct(category)
    if category is not None and category.kind == "metro":  # combo: custo do produto do combo
        combo = next((p for p in category.products if p.variants), None)
        variant = combo.variants[0] if combo else None
        if variant is None:
            return None
        if variant.cost is not None:
            return Decimal(variant.cost).quantize(CENT)
        return (Decimal(variant.price) * pct).quantize(CENT) if pct is not None else None
    total = Decimal("0")
    for product_id, share in flavors:
        part = _flavor_cost(menu, product_id, label, pct)
        if part is None:
            return None
        total += part * Decimal(share)
    border = menu.borders.get(border_name or "")
    if border is not None:
        if border.cost is not None:
            total += Decimal(border.cost)
        elif pct is not None:
            total += Decimal(border.price) * pct
    if addon_names and pct is not None:
        from app.services.pricing import SMALL_PIZZA

        whole = not SMALL_PIZZA.search(label or "")
        for chunk in addon_names.split(", "):
            qty, _, name = chunk.partition("x ")
            addon = menu.addons.get(name)
            if addon is not None and qty.isdigit():
                total += int(qty) * Decimal(addon.price_whole if whole else addon.price_half) * pct
    return total.quantize(CENT)


def estimate(menu, item):
    """Custo de uma unidade de um OrderItem: o gravado na venda ou, se não houver, pelos custos de hoje."""
    if item.unit_cost is not None:
        return Decimal(item.unit_cost)
    flavors = [(f.product_id, f.share) for f in item.flavor_rows if f.product_id]
    if not flavors and (menu.categories.get(item.category_id) or Category()).kind != "metro":
        return None
    return cost_of(menu, item.category_id, item.variant_label, flavors, item.border_name, item.addon_names)


# ---------- taxa da maquininha ----------

def fee_rates(tenant):
    """{"Débito": Decimal("1.99"), ...} em %."""
    try:
        data = json.loads(tenant.payment_fees or "{}")
    except ValueError:
        data = {}
    return {k: Decimal(str(v)) for k, v in data.items() if k in PAY_METHODS}


def card_fee(rates, method, total):
    rate = rates.get((method or "").strip())
    if rate is None and (method or "").strip() == "Cartão":  # pedidos antigos sem débito/crédito
        rate = rates.get("Crédito")
    return (Decimal(total) * rate / 100).quantize(CENT) if rate else Decimal("0")
