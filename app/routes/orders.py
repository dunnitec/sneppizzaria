"""Recebe as escolhas do cliente, calcula preços e taxa de entrega no servidor,
grava o pedido no banco e devolve o link do WhatsApp com a mensagem pronta."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import Order, OrderItem, OrderItemFlavor
from app.services.customers import phone_key, upsert_customer
from app.routes.public import get_tenant_or_404
from app.services.delivery import calculate_fee
from app.services.hours import is_open
from app.services.pricing import OrderError, price_item
from app.services.money import brl
from app.services.whatsapp import build_order_message, build_whatsapp_link

orders_bp = Blueprint("orders", __name__)

MAX_ITEMS = 30


MAX_CHANGE_FOR = Decimal("99999.99")


def _change_for(value):
    """'Troco para quanto' digitado pelo cliente; qualquer coisa que não seja um valor razoável vira None."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or not 0 < amount <= MAX_CHANGE_FOR:
        return None
    return amount.quantize(Decimal("0.01"))


@orders_bp.route("/<slug>/api/pedido", methods=["POST"])
def create_order(slug):
    tenant = get_tenant_or_404(slug)
    p = request.get_json(silent=True) or {}
    if not is_open(tenant):
        return jsonify(ok=False, error="Estamos fechados no momento. Confira nossos horários de atendimento."), 400

    items = p.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify(ok=False, error="Sua cesta está vazia."), 400
    if len(items) > MAX_ITEMS:
        return jsonify(ok=False, error="Pedido grande demais. Fale com a loja pelo WhatsApp."), 400
    if not str(p.get("customer_name") or "").strip() or not str(p.get("customer_phone") or "").strip():
        return jsonify(ok=False, error="Informe nome e telefone."), 400

    key = phone_key(p.get("customer_phone"))
    if not key:
        return jsonify(ok=False, error="Informe um telefone válido, com DDD."), 400

    withdraw = bool(p.get("withdraw"))
    if not withdraw and not (str(p.get("street") or "").strip() and str(p.get("number") or "").strip()):
        return jsonify(ok=False, error="Informe o endereço de entrega."), 400

    try:
        cart = [price_item(tenant, it) for it in items]
    except OrderError as e:
        return jsonify(ok=False, error=str(e)), 400
    subtotal = sum((line["line_total"] for line in cart), Decimal("0"))
    if tenant.min_order and subtotal < tenant.min_order:
        return jsonify(ok=False, error=f"O pedido mínimo é de {brl(tenant.min_order)} (sem a entrega)."), 400

    neighborhood = str(p.get("neighborhood") or "").strip()
    if withdraw:
        fee, found = Decimal("0"), True
    else:
        fee, found = calculate_fee(tenant.id, neighborhood)
    delivery_fee = fee if found else None
    total = subtotal + (delivery_fee or Decimal("0"))

    order_info = {
        "customer_name": str(p["customer_name"]).strip()[:120],
        "customer_phone": str(p["customer_phone"]).strip()[:30],
        "street": str(p.get("street") or "").strip()[:200],
        "number": str(p.get("number") or "").strip()[:20],
        "complement": str(p.get("complement") or "").strip()[:120],
        "neighborhood_name": neighborhood[:120] or ("Retirada na loja" if withdraw else "(outro bairro)"),
        "reference": str(p.get("reference") or "").strip()[:200],
        "payment_method": str(p.get("payment_method") or "").strip()[:30],
        "change_for": _change_for(p.get("change_for")),
        "withdraw": withdraw,
    }

    customer = upsert_customer(tenant, key, order_info)
    db.session.flush()

    order = Order(
        tenant_id=tenant.id,
        customer_id=customer.id,
        customer_name=order_info["customer_name"],
        customer_phone=order_info["customer_phone"],
        street=order_info["street"],
        number=order_info["number"],
        complement=order_info["complement"],
        neighborhood_name=order_info["neighborhood_name"],
        reference=order_info["reference"],
        payment_method=order_info["payment_method"],
        change_for=order_info["change_for"],
        subtotal=subtotal,
        delivery_fee=delivery_fee or Decimal("0"),
        total=total,
    )
    db.session.add(order)
    db.session.flush()  # gera o número do pedido usado na mensagem
    for line in cart:
        item = OrderItem(
                order_id=order.id,
                product_names=line["product_names"],
                variant_label=line["variant_label"],
                border_name=line["border_name"] or None,
                addon_names=line["addon_names"] or None,
                extras=line["extras"] or None,
                notes=line["notes"] or None,
                unit_price=line["unit_price"],
                quantity=line["quantity"],
                line_total=line["line_total"],
        )
        db.session.add(item)
        db.session.flush()
        for product, share in line["flavors"]:
            db.session.add(
                OrderItemFlavor(order_item_id=item.id, product_id=product.id, product_name=product.name, share=share)
            )

    message = build_order_message(tenant, order.id, order_info, cart, delivery_fee, subtotal, total)
    order.whatsapp_message = message
    db.session.commit()

    return jsonify(
        ok=True,
        order_id=order.id,
        wa_link=build_whatsapp_link(tenant.whatsapp, message),
        subtotal=float(subtotal),
        delivery_fee=float(delivery_fee) if delivery_fee is not None else None,
        total=float(total),
    )
