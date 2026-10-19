from decimal import Decimal

from app.services.money import brl, money_input, parse_money


def test_brl_uses_thousands_dot():
    assert brl(Decimal("17275.4")) == "R$ 17.275,40"
    assert brl(1234567.891) == "R$ 1.234.567,89"
    assert brl(65.5) == "R$ 65,50"
    assert brl(None) == "R$ 0,00"


def test_money_input_stays_plain_for_form_fields():
    assert money_input(Decimal("17275.4")) == "17275,40"
    assert parse_money("17.275,40") == Decimal("17275.40")
