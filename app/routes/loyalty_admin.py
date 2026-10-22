"""Painel: fidelidade (selos), desconto do 1º pedido e senha nova do cliente."""

import secrets
from decimal import Decimal, InvalidOperation

from flask import flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Category, Customer
from app.routes.admin import FormError, _reject, _save, admin_bp
from app.services.loyalty import KIND_NAMES, card, first_order_text, is_active, reward_text

MAX_GOAL = 30


@admin_bp.route("/fidelidade", methods=["GET", "POST"])
def loyalty():
    t = g.tenant
    cats = Category.query.filter(Category.tenant_id == t.id, Category.kind.in_(("pizza", "doce"))) \
        .order_by(Category.sort_order, Category.id).all()
    if request.method == "POST":
        form = request.form
        try:
            t.loyalty_enabled = "loyalty_enabled" in form
            try:
                goal = int(form.get("loyalty_goal", ""))
            except ValueError:
                goal = 0
            if not 2 <= goal <= MAX_GOAL:
                raise FormError(f"Fidelidade: o número de pizzas vai de 2 a {MAX_GOAL}.")
            t.loyalty_goal = goal
            chosen = [k for k in KIND_NAMES if k in form.getlist("kinds")]
            if t.loyalty_enabled and not chosen:
                raise FormError("Fidelidade: marque o que conta selo (ex.: pizzas salgadas).")
            t.loyalty_kinds = ",".join(chosen) or "pizza"
            cat = next((c for c in cats if c.id == form.get("reward_category", type=int)), None)
            if t.loyalty_enabled and not cat:
                raise FormError("Fidelidade: escolha qual pizza o cliente ganha.")
            t.loyalty_reward_category_id = cat.id if cat else None
            size = form.get(f"reward_size-{cat.id}", "") if cat else ""
            if cat and size and size not in [s["label"] for s in cat.sizes()]:
                raise FormError("Fidelidade: tamanho inválido. Atualize a página.")
            t.loyalty_reward_size = size or None

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
            _save("Fidelidade e desconto do 1º pedido salvos.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.loyalty"))
    registered = Customer.query.filter(Customer.tenant_id == t.id, Customer.registered_at.isnot(None)).count()
    return render_template("admin/loyalty.html", cats=cats, kinds=KIND_NAMES, registered=registered,
                           active=is_active(t), reward=reward_text(t), first_text=first_order_text(t))


@admin_bp.route("/clientes/<int:customer_id>/senha", methods=["POST"])
def customer_new_pin(customer_id):
    """Cliente esqueceu a senha: gera uma de 4 números para o dono mandar pelo WhatsApp."""
    c = Customer.query.filter_by(tenant_id=g.tenant.id, id=customer_id).first_or_404()
    if not c.registered_at:
        flash(f"{c.name} ainda não tem cadastro no site.", "error")
        return redirect(url_for("admin.customers"))
    pin = f"{secrets.randbelow(10000):04d}"
    c.set_pin(pin)
    c.failed_attempts, c.locked_until = 0, None
    db.session.commit()
    flash(f"Senha nova de {c.name}: {pin}. Mande para o cliente pelo WhatsApp; ele pode trocar depois em “Minha conta”.", "ok")
    return redirect(url_for("admin.customers", q=c.phone_key))


def loyalty_card(customer):
    """Para a lista de clientes."""
    return card(g.tenant, customer) if is_active(g.tenant) and customer.registered_at else None
