"""Cupom de desconto: o dono cria em Cupons; o cliente pega na vitrine do site ou digita o código no pagamento.

Vale só no site. O desconto é calculado aqui no servidor, sobre os itens (sem a entrega) e depois da pizza
grátis da fidelidade. Não junta com o desconto do 1º pedido: vale o maior dos dois.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from app.extensions import db
from app.models import Coupon, Customer, Order
from app.services.hours import work_day
from app.services.money import brl
from app.services.plans import has as has_feature
from app.services.pricing import OrderError

CENT = Decimal("0.01")


def normalize(text):
    """Código como é guardado: só letras e números, em maiúsculas (“sextou 10” → “SEXTOU10”)."""
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())[:20]


def uses(coupon):
    """Quantas vezes já foi usado (pedido cancelado devolve o uso)."""
    return Order.query.filter(Order.coupon_id == coupon.id, Order.status != "cancelado").count()


def status(coupon, today):
    """(código, texto): ok | pausado | antes | vencido | esgotado."""
    if not coupon.active:
        return "pausado", "Pausado"
    if coupon.starts_on and today < coupon.starts_on:
        return "antes", f"Começa em {coupon.starts_on:%d/%m}"
    if coupon.ends_on and today > coupon.ends_on:
        return "vencido", "Vencido"
    if coupon.max_uses is not None and uses(coupon) >= coupon.max_uses:
        return "esgotado", "Esgotado"
    return "ok", "Valendo"


def describe(coupon):
    """Texto para o cliente: “10% de desconto · pedido mínimo R$ 50,00 · até 30/11”."""
    if coupon.discount_type == "percent":
        value = f"{Decimal(coupon.value).normalize():f}".replace(".", ",") + "%"
    else:
        value = brl(coupon.value)
    parts = [f"{value} de desconto"]
    if coupon.min_order:
        parts.append(f"pedido mínimo {brl(coupon.min_order)}")
    if coupon.ends_on:
        parts.append(f"até {coupon.ends_on:%d/%m}")
    return " · ".join(parts)


def public(coupon):
    """O que o navegador recebe (o desconto mostrado na tela é só uma prévia: quem calcula é o servidor)."""
    return {"code": coupon.code, "title": coupon.title or describe(coupon), "text": describe(coupon),
            "type": coupon.discount_type, "value": float(coupon.value),
            "min_order": float(coupon.min_order) if coupon.min_order else 0}


def showcase(tenant):
    """Cupons da vitrine do site: só os que estão valendo agora."""
    if not has_feature(tenant, "promocoes"):
        return []
    today = work_day(tenant)
    rows = Coupon.query.filter_by(tenant_id=tenant.id, show_on_site=True, active=True).order_by(Coupon.id.desc()).all()
    return [public(c) for c in rows if status(c, today)[0] == "ok"]


def check(tenant, code, subtotal, phone_key=None):
    """Devolve o cupom, ou levanta OrderError com a mensagem para o cliente."""
    code = normalize(code)
    coupon = Coupon.query.filter_by(tenant_id=tenant.id, code=code).first() if code and has_feature(tenant, "promocoes") else None
    if not coupon or not coupon.active:
        raise OrderError("Cupom não encontrado. Confira o código.")
    state, _ = status(coupon, work_day(tenant))
    if state == "antes":
        raise OrderError(f"O cupom {code} só vale a partir de {coupon.starts_on:%d/%m}.")
    if state == "vencido":
        raise OrderError(f"O cupom {code} venceu em {coupon.ends_on:%d/%m}.")
    if state == "esgotado":
        raise OrderError(f"O cupom {code} já esgotou.")
    if coupon.min_order and subtotal < coupon.min_order:
        raise OrderError(f"O cupom {code} vale para pedidos a partir de {brl(coupon.min_order)} (sem a entrega).")
    if coupon.per_customer and phone_key:
        customer = Customer.query.filter_by(tenant_id=tenant.id, phone_key=phone_key).first()
        if customer and db.session.query(Order.id).filter(
                Order.coupon_id == coupon.id, Order.customer_id == customer.id, Order.status != "cancelado").first():
            raise OrderError(f"Você já usou o cupom {code}. Ele vale uma vez por cliente.")
    return coupon


def amount_off(coupon, rest):
    """Desconto sobre `rest` (itens menos a pizza grátis), sem passar dele."""
    value = Decimal(coupon.value)
    off = rest * value / 100 if coupon.discount_type == "percent" else value
    return max(Decimal("0"), min(rest, off)).quantize(CENT, rounding=ROUND_HALF_UP)
