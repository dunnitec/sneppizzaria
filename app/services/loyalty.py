"""Fidelidade (cartões de selos) e desconto no 1º pedido — só para quem tem cadastro no site.

Cartões (LoyaltyProgram): o dono cria quantos quiser, ex.:
  - “Promocional”: pizzas das Promocionais valem selo; a cada 10, 1 Promocional grátis;
  - “Premium”: pizzas Premium e Doces valem selo; a cada 10, 1 Premium grátis.
No prêmio o cliente escolhe só entre os sabores que o dono liberou. Cada pizza vale
1 selo no cartão da categoria dela, contando os pedidos confirmados depois do cadastro
(inclusive os lançados por telefone com o mesmo número). A pizza-prêmio não gera selo;
pedido cancelado não conta selo e devolve o prêmio.

1º pedido: quem se cadastra e ainda não tem nenhum pedido (cancelados não contam)
ganha o desconto do Tenant.first_order_*.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import SOLD_STATUSES, LoyaltyProgram, Order, OrderItem, Product

CENT = Decimal("0.01")


def programs(tenant):
    """Cartões prontos para o site: ligados e com tudo preenchido."""
    rows = LoyaltyProgram.query.filter_by(tenant_id=tenant.id, active=True).order_by(LoyaltyProgram.sort_order,
                                                                                     LoyaltyProgram.id)
    return [p for p in rows if is_ready(p)]


def is_ready(p):
    return bool(p.active and p.goal and p.counted() and p.reward_category_id and p.reward_products())


def reward_text(p):
    """Ex.: “1 pizza Promocional Grande grátis” (o tamanho sem o “(8 pedaços)”)."""
    size = re.sub(r"\s*\(.*?\)", "", p.reward_size or "")
    return f"1 pizza {p.name}{' ' + size if size else ''} grátis"


def flavor_names(p):
    ids = p.reward_products()
    return [x.name for x in Product.query.filter(Product.id.in_(ids)).order_by(Product.name)] if ids else []


def _used_like(p):
    return f"%,{p.id},%"


def stamps(p, customer):
    """Selos do cartão: pizzas confirmadas das categorias que contam, desde o cadastro, menos as pizzas-prêmio."""
    if not customer or not customer.registered_at or not p.counted():
        return 0
    sold = Order.query.filter(Order.customer_id == customer.id, Order.status.in_(SOLD_STATUSES),
                              Order.created_at >= customer.registered_at)
    pizzas = (db.session.query(func.coalesce(func.sum(OrderItem.quantity), 0))
              .filter(OrderItem.order_id.in_(sold.with_entities(Order.id)), OrderItem.category_id.in_(p.counted()))
              .scalar())
    rewards = sold.filter(Order.loyalty_programs.like(_used_like(p))).count() if p.reward_category_id in p.counted() else 0
    return max(0, int(pizzas) - rewards)


def rewards_used(p, customer):
    """Prêmios usados (pedido pendente também segura o prêmio; cancelado devolve)."""
    return Order.query.filter(Order.customer_id == customer.id, Order.loyalty_programs.like(_used_like(p)),
                              Order.status != "cancelado").count()


def card(p, customer):
    """Cartão de selos para o site e o painel."""
    total = stamps(p, customer)
    available = max(0, total // p.goal - rewards_used(p, customer)) if customer else 0
    return {"id": p.id, "name": p.name, "goal": p.goal, "filled": total % p.goal, "rewards": available,
            "total_stamps": total, "reward_text": reward_text(p), "flavors": flavor_names(p),
            "category_id": p.reward_category_id, "size": p.reward_size or "", "product_ids": p.reward_products()}


def cards(tenant, customer):
    return [card(p, customer) for p in programs(tenant)]


def public_info(tenant):
    """O que o site mostra para quem ainda não entrou (convite para o cadastro)."""
    return [{"id": p.id, "name": p.name, "goal": p.goal, "reward": reward_text(p), "category_id": p.reward_category_id,
             "size": p.reward_size or "", "product_ids": p.reward_products(), "flavors": flavor_names(p)}
            for p in programs(tenant)]


def first_order_eligible(tenant, customer):
    if not tenant.first_order_enabled or not customer or not customer.registered_at:
        return False
    return not Order.query.filter(Order.customer_id == customer.id, Order.status != "cancelado").first()


def first_order_text(tenant):
    v = Decimal(tenant.first_order_value or 0)
    if tenant.first_order_type == "percent":
        return f"{v.normalize():f}% de desconto no 1º pedido"
    return f"R$ {v:.2f}".replace(".", ",") + " de desconto no 1º pedido"


def eligible(p, line):
    """A pizza do pedido serve como prêmio deste cartão? (categoria, tamanho e todos os sabores liberados)"""
    if line.get("category_id") != p.reward_category_id:
        return False
    if p.reward_size and line["variant_label"] != p.reward_size:
        return False
    allowed = set(p.reward_products())
    return all(prod.id in allowed for prod, _ in line.get("flavors", []))


def discounts(tenant, customer, cart, use_programs):
    """Descontos do pedido do site. Devolve (valor, observação, é_1º_pedido, ids dos cartões usados)."""
    subtotal = sum((line["line_total"] for line in cart), Decimal("0"))
    total, notes, used = Decimal("0"), [], []
    free_units = {}  # linha do pedido -> quantas unidades já viraram prêmio
    wanted = {int(x) for x in (use_programs or []) if str(x).isdigit()}
    for p in programs(tenant) if customer else []:
        if p.id not in wanted or card(p, customer)["rewards"] < 1:
            continue
        options = [(line["base_price"], i) for i, line in enumerate(cart)
                   if eligible(p, line) and free_units.get(i, 0) < line["quantity"]]
        if not options:
            continue
        price, i = max(options)
        free_units[i] = free_units.get(i, 0) + 1
        total += price
        used.append(p.id)
        notes.append(f"{p.name} grátis (fidelidade)")
    first = False
    if first_order_eligible(tenant, customer):
        rest = subtotal - total
        v = Decimal(tenant.first_order_value or 0)
        off = rest * v / 100 if tenant.first_order_type == "percent" else v
        off = min(rest, off).quantize(CENT, rounding=ROUND_HALF_UP)
        if off > 0:
            total += off
            notes.append("1º pedido")
            first = True
    return min(total, subtotal), " · ".join(notes), first, used
