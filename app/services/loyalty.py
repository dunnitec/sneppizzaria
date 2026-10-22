"""Fidelidade (selos) e desconto no 1º pedido — só para quem tem cadastro no site.

Selos: cada pizza dos tipos escolhidos pelo dono (Tenant.loyalty_kinds) vale 1
selo, contando os pedidos confirmados depois do cadastro (inclusive os feitos
por telefone no balcão, que caem no mesmo cliente pelo número). A cada
Tenant.loyalty_goal selos o cliente ganha 1 pizza grátis da categoria/tamanho
escolhidos pelo dono. A pizza usada como prêmio não gera selo. Pedido cancelado
não conta selo e devolve o prêmio.

1º pedido: quem se cadastra e ainda não tem nenhum pedido (cancelados não
contam) ganha o desconto do Tenant.first_order_*.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import SOLD_STATUSES, Category, Order, OrderItem

CENT = Decimal("0.01")
KIND_NAMES = {"pizza": "Pizzas salgadas", "doce": "Pizzas doces", "metro": "Combos"}


def kinds(tenant):
    return [k for k in (tenant.loyalty_kinds or "").split(",") if k in KIND_NAMES]


def reward_category(tenant):
    if not tenant.loyalty_reward_category_id:
        return None
    return Category.query.filter_by(tenant_id=tenant.id, id=tenant.loyalty_reward_category_id).first()


def reward_text(tenant):
    cat = reward_category(tenant)
    if not cat:
        return "1 pizza grátis"
    what = cat.name.replace("Pizzas ", "").replace("Pizza ", "")
    return f"1 pizza {what}{' ' + tenant.loyalty_reward_size if tenant.loyalty_reward_size else ''} grátis"


def is_active(tenant):
    return bool(tenant.loyalty_enabled and tenant.loyalty_goal and kinds(tenant) and reward_category(tenant))


def stamps(tenant, customer):
    """Selos já ganhos (pizzas confirmadas desde o cadastro, menos as pizzas-prêmio)."""
    if not customer or not customer.registered_at or not kinds(tenant):
        return 0
    sold = Order.query.filter(Order.customer_id == customer.id, Order.status.in_(SOLD_STATUSES),
                              Order.created_at >= customer.registered_at)
    pizzas = (db.session.query(func.coalesce(func.sum(OrderItem.quantity), 0))
              .join(Order).filter(Order.id.in_(sold.with_entities(Order.id)), OrderItem.kind.in_(kinds(tenant)))
              .scalar())
    used_as_reward = sold.filter(Order.loyalty_reward.is_(True)).count()
    return max(0, int(pizzas) - used_as_reward)


def rewards_used(customer):
    """Prêmios usados (pedido pendente também segura o prêmio; cancelado devolve)."""
    return Order.query.filter(Order.customer_id == customer.id, Order.loyalty_reward.is_(True),
                              Order.status != "cancelado").count()


def card(tenant, customer):
    """Cartão de selos para o site: {goal, filled, rewards, total_stamps}."""
    goal = tenant.loyalty_goal or 8
    total = stamps(tenant, customer)
    earned = total // goal
    available = max(0, earned - rewards_used(customer)) if customer else 0
    return {"goal": goal, "filled": total % goal, "rewards": available, "total_stamps": total,
            "reward_text": reward_text(tenant)}


def first_order_eligible(tenant, customer):
    if not tenant.first_order_enabled or not customer or not customer.registered_at:
        return False
    return not Order.query.filter(Order.customer_id == customer.id, Order.status != "cancelado").first()


def first_order_text(tenant):
    v = Decimal(tenant.first_order_value or 0)
    if tenant.first_order_type == "percent":
        return f"{v.normalize():f}% de desconto no 1º pedido"
    return f"R$ {v:.2f}".replace(".", ",") + " de desconto no 1º pedido"


def discounts(tenant, customer, cart, use_reward):
    """Descontos do pedido do site. Devolve (valor, observação, é_1º_pedido, usou_prêmio)."""
    subtotal = sum((line["line_total"] for line in cart), Decimal("0"))
    total, notes, first, reward = Decimal("0"), [], False, False
    if use_reward and customer and is_active(tenant) and card(tenant, customer)["rewards"] > 0:
        cat = reward_category(tenant)
        eligible = [line for line in cart if line.get("category_id") == cat.id
                    and (not tenant.loyalty_reward_size or line["variant_label"] == tenant.loyalty_reward_size)]
        if eligible:
            best = max(line["base_price"] for line in eligible)
            total += best
            notes.append("Pizza grátis da fidelidade")
            reward = True
    if first_order_eligible(tenant, customer):
        rest = subtotal - total
        v = Decimal(tenant.first_order_value or 0)
        off = rest * v / 100 if tenant.first_order_type == "percent" else v
        off = min(rest, off).quantize(CENT, rounding=ROUND_HALF_UP)
        if off > 0:
            total += off
            notes.append("1º pedido")
            first = True
    return min(total, subtotal), " · ".join(notes), first, reward
