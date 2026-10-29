"""Calcula o preço de um item do pedido a partir do banco.

O navegador só informa O QUE foi escolhido (categoria, tamanho, sabores,
borda, adicionais). Qualquer preço enviado por ele é ignorado, então adulterar
a página não muda o valor que chega para a loja.

Regras: meio a meio cobra o sabor mais caro; o combo (kind="metro") tem preço
fixo, sabores só das linhas que o dono escolheu e não leva borda paga;
adicionais só nas categorias com allows_addons, no máximo MAX_ADDONS por pizza.
Promoções no ar (services/promotions.py) baixam o preço do sabor/tamanho antes
dessas regras; borda e adicionais não entram no desconto.
"""

import re
from decimal import Decimal

from app.models import Addon, Border, Category, Product
from app.services.promotions import best_price, running

MAX_ADDONS = 5
MAX_QUANTITY = 50
# adicional tem preço de pizza pequena (price_half) e de inteira (price_whole); qualquer tamanho que não
# seja pequeno (Broto, Pequena, Mini, Individual) paga o de inteira — Grande, Gigante, Família...
SMALL_PIZZA = re.compile(r"broto|pequen|mini|individual|meia", re.I)


class OrderError(ValueError):
    """Item inválido; a mensagem é exibida ao cliente."""


def _int(value, error):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise OrderError(error)
    try:
        return int(value)
    except ValueError:
        raise OrderError(error) from None


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _flavors(raw, query):
    ids = raw.get("flavors")
    if not isinstance(ids, list) or not ids:
        raise OrderError("Escolha o sabor da pizza.")
    by_id = {p.id: p for p in query.filter(Product.id.in_([_int(i, "Sabor inválido.") for i in ids]))}
    try:
        return [by_id[int(i)] for i in ids]
    except KeyError:
        raise OrderError("Um dos sabores escolhidos não está mais disponível. Atualize a página.") from None


def _border(tenant, raw):
    if raw.get("border_id") in (None, ""):
        return None
    border = Border.query.filter_by(
        tenant_id=tenant.id, id=_int(raw["border_id"], "Borda inválida."), active=True
    ).first()
    if not border:
        raise OrderError("A borda escolhida não está mais disponível. Atualize a página.")
    return border


def _addons(tenant, category, raw):
    chosen = raw.get("addons") or []
    if not chosen:
        return []
    if not category.allows_addons or not isinstance(chosen, list):
        raise OrderError("Esta pizza não aceita adicionais.")
    result = []
    for entry in chosen:
        if not isinstance(entry, dict):
            raise OrderError("Adicional inválido.")
        qty = _int(entry.get("qty"), "Adicional inválido.")
        if qty < 1:
            raise OrderError("Adicional inválido.")
        addon = Addon.query.filter_by(
            tenant_id=tenant.id, id=_int(entry.get("id"), "Adicional inválido."), active=True
        ).first()
        if not addon:
            raise OrderError("Um dos adicionais não está mais disponível. Atualize a página.")
        result.append((addon, qty))
    if sum(qty for _, qty in result) > MAX_ADDONS:
        raise OrderError(f"Escolha no máximo {MAX_ADDONS} adicionais por pizza.")
    return result


