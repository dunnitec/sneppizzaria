"""Lançar pedido pelo painel (balcão, mesa, telefone/WhatsApp). Mesma regra de preço do site."""

from flask import g, jsonify, render_template, request, url_for

from app.models import Customer
from app.routes.admin import PAYMENT_OPTIONS, admin_bp
from app.routes.public import fee_quote
from app.services.customers import format_phone, has_real_name, phone_key
from app.services.loyalty import cards, programs
from app.services.menu_data import data_from_db
from app.services.order_create import place_order
from app.services.pricing import OrderError
from app.services.push import notify_loyalty


@admin_bp.route("/pedidos/novo", methods=["GET", "POST"])
def order_new():
    if request.method == "GET":
        data = data_from_db(g.tenant, order_url=url_for("admin.order_new"), assets={})
        payments = [p for p in (g.tenant.accepted_payments or "").split(",") if p] or PAYMENT_OPTIONS
        from app.models import RESIDENCES

        return render_template("admin/pos.html", data=data, payments=payments, residences=RESIDENCES)

    payload = request.get_json(silent=True) or {}
    channel = payload.get("channel")
    if channel == "site":  # pedido do site só vem do site
        return jsonify(ok=False, error="Escolha balcão, mesa ou telefone."), 400
    try:
        order, _ = place_order(g.tenant, payload, channel=channel or "")
    except OrderError as e:
        return jsonify(ok=False, error=str(e)), 400
    notify_loyalty(g.tenant, order)  # pedido do balcão/telefone já entra confirmado: selos da fidelidade
    to_print = order.id if g.tenant.auto_print else None
    return jsonify(ok=True, order_id=order.id, ticket=order.ticket, total=float(order.total),
                   redirect=url_for("admin.orders", imprimir=to_print))


@admin_bp.route("/pedidos/cliente")
def order_customer():
    """Cliente pelo telefone: nome, endereço guardado e cartões de selos (na tela de novo pedido)."""
    key = phone_key(request.args.get("telefone"))
    c = Customer.query.filter_by(tenant_id=g.tenant.id, phone_key=key).first() if key else None
    loyalty = bool(programs(g.tenant))
    if not c:
        return jsonify(found=False, loyalty=loyalty)
    return jsonify(found=True, loyalty=loyalty, registered=bool(c.registered_at), phone=format_phone(c.phone_key),
                   name=c.name if has_real_name(c.name) else "",
                   address={"street": c.street or "", "number": c.number or "", "complement": c.complement or "",
                            "neighborhood": c.neighborhood or "", "reference": c.reference or "",
                            "residence": c.residence or "", "building": c.building or ""},
                   cards=cards(g.tenant, c) if c.registered_at else [])


@admin_bp.route("/pedidos/frete")
def order_fee_quote():
    """Frete por distância no pedido por telefone: preenche o endereço pelo CEP e sugere a taxa."""
    return jsonify(fee_quote(g.tenant, request.args))
