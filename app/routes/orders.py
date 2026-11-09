"""Pedido feito pelo site: recebe as escolhas do cliente e devolve o link do WhatsApp com a mensagem pronta.

A validação, os preços e a gravação ficam em app/services/order_create.py (mesma regra do painel).
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request, url_for

from app.extensions import db
from app.models import PushSubscription
from app.routes.public import get_tenant_or_404
from app.services.coupons import check, public
from app.services.customers import phone_key
from app.services.order_create import place_order
from app.services.pix import for_order
from app.services.plans import has as has_feature
from app.services.pricing import OrderError
from app.services.whatsapp import build_whatsapp_link

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/<slug>/api/cupom", methods=["POST"])
def coupon_check(slug):
    """Cliente digitou um código no pagamento: confere e devolve o cupom. O desconto final é calculado no pedido."""
    tenant = get_tenant_or_404(slug)
    data = request.get_json(silent=True) or {}
    try:
        subtotal = Decimal(str(data.get("subtotal") or 0))
    except InvalidOperation:
        subtotal = Decimal("0")
    try:
        coupon = check(tenant, data.get("code"), subtotal, phone_key(str(data.get("phone") or "")))
    except OrderError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, coupon=public(coupon))


@orders_bp.route("/<slug>/api/pedido", methods=["POST"])
def create_order(slug):
    tenant = get_tenant_or_404(slug)
    try:
        from app.routes.account import current_customer

        order, delivery_fee = place_order(tenant, request.get_json(silent=True) or {}, channel="site",
                                          account=current_customer(tenant))
    except OrderError as e:
        return jsonify(ok=False, error=str(e)), 400
    endpoint = str((request.get_json(silent=True) or {}).get("push_endpoint") or "")
    if endpoint and order.customer_id:
        sub = PushSubscription.query.filter_by(tenant_id=tenant.id, endpoint=endpoint).first()
        if sub:
            sub.customer_id = order.customer_id
            db.session.commit()
    # Pix com o valor exato; com a taxa de entrega “a confirmar” o total ainda não é o final
    pix = for_order(tenant, order) if order.payment_method == "Pix" and (delivery_fee is not None or not order.delivery) else None
    return jsonify(
        ok=True,
        order_id=order.id,
        ticket=order.ticket,
        wa_link=build_whatsapp_link(tenant.whatsapp, order.whatsapp_message),
        subtotal=float(order.subtotal),
        delivery_fee=float(delivery_fee) if delivery_fee is not None else None,
        total=float(order.total),
        eta=order.eta_text(),
        eta_label="Previsão de entrega" if order.delivery else "Pronto para retirar",
        pix=pix,
        discount=float(order.discount),
        discount_note=order.discount_note or "",
        track_url=url_for("account.track", slug=slug, token=order.track_token) if has_feature(tenant, "rastreio") else None,
        pix_pending=order.payment_method == "Pix" and bool(tenant.pix_key) and order.delivery and delivery_fee is None,
    )