def price_item(tenant, raw):
    """Valida um item vindo do navegador e devolve a linha do pedido já precificada."""
    if not isinstance(raw, dict):
        raise OrderError("Item inválido.")
    quantity = _int(raw.get("quantity", 1), "Quantidade inválida.")
    if not 1 <= quantity <= MAX_QUANTITY:
        raise OrderError("Quantidade inválida.")

    category = Category.query.filter_by(
        tenant_id=tenant.id, id=_int(raw.get("category_id"), "Item inválido.")
    ).first()
    if not category:
        raise OrderError("Item inválido. Atualize a página.")
    promos = running(tenant)
    applied = []  # nomes das promoções que baixaram o preço deste item

    if category.kind == "metro":
        combo = next((p for p in category.products if p.active and p.variants), None)
        variant = next((v for v in combo.variants if v.active), None) if combo else None
        if not variant:  # desligado no estoque com o site já aberto no celular do cliente
            raise OrderError("Este item não está mais disponível. Atualize a página.")
        settings = category.combo_settings()
        pool = Product.query.join(Category).filter(
            Product.tenant_id == tenant.id,
            Product.active.is_(True),
            Category.slug.in_(settings["sources"]),
            Category.kind.notin_(("metro", "bebida")),
        )
        flavors = _flavors(raw, pool)
        label, max_flavors = variant.label, variant.max_flavors
        price, promo = best_price(promos, category.id, combo.id, label, variant.price)
        if promo:
            applied.append(promo.name)
        title = f"{category.name}: " + " + ".join(p.name for p in flavors)
        if raw.get("border_id") not in (None, ""):
            raise OrderError("O combo não aceita borda adicional.")
        extras = list(settings["extras"])
        if settings["choice_options"]:
            choice = str(raw.get("combo_choice") or "")
            if choice not in settings["choice_options"]:
                raise OrderError(f"Escolha: {settings['choice_label'] or 'opção do combo'}.")
            extras.append(f"{settings['choice_label'] or 'Escolha'}: {choice}")
    else:
        label = str(raw.get("variant") or "")
        flavors = _flavors(raw, Product.query.filter_by(category_id=category.id, active=True))
        variants = [next((v for v in p.variants if v.label == label and v.active), None) for p in flavors]
        if not all(variants):
            raise OrderError("Tamanho indisponível para o sabor escolhido. Atualize a página.")
        if category.kind == "bebida" and (len(flavors) != 1 or raw.get("border_id") not in (None, "")):
            raise OrderError("Bebida inválida. Atualize a página.")
        max_flavors = max(v.max_flavors for v in variants)
        # meio a meio cobra o sabor mais caro, já com o desconto de cada sabor
        prices = [best_price(promos, category.id, p.id, label, v.price) for p, v in zip(flavors, variants)]
        price = max(pr for pr, _ in prices)
        if price < max(_money(v.price) for v in variants):
            applied += [promo.name for _, promo in prices if promo]
        extras = []
        n = len(flavors)
        title = flavors[0].name if n == 1 else " + ".join(f"1/{n} {p.name}" for p in flavors)

    if len(flavors) > max_flavors:
        raise OrderError(f"Este tamanho aceita no máximo {max_flavors} sabor(es).")

    base_price = price  # sabor/tamanho já com promoção, sem borda e adicionais (prêmio da fidelidade)
    border = _border(tenant, raw)
    no_border = next((p for p in flavors if not p.accepts_border), None)
    if border and no_border:
        raise OrderError(f"{no_border.name} não aceita borda. Tire a borda e envie de novo.")
    if border and not border.allowed_for(category.slug, label):
        raise OrderError(f"A borda {border.group_name} não está disponível para {label}. Escolha outra borda.")
    if border:
        price += _money(border.price)

    addons = _addons(tenant, category, raw)
    whole = not SMALL_PIZZA.search(label)
    for addon, qty in addons:
        price += qty * _money(addon.price_whole if whole else addon.price_half)

    return {
        "product_names": title[:255],
        "variant_label": label,
        "border_name": f"{re.sub(r'^Borda ', '', border.group_name)} - {border.name}"[:60] if border else "",
        "addon_names": ", ".join(f"{qty}x {addon.name}" for addon, qty in addons)[:255],
        "extras": ", ".join(extras)[:255],
        "promo_name": " + ".join(dict.fromkeys(applied))[:120],
        "kind": category.kind,
        "category_id": category.id,
        "category_name": category.name,
        "base_price": base_price,
        # combo: cada sabor é 1/n da pizza; meio a meio: 1/n de cada
        "flavors": [(p, Decimal(1) / len(flavors)) for p in flavors],
        "notes": str(raw.get("notes") or "").strip()[:255],
        "unit_price": price,
        "quantity": quantity,
        "line_total": price * quantity,
    }
