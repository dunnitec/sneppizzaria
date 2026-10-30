"""Leitura de valores em reais digitados no painel."""

import re
from decimal import Decimal

MAX_VALUE = Decimal("99999.99")
# "65", "65,5", "65.90" ou, com separador de milhar, "1.234,56"
_FORMAT = re.compile(r"^(\d{1,3}(\.\d{3})+,\d{1,2}|\d+([.,]\d{1,2})?)$")


def parse_money(text):
    """Converte o texto em Decimal com 2 casas. Levanta ValueError se não for um valor válido.

    "1.234" é recusado de propósito: não dá para saber se é mil ou um real e vinte e três.
    """
    s = str(text or "").replace("R$", "").replace(" ", "")
    if not _FORMAT.match(s):
        raise ValueError(f"valor inválido: {text!r}")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    value = Decimal(s).quantize(Decimal("0.01"))
    if value > MAX_VALUE:
        raise ValueError(f"valor alto demais: {text!r}")
    return value


def brl(value):
    """65.5 -> 'R$ 65,50'; 17275.4 -> 'R$ 17.275,40'"""
    value = Decimal(str(value or 0))
    text = "R$ " + f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return "-" + text if value < 0 else text  # -R$ 250,00 (sobrou negativo na aba Contas)


def money_input(value):
    """65.5 -> '65,50' (formato usado nos campos do painel)"""
    return f"{Decimal(str(value or 0)):.2f}".replace(".", ",")
