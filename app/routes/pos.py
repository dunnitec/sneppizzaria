"""Lançar pedido pelo painel (balcão, mesa, telefone/WhatsApp). Mesma regra de preço do site."""

from flask import g, jsonify, render_template, request, url_for

from app.routes.admin import PAYMENT_OPTIONS, admin_bp
from app.services.menu_data import data_from_db
from app.services.order_create import place_order
from app.services.pricing import OrderError


@admin_bp.route("/pedidos/novo", methods=["GET", "POST"])
def order_new():
    if request.method == "GET":
        data = data_from_db(g.tenant, order_url=url_for("admin.order_new"), assets={})
        payments = [p for p in (g.tenant.accepted_payments or "").split(",") if p] or PAYMENT_OPTIONS
        return render_template("admin/pos.html", data=data, payments=payments)

    payload = request.get_json(silent=True) or {}
    channel = payload.get("channel")
    if channel == "site":  # pedido do site só vem do site
        return jsonify(ok=False, error="Escolha balcão, mesa ou telefone."), 400
    try:
        order, _ = place_order(g.tenant, payload, channel=channel or "")
    except OrderError as e:
        return jsonify(ok=False, error=str(e)), 400
    to_print = order.id if g.tenant.auto_print else None
    return jsonify(ok=True, order_id=order.id, total=float(order.total),
                   redirect=url_for("admin.orders", imprimir=to_print))
