"""Dividir a conta: partes iguais, todos pagam com a mesma forma de pagamento do pedido.

Os centavos que não dividem certo ficam nas primeiras partes (R$ 100,00 em 3 = 33,34 + 33,33 + 33,33),
para a soma das partes ser sempre o total. O site e o PDV fazem a mesma conta (splitParts).
"""
from decimal import Decimal

from app.services.money import brl

MAX_PEOPLE = 10


def people(value):
    """Quantas pessoas vão dividir: 2 a MAX_PEOPLE; qualquer outra coisa = não divide (None)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 2 <= n <= MAX_PEOPLE else None


def parts(total, n):
    cents = int((Decimal(str(total or 0)) * 100).quantize(Decimal("1")))
    base, extra = divmod(cents, n)
    return [Decimal(base + 1) / 100] * extra + [Decimal(base) / 100] * (n - extra)


def groups(total, n):
    """Partes agrupadas por valor: [(1, 33.34), (2, 33.33)] ou [(4, 25.00)]."""
    ps = parts(total, n)
    extra = sum(1 for p in ps if p != ps[-1])
    return ([(extra, ps[0])] if extra else []) + [(n - extra, ps[-1])]


def describe(total, n):
    """'3 pessoas: R$ 25,00 cada' ou '3 pessoas: 1 de R$ 33,34 e 2 de R$ 33,33'."""
    g = groups(total, n)
    if len(g) == 1:
        return f"{n} pessoas: {brl(g[0][1])} cada"
    return f"{n} pessoas: " + " e ".join(f"{count} de {brl(value)}" for count, value in g)
