"""Carrinho simples guardado na sessão do Flask (sem login necessário)."""

import uuid
from decimal import Decimal

from flask import session

CART_KEY = "cart_items"
CART_TENANT_KEY = "cart_tenant_id"


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def get_cart(tenant_id):
    """Retorna a lista de itens do carrinho, esvaziando se for de outra loja."""
    if session.get(CART_TENANT_KEY) != tenant_id:
        session[CART_TENANT_KEY] = tenant_id
        session[CART_KEY] = []
    return session.get(CART_KEY, [])


def add_item(tenant_id, item: dict):
    """item precisa ter: product_names, variant_label, border_name, addon_names,
    unit_price, quantity, notes (opcional)."""
    cart = get_cart(tenant_id)
    item = dict(item)
    item["id"] = uuid.uuid4().hex[:8]
    item["unit_price"] = float(_as_decimal(item["unit_price"]))
    item["quantity"] = int(item.get("quantity", 1))
    item["line_total"] = round(item["unit_price"] * item["quantity"], 2)
    cart.append(item)
    session[CART_KEY] = cart
    session.modified = True
    return cart


def update_quantity(tenant_id, item_id, quantity):
    cart = get_cart(tenant_id)
    quantity = max(1, int(quantity))
    for item in cart:
        if item["id"] == item_id:
            item["quantity"] = quantity
            item["line_total"] = round(item["unit_price"] * quantity, 2)
            break
    session[CART_KEY] = cart
    session.modified = True
    return cart


def remove_item(tenant_id, item_id):
    cart = [i for i in get_cart(tenant_id) if i["id"] != item_id]
    session[CART_KEY] = cart
    session.modified = True
    return cart


def clear_cart(tenant_id):
    session[CART_KEY] = []
    session.modified = True


def cart_subtotal(cart):
    return round(sum(item["line_total"] for item in cart), 2)


def cart_item_count(cart):
    return sum(item["quantity"] for item in cart)
