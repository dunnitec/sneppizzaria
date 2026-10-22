"""Pedido feito pelo site: recebe as escolhas do cliente e devolve o link do WhatsApp com a mensagem pronta.

A validação, os preços e a gravação ficam em app/services/order_create.py (mesma regra do painel).
"""

from flask import Blueprint, jsonify, request

from app.routes.public import get_tenant_or_404
from app.services.hours import local_time
from app.services.order_create import place_order
from app.services.pix import for_order
from app.services.pricing import OrderError
from app.services.whatsapp import build_whatsapp_link

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/<slug>/api/pedido", methods=["POST"])
def create_order(slug):
    tenant = get_tenant_or_404(slug)
    try:
        order, delivery_fee = place_order(tenant, request.get_json(silent=True) or {}, channel="site")
    except OrderError as e:
        return jsonify(ok=False, error=str(e)), 400
    # Pix com o valor exato; com a taxa de entrega “a confirmar” o total ainda não é o final
    pix = for_order(tenant, order) if order.payment_method == "Pix" and (delivery_fee is not None or not order.delivery) else None
    return jsonify(
        ok=True,
        order_id=order.id,
        wa_link=build_whatsapp_link(tenant.whatsapp, order.whatsapp_message),
        subtotal=float(order.subtotal),
        delivery_fee=float(delivery_fee) if delivery_fee is not None else None,
        total=float(order.total),
        eta=local_time(order.eta_at).strftime("%H:%M"),
        eta_label="Previsão de entrega" if order.delivery else "Pronto para retirar",
        pix=pix,
        pix_pending=order.payment_method == "Pix" and bool(tenant.pix_key) and pix is None,
    )
