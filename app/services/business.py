"""Tipo de loja (Loja → Dados): pizzaria, lanchonete, açaí, restaurante, doceria ou outro.

O tipo só muda palavras (o que aparece no fechamento, nos relatórios e na sugestão de nova categoria).
O que a loja vende é definido pelas categorias, e qualquer loja pode ter qualquer tipo de categoria:
    pizza / doce  — sabores por tamanho, meio a meio, borda e adicionais
    lanche        — item com preço por tamanho (ou preço único) e adicionais: lanche, porção, prato, salgado
    montar        — “monte o seu”: tamanho + complementos grátis (até N) + extras pagos: açaí, marmita, salada
    bebida        — só o tamanho
    metro         — combo de preço fixo
"""

TYPES = {
    "pizzaria": {"label": "Pizzaria", "sold": "Pizzas vendidas", "plural": "Pizzas", "main_kind": "pizza"},
    "lanchonete": {"label": "Lanchonete / Hamburgueria", "sold": "Lanches vendidos", "plural": "Lanches",
                   "main_kind": "lanche"},
    "acai": {"label": "Açaí / Sorveteria", "sold": "Açaís vendidos", "plural": "Açaís", "main_kind": "montar"},
    "restaurante": {"label": "Restaurante / Marmitaria", "sold": "Pratos vendidos", "plural": "Pratos",
                    "main_kind": "lanche"},
    "doceria": {"label": "Doceria / Confeitaria", "sold": "Doces vendidos", "plural": "Doces", "main_kind": "lanche"},
    "outro": {"label": "Outro tipo de comida", "sold": "Itens vendidos", "plural": "Itens", "main_kind": "lanche"},
}
DEFAULT = "pizzaria"
# o que conta como “item principal” no fechamento e nos relatórios (tudo menos bebida)
MAIN_KINDS = ("pizza", "doce", "metro", "lanche", "montar")
PIZZA_KINDS = ("pizza", "doce")  # meio a meio e borda
SINGLE_KINDS = ("lanche", "montar")  # um item por vez, sem sabores para misturar
MAX_PICKS = 20  # complementos grátis por tamanho no “monte o seu”


def biz(tenant):
    """Palavras do tipo da loja: {"key", "label", "sold", "plural", "main_kind"}."""
    key = tenant.business_type if tenant is not None and tenant.business_type in TYPES else DEFAULT
    return {"key": key, **TYPES[key]}


def kind_order(tenant):
    """Tipos de categoria na tela “Nova categoria”, o principal da loja primeiro."""
    main = biz(tenant)["main_kind"]
    base = ["pizza", "doce", "lanche", "montar", "bebida"]
    return [main] + [k for k in base if k != main]
