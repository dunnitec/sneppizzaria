"""Como um item do pedido aparece no cupom, no painel e no WhatsApp.

Pizza com mais de um sabor fica um sabor por linha (“1/2 Frango” / “1/2 Portuguesa”),
e a pizza leva o tipo ao lado (Premium, Promocionais, Doces), tirado da categoria
gravada no item na hora da venda. Pizza Trem (combo) também sai com a fração de cada sabor
(“1/4 Frango” em cada linha). O tamanho da pizza leva os pedaços: Broto (4 pedaços), Inteira (8 pedaços),
ou o que o dono escolheu no tamanho (Cardápio → categoria → Tamanhos).
"""

import re

PIZZA_KINDS = ("pizza", "doce")


def short_type(category_name):
    """'Pizzas Premium' -> 'Premium'; 'Pizza Doce' -> 'Doce'."""
    name = re.sub(r"^pizzas?\s+", "", (category_name or "").strip(), flags=re.I)
    return name or None


def flavor_view(kind, category_name, flavor_names, product_names=""):
    """{head, lines, tag}: primeira linha, linhas dos outros sabores e o tipo da pizza (ou None)."""
    names = [n for n in flavor_names if n]
    if kind == "bebida":
        return {"head": product_names or (names[0] if names else ""), "lines": [], "tag": None}
    if kind == "metro":
        head = category_name or product_names.split(":")[0].strip()
        n = len(names)
        return {"head": head, "lines": [f"1/{n} {x}" for x in names] if n > 1 else names, "tag": None}
    tag = short_type(category_name) if kind in PIZZA_KINDS else None
    if len(names) <= 1:
        return {"head": names[0] if names else product_names, "lines": [], "tag": tag}
    n = len(names)
    return {"head": f"1/{n} {names[0]}", "lines": [f"1/{n} {x}" for x in names[1:]], "tag": tag}


def _names_from_text(item):
    """Pedidos sem os sabores gravados à parte: tira os nomes do texto (“1/2 A + 1/2 B”, “Combo: A + B”)."""
    text = item.product_names or ""
    if item.kind == "metro" and ":" in text:
        text = text.split(":", 1)[1]
    return [re.sub(r"^1/\d+\s+", "", part.strip()) for part in text.split(" + ") if part.strip()]


def item_view(item):
    names = [f.product_name for f in item.flavor_rows] or _names_from_text(item)
    return flavor_view(item.kind, item.category_name, names, item.product_names)


def slices(kind, label, sizes=None):
    """Quantos pedaços tem a pizza neste tamanho (ou None: não mostra).

    sizes: tamanhos da categoria (Category.sizes()); "slices" escolhido pelo dono vale mais
    (0 = não mostrar). Sem escolha: Broto 4, Inteira/Grande 8. Nome que já diz os pedaços fica como está.
    """
    if kind not in PIZZA_KINDS or not label or "pedaç" in label.lower():
        return None
    for s in sizes or []:
        if s.get("label") == label and "slices" in s:
            return int(s["slices"]) or None
    low = label.lower()
    if "broto" in low:
        return 4
    if "inteira" in low or "grande" in low:
        return 8
    return None


def with_slices(label, n):
    return f"{label} ({n} pedaços)" if n else label


def size_text(item):
    """Tamanho do item no cupom: “Broto (4 pedaços)”."""
    from app.extensions import db
    from app.models import Category

    category = db.session.get(Category, item.category_id) if item.category_id else None
    return with_slices(item.variant_label or "", slices(item.kind, item.variant_label, category.sizes() if category else None))
