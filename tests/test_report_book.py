"""Relatórios separados: custos (CMV), lucro real, curva ABC, fechamento do dia e a aba Custos."""
import json
from decimal import Decimal

from app.extensions import db
from app.models import Border, Category, Expense, Order, OrderItem, Product
from app.services import report_book as book
from app.services.costs import Menu, card_fee, cost_of, fee_rates
from tests.test_admin import admin, panel  # noqa: F401
from tests.test_finance import today
from tests.test_pos import paulista_price, pizza
from tests.test_pos import post as pos_post


def post(client, **data):
    r = pos_post(client, channel="balcao", **data)
    assert r.status_code == 200, r.json
    return r


def paulista():
    p = Product.query.filter_by(name="Paulista").one()
    return p, next(v for v in p.variants if v.label == "Inteira")


def premium():
    return Category.query.filter_by(slug="premium").one()


# ---------- custo do item ----------

def test_cost_from_value_then_from_line_percent(tenant):
    p, v = paulista()
    menu = Menu(tenant)
    assert cost_of(menu, premium().id, "Inteira", [(p.id, 1)]) is None  # nada cadastrado
    premium().cost_percent = Decimal("30")
    db.session.commit()
    menu = Menu(tenant)
    assert cost_of(menu, premium().id, "Inteira", [(p.id, 1)]) == (v.price * Decimal("0.3")).quantize(Decimal("0.01"))
    v.cost = Decimal("18.00")
    db.session.commit()
    assert cost_of(Menu(tenant), premium().id, "Inteira", [(p.id, 1)]) == Decimal("18.00")


def test_half_and_half_sums_each_half_and_border(tenant):
    p, v = paulista()
    other = next(x for x in premium().products if x.id != p.id)
    ov = next(x for x in other.variants if x.label == "Inteira")
    v.cost, ov.cost = Decimal("20"), Decimal("10")
    border = Border.query.first()
    border.cost = Decimal("4")
    db.session.commit()
    name = f"{border.group_name.replace('Borda ', '')} - {border.name}"[:60]
    menu = Menu(tenant)
    assert cost_of(menu, premium().id, "Inteira", [(p.id, Decimal("0.5")), (other.id, Decimal("0.5"))], name) == Decimal("19.00")


def test_order_keeps_cost_of_the_sale(panel, tenant):
    _, v = paulista()
    v.cost = Decimal("21.50")
    db.session.commit()
    post(panel, items=[pizza(qty=2)])
    item = OrderItem.query.order_by(OrderItem.id.desc()).first()
    assert item.unit_cost == Decimal("21.50")
    v.cost = Decimal("30")  # mudar o custo depois não muda a venda já feita
    db.session.commit()
    assert book.profit(tenant, today(), today())["cmv"] == Decimal("43.00")


# ---------- taxa da maquininha ----------

def test_card_fee_by_payment_method(tenant):
    tenant.payment_fees = json.dumps({"Crédito": 3.5, "Débito": 2})
    db.session.commit()
    rates = fee_rates(tenant)
    assert card_fee(rates, "Crédito", Decimal("100")) == Decimal("3.50")
    assert card_fee(rates, "Débito", Decimal("50")) == Decimal("1.00")
    assert card_fee(rates, "Dinheiro", Decimal("50")) == Decimal("0")


# ---------- lucro real ----------

def test_profit_with_costs_fees_and_expenses(panel, tenant):
    _, v = paulista()
    v.cost = Decimal("20")
    tenant.payment_fees = json.dumps({"Crédito": 5})
    db.session.commit()
    post(panel, payment_method="Crédito", items=[pizza()])
    price = paulista_price()
    db.session.add_all([Expense(tenant_id=tenant.id, day=today(), category="aluguel", amount=Decimal("10")),
                        Expense(tenant_id=tenant.id, day=today(), category="mercado", amount=Decimal("99"))])
    db.session.commit()
    p = book.profit(tenant, today(), today())
    fee = (price * Decimal("0.05")).quantize(Decimal("0.01"))
    assert p["mode"] == "ficha"
    assert (p["sold"], p["card_fees"], p["cmv"]) == (price, fee, Decimal("20.00"))
    assert p["gross_profit"] == price - fee - 20
    # mercado não entra de novo nos gastos: o custo da pizza já está no CMV
    assert p["operating_total"] == Decimal("10")
    assert p["purchases"] == Decimal("99")
    assert p["net"] == price - fee - 20 - 10
    assert round(p["markup"], 2) == round(float(price / 20), 2)


