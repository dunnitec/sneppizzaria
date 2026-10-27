"""Promoções: quais valem agora e quanto fica cada preço.

Usado pelo cálculo do pedido (pricing.py), pelo cardápio do site e do balcão
(menu_data.py) e pelo painel. Dias e datas seguem o horário da loja.
"""

import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.services.plans import has as has_feature
from app.models import Promotion
from app.services.hours import STORE_TZ
from app.services.money import brl

WEEKDAY_NAMES = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
WEEKDAY_PLURAL = ["domingos", "segundas", "terças", "quartas", "quintas", "sextas", "sábados"]
CENT = Decimal("0.01")


def store_today():
    return datetime.now(STORE_TZ).date()


def _weekday(day):
    return (day.weekday() + 1) % 7  # 0 = domingo, igual ao horário da loja


def status(promo, today=None):
    """(código, texto) para o painel: no_ar, hoje_nao, agendada, encerrada, pausada."""
    today = today or store_today()
    if not promo.active:
        return "pausada", "Pausada"
    if promo.ends_on and today > promo.ends_on:
        return "encerrada", "Encerrada"
    if promo.starts_on and today < promo.starts_on:
        return "agendada", f"Começa em {promo.starts_on.strftime('%d/%m')}"
    days = promo.weekday_list()
    if days and _weekday(today) not in days:
        return "hoje_nao", "Não vale hoje"
    return "no_ar", "No ar agora"


def running(tenant, today=None):
    if not has_feature(tenant, "promocoes"):
        return []
    today = today or store_today()
    promos = Promotion.query.filter_by(tenant_id=tenant.id, active=True).order_by(Promotion.id).all()
    return [p for p in promos if status(p, today)[0] == "no_ar"]


def running_count(tenant):
    """Quantas promoções estão no ar agora (tela Início)."""
    return len(running(tenant))


def applies(promo, category_id, product_id, label):
    if promo.category_id != category_id:
        return False
    ids = promo.product_id_list()
    if ids and product_id not in ids:
        return False
    return not promo.size_label or promo.size_label == label


def discounted(promo, regular):
    regular = Decimal(str(regular))
    if promo.discount_type == "percent":
        price = regular * (100 - Decimal(promo.value)) / 100
    else:
        price = Decimal(promo.value)
    return price.quantize(CENT, rounding=ROUND_HALF_UP)


def best_price(promos, category_id, product_id, label, regular):
    """Menor preço entre as promoções que valem para o item. Devolve (preço, promoção ou None)."""
    regular = Decimal(str(regular)).quantize(CENT)
    best, chosen = regular, None
    for p in promos:
        if applies(p, category_id, product_id, label):
            price = discounted(p, regular)
            if Decimal(0) < price < best:
                best, chosen = price, p
    return best, chosen


def badge(promo):
    if promo.discount_type == "percent":
        return f"-{Decimal(promo.value).normalize():f}%"
    return "PROMOÇÃO"


def _days_text(promo):
    days = promo.weekday_list()
    if not days or len(days) == 7:
        return ""
    names = [WEEKDAY_PLURAL[d] for d in sorted(days, key=lambda d: (d + 6) % 7)]  # segunda primeiro
    return "às " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1])


def target_text(promo):
    """Ex.: “Calabresa e Atum — Pizzas Tradicionais, Grande”."""
    cat = promo.category
    names = [p.name for p in cat.products if p.id in promo.product_id_list()] if cat else []
    where = cat.name if cat else "?"
    if names:
        where = (", ".join(names[:-1]) + " e " + names[-1] if len(names) > 1 else names[0]) + f" ({where})"
    if promo.size_label and cat and cat.kind != "metro":
        where += f", {promo.size_label}"
    return where


def describe(promo):
    """Frase curta para o cliente e para o painel."""
    off = (f"{Decimal(promo.value).normalize():f}% de desconto" if promo.discount_type == "percent"
           else f"por {brl(promo.value)}")
    parts = [f"{target_text(promo)} {off}" if promo.discount_type == "price" else f"{off} em {target_text(promo)}"]
    days = _days_text(promo)
    if days:
        parts.append(days)
    if promo.ends_on:
        parts.append(f"até {promo.ends_on.strftime('%d/%m')}")
    return " · ".join(parts)


def forget_product(tenant_id, product_id):
    """Sabor excluído: tira das promoções que o citavam. Se não sobrar sabor, a promoção é pausada
    (lista vazia significaria “a categoria inteira”)."""
    for p in Promotion.query.filter_by(tenant_id=tenant_id):
        ids = p.product_id_list()
        if product_id in ids:
            ids.remove(product_id)
            if ids:
                p.product_ids = json.dumps(ids)
            else:
                p.active = False
