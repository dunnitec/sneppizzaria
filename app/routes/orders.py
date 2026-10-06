"""Recebe o pedido montado no navegador, calcula a taxa de entrega no servidor,
grava o pedido no banco e devolve o link do WhatsApp com a mensagem pronta."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import Order, OrderItem
from app.routes.public import get_tenant_or_404
from app.services.delivery import calculate_fee
from app.services.whatsapp import build_order_message, build_whatsapp_link

orders_bp = Blueprint("orders", __name__)


def _dec(v, default="0"):
    try:
        return Decimal(str(v if v not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


@orders_bp.route("/<slug>/api/pedido", methods=["POST"])
def create_order(slug):
    tenant = get_tenant_or_404(slug)
    p = request.get_json(silent=True) or {}
    items = p.get("items") or []
    if not items:
        return jsonify(ok=False, error="Sua cesta está vazia."), 400
    if not (p.get("customer_name") or "").strip() or not (p.get("customer_phone") or "").strip():
        return jsonify(ok=False, error="Informe nome e telefone."), 400

    withdraw = bool(p.get("withdraw"))
    if not withdraw and not ((p.get("street") or "").strip() and (p.get("number") or "").strip()):
        return jsonify(ok=False, error="Informe o endereço de entrega."), 400

    cart = []
    subtotal = Decimal("0")
    for it in items:
        qty = max(1, int(it.get("quantity") or 1))
        unit = _dec(it.get("unit_price")).quantize(Decimal("0.01"))
        line = (unit * qty).quantize(Decimal("0.01"))
        subtotal += line
        cart.append(
            {
                "product_names": (it.get("title") or "")[:200],
                "variant_label": (it.get("variant") or "")[:60],
                "border_name": (it.get("border") or "")[:120],
                "addon_names": (it.get("addons") or "")[:300],
                "notes": (it.get("notes") or "")[:300],
                "unit_price": float(unit),
                "quantity": qty,
                "line_total": float(line),
            }
        )

    if withdraw:
        fee, found = Decimal("0"), True
    else:
        fee, found = calculate_fee(tenant.id, (p.get("neighborhood") or "").strip())
    delivery_fee = float(fee) if found else None
    total = float(subtotal) + (delivery_fee or 0)

    order_info = {
        "customer_name": p["customer_name"].strip()[:120],
        "customer_phone": p["customer_phone"].strip()[:30],
        "street": (p.get("street") or "").strip()[:200],
        "number": (p.get("number") or "").strip()[:20],
        "complement": (p.get("complement") or "").strip()[:120],
        "neighborhood_name": (p.get("neighborhood") or "").strip()[:120] or ("Retirada na loja" if withdraw else "(outro bairro)"),
        "reference": (p.get("reference") or "").strip()[:200],
        "payment_method": (p.get("payment_method") or "").strip()[:30],
        "change_for": p.get("change_for") or None,
        "withdraw": withdraw,
    }

    message = build_order_message(tenant, order_info, cart, delivery_fee, float(subtotal), total)
    wa_link = build_whatsapp_link(tenant.whatsapp, message)

    order = Order(
        tenant_id=tenant.id,
        customer_name=order_info["customer_name"],
        customer_phone=order_info["customer_phone"],
        street=order_info["street"],
        number=order_info["number"],
        complement=order_info["complement"],
        neighborhood_name=order_info["neighborhood_name"],
        reference=order_info["reference"],
        payment_method=order_info["payment_method"],
        change_for=_dec(order_info["change_for"]) if order_info["change_for"] else None,
        subtotal=subtotal,
        delivery_fee=Decimal(str(delivery_fee or 0)),
        total=Decimal(str(total)),
        whatsapp_message=message,
    )
    db.session.add(order)
    db.session.flush()
    for it in cart:
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_names=it["product_names"],
                variant_label=it["variant_label"],
                border_name=it["border_name"] or None,
                addon_names=it["addon_names"] or None,
                notes=it["notes"] or None,
                unit_price=Decimal(str(it["unit_price"])),
                quantity=it["quantity"],
                line_total=Decimal(str(it["line_total"])),
            )
        )
    db.session.commit()

    return jsonify(ok=True, order_id=order.id, wa_link=wa_link, subtotal=float(subtotal), delivery_fee=delivery_fee, total=total)