def test_without_costs_purchases_become_the_product_cost(panel, tenant):
    post(panel, items=[pizza()])
    db.session.add(Expense(tenant_id=tenant.id, day=today(), category="mercado", amount=Decimal("15")))
    db.session.commit()
    p = book.profit(tenant, today(), today())
    assert p["mode"] == "compras"
    assert p["cmv"] == Decimal("15")
    assert p["operating_total"] == 0
    assert p["markup"] is None


# ---------- produtos e fechamento ----------

def test_products_abc_curve(panel, tenant):
    post(panel, items=[pizza(qty=5)])
    p = Product.query.filter(Product.name != "Paulista", Product.category_id == premium().id).first()
    post(panel, items=[{"category_id": premium().id, "variant": "Inteira", "flavors": [p.id], "quantity": 1}])
    pr = book.products(tenant, today(), today())
    assert pr["rows"][0]["name"] == "Paulista" and pr["rows"][0]["cls"] == "A"
    assert pr["rows"][-1]["cls"] in ("B", "C")
    assert pr["total"] == sum(r["sales"] for r in pr["rows"])


def test_closing_shows_cash_in_drawer_and_what_was_left(panel, tenant):
    post(panel, payment_method="Dinheiro", items=[pizza()])
    post(panel, payment_method="Pix", items=[pizza()])
    db.session.add(Expense(tenant_id=tenant.id, day=today(), category="gas", amount=Decimal("30")))
    db.session.commit()
    c = book.closing(tenant, today())
    price = paulista_price()
    assert c["cash_in"] == price
    assert c["sold"] == 2 * price
    assert c["paid_out"] == Decimal("30")
    assert c["left"] == 2 * price - 30
    assert {r["label"] for r in c["by_payment"]} == {"Dinheiro", "Pix"}


# ---------- telas ----------

def test_every_report_opens_and_downloads(panel, tenant):
    post(panel, items=[pizza()])
    for kind in ("resumo", "fechamento", "lucro", "produtos", "vendas", "pagamentos", "clientes", "entregas",
                 "gastos", "cancelados"):
        r = panel.get(f"/snep/admin/relatorios?tipo={kind}")
        assert r.status_code == 200, kind
        assert "Baixar planilha" in r.get_data(as_text=True), kind
        csv = panel.get(f"/snep/admin/relatorios?tipo={kind}&formato=csv")
        assert csv.status_code == 200 and csv.mimetype == "text/csv", kind


def test_closing_picks_any_day(panel):
    html = panel.get("/snep/admin/relatorios?tipo=fechamento&dia=2026-01-05").get_data(as_text=True)
    assert "5 de janeiro de 2026" in html and 'value="2026-01-05"' in html


def test_home_shows_todays_closing(panel):
    post(panel, payment_method="Dinheiro", items=[pizza()])
    html = panel.get("/snep/admin/").get_data(as_text=True)
    assert "Fechamento de hoje" in html and "Dinheiro na gaveta" in html


def test_costs_page_saves_values_percent_and_fees(panel, tenant):
    _, v = paulista()
    border = Border.query.first()
    r = panel.post("/snep/admin/custos", data={
        f"cost-{v.id}": "22,40", f"pct-{premium().id}": "35", f"bcost-{border.id}": "3,00",
        "fee-Crédito": "3,49", "fee-Débito": ""}, follow_redirects=True)
    assert "Custos salvos" in r.get_data(as_text=True)
    db.session.expire_all()
    assert v.cost == Decimal("22.40") and premium().cost_percent == Decimal("35") and border.cost == Decimal("3")
    assert fee_rates(tenant) == {"Crédito": Decimal("3.49")}


def test_costs_page_rejects_nonsense(panel):
    r = panel.post("/snep/admin/custos", data={"fee-Crédito": "80"}, follow_redirects=True)
    assert "Confira a taxa do Crédito" in r.get_data(as_text=True)


def test_accounts_and_team_have_a_day_picker(panel):
    for url in ("/snep/admin/contas?dia=2026-10-01", "/snep/admin/equipe?dia=2026-10-01"):
        html = panel.get(url).get_data(as_text=True)
        assert 'type="date" name="dia" value="2026-10-01"' in html, url
