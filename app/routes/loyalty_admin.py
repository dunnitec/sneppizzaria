"""Painel: cartões fidelidade, desconto do 1º pedido e senha nova do cliente."""

import json
import secrets
from decimal import Decimal, InvalidOperation

from flask import flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Category, Customer, LoyaltyProgram
from app.routes.admin import FormError, _name, _reject, _save, admin_bp
from app.services.loyalty import card, first_order_text, flavor_names, is_ready, programs, reward_text

MAX_GOAL = 30


def _categories():
    return Category.query.filter(Category.tenant_id == g.tenant.id, Category.kind != "bebida") \
        .order_by(Category.sort_order, Category.id).all()


def _program_or_404(program_id):
    return LoyaltyProgram.query.filter_by(tenant_id=g.tenant.id, id=program_id).first_or_404()


def _missing(p):
    """O que falta para o cartão aparecer no site (texto para o dono)."""
    if not p.active:
        return "Desligado: não aparece no site."
    falta = []
    if not p.counted():
        falta.append("as categorias que valem selo")
    if not p.reward_category_id:
        falta.append("a pizza do prêmio")
    if not p.reward_products():
        falta.append("os sabores que o cliente pode escolher no prêmio")
    return "Falta escolher " + ", ".join(falta) + "." if falta else ""


def _fill(p, form, cats):
    p.name = _name(form.get("name"), "o nome do cartão (ex.: Promocional)", max_length=40)
    p.active = "active" in form
    try:
        p.goal = int(form.get("goal", ""))
    except ValueError:
        p.goal = 0
    if not 2 <= p.goal <= MAX_GOAL:
        raise FormError(f"{p.name}: o número de pizzas vai de 2 a {MAX_GOAL}.")
    by_id = {c.id: c for c in cats}
    counted = [int(x) for x in form.getlist("counted") if x.isdigit() and int(x) in by_id]
    # uma categoria só pode dar selo em um cartão, senão a mesma pizza contaria duas vezes
    for other in LoyaltyProgram.query.filter(LoyaltyProgram.tenant_id == g.tenant.id, LoyaltyProgram.id != (p.id or 0)):
        clash = [by_id[c].name for c in counted if c in other.counted()]
        if clash:
            raise FormError(f"{', '.join(clash)} já vale selo no cartão “{other.name}”. Cada categoria conta em um cartão só.")
    p.count_category_ids = json.dumps(counted)
    reward = by_id.get(form.get("reward_category", type=int))
    if reward and reward.kind == "metro":
        reward = None
    p.reward_category_id = reward.id if reward else None
    size = form.get(f"reward_size-{reward.id}", "") if reward else ""
    if reward and size and size not in [s["label"] for s in reward.sizes()]:
        raise FormError("Tamanho do prêmio inválido. Atualize a página.")
    p.reward_size = size or None
    valid = {x.id for x in reward.products} if reward else set()
    flavors = [int(x) for x in form.getlist(f"flavors-{reward.id}") if x.isdigit() and int(x) in valid] if reward else []
    p.reward_product_ids = json.dumps(flavors)
    if p.active and _missing(p):
        raise FormError(f"{p.name}: {_missing(p)} Ou desmarque “Cartão ligado” para salvar sem ligar.")


@admin_bp.route("/fidelidade")
def loyalty():
    t = g.tenant
    rows = LoyaltyProgram.query.filter_by(tenant_id=t.id).order_by(LoyaltyProgram.sort_order, LoyaltyProgram.id).all()
    registered = Customer.query.filter(Customer.tenant_id == t.id, Customer.registered_at.isnot(None)).count()
    cards_info = [{"p": p, "ready": is_ready(p), "missing": _missing(p), "reward": reward_text(p),
                   "flavors": flavor_names(p)} for p in rows]
    return render_template("admin/loyalty.html", rows=cards_info, cats=_categories(), registered=registered,
                           first_text=first_order_text(t), max_goal=MAX_GOAL)


@admin_bp.route("/fidelidade/cartao/novo", methods=["POST"])
@admin_bp.route("/fidelidade/cartao/<int:program_id>", methods=["POST"])
def loyalty_program_save(program_id=None):
    p = _program_or_404(program_id) if program_id else LoyaltyProgram(tenant_id=g.tenant.id, sort_order=99)
    try:
        _fill(p, request.form, _categories())
        if not program_id:
            db.session.add(p)
        _save(f"Cartão “{p.name}” salvo." + (" Já aparece no site." if is_ready(p) else ""))
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.loyalty"))


@admin_bp.route("/fidelidade/cartao/<int:program_id>/excluir", methods=["POST"])
def loyalty_program_delete(program_id):
    p = _program_or_404(program_id)
    name = p.name
    db.session.delete(p)
    db.session.commit()
    flash(f"Cartão “{name}” excluído. Os pedidos continuam no histórico.", "ok")
    return redirect(url_for("admin.loyalty"))


@admin_bp.route("/fidelidade/primeiro-pedido", methods=["POST"])
def loyalty_first_order():
    t, form = g.tenant, request.form
    try:
        t.first_order_enabled = "first_order_enabled" in form
        t.first_order_type = "amount" if form.get("first_order_type") == "amount" else "percent"
        try:
            value = Decimal(form.get("first_order_value", "").replace(",", ".").replace("%", "").strip())
        except InvalidOperation:
            value = Decimal(0)
        if t.first_order_type == "percent" and not 1 <= value <= 50:
            raise FormError("1º pedido: o desconto vai de 1% a 50%.")
        if t.first_order_type == "amount" and not 1 <= value <= 200:
            raise FormError("1º pedido: o desconto vai de R$ 1,00 a R$ 200,00.")
        t.first_order_value = value.quantize(Decimal("0.01"))
        _save("Desconto do 1º pedido salvo.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.loyalty"))


@admin_bp.route("/clientes/<int:customer_id>/senha", methods=["POST"])
def customer_new_pin(customer_id):
    """Cliente esqueceu a senha: gera uma de 6 números para o dono mandar pelo WhatsApp."""
    c = Customer.query.filter_by(tenant_id=g.tenant.id, id=customer_id).first_or_404()
    if not c.registered_at:
        flash(f"{c.name} ainda não tem cadastro no site.", "error")
        return redirect(url_for("admin.customers"))
    from app.routes.account import weak_pin

    pin = f"{secrets.randbelow(10 ** 6):06d}"
    while weak_pin(pin):
        pin = f"{secrets.randbelow(10 ** 6):06d}"
    c.set_pin(pin)
    c.failed_attempts, c.locked_until = 0, None
    db.session.commit()
    flash(f"Senha nova de {c.name}: {pin}. Mande para o cliente pelo WhatsApp; ele pode trocar depois em “Minha conta”.", "ok")
    return redirect(url_for("admin.customers", q=c.phone_key))


def loyalty_cards(customer):
    """Para a lista de clientes: um cartão por programa ligado."""
    return [card(p, customer) for p in programs(g.tenant)] if customer.registered_at else []
