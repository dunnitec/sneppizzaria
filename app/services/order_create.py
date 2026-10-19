"""Criação de pedido, usada pelo site (canal "site") e pelo painel (balcão, mesa, telefone).

Os preços são sempre recalculados aqui pelo banco (services/pricing.py). As regras que mudam
por canal ficam todas neste arquivo:

- site: loja precisa estar aberta; nome e telefone obrigatórios; pedido mínimo; entra "pendente".
- balcao / mesa: lançado por quem atende; nome e telefone opcionais (mesa exige o número);
  sem pedido mínimo e mesmo com o site fechado; entra "confirmado".
- telefone: lançado por quem atende; nome e telefone obrigatórios; pode ser entrega; entra "confirmado".
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models import CHANNELS, Order, OrderItem, OrderItemFlavor, utcnow
from app.services.customers import phone_key, upsert_customer
from app.services.delivery import calculate_fee
from app.services.hours import is_open, local_time
from app.services.money import brl
from app.services.pricing import OrderError, price_item
from app.services.whatsapp import build_order_message

MAX_ITEMS = 30
MAX_CHANGE_FOR = Decimal("99999.99")


def _change_for(value):
    """'Troco para quanto'; qualquer coisa que não seja um valor razoável vira None."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or not 0 < amount <= MAX_CHANGE_FOR:
        return None
    return amount.quantize(Decimal("0.01"))


def _text(p, key, limit):
    return str(p.get(key) or "").strip()[:limit]


def place_order(tenant, p, channel="site"):
    """Valida, precifica e grava o pedido. Devolve (order, cart). Levanta OrderError com mensagem para a tela."""
    if channel not in CHANNELS:
        raise OrderError("Origem do pedido inválida.")
    from_site = channel == "site"
    if from_site and not is_open(tenant):
        raise OrderError("Estamos fechados no momento. Confira nossos horários de atendimento.")

    items = p.get("items") or []
    if not isinstance(items, list) or not items:
        raise OrderError("Sua cesta está vazia." if from_site else "Adicione pelo menos um item ao pedido.")
    if len(items) > MAX_ITEMS:
        raise OrderError("Pedido grande demais. Fale com a loja pelo WhatsApp." if from_site else "Pedido grande demais.")

    name, phone = _text(p, "customer_name", 120), _text(p, "customer_phone", 30)
    table = _text(p, "table_label", 20)
    if channel in ("site", "telefone") and (not name or not phone):
        raise OrderError("Informe nome e telefone.")
    if channel == "mesa" and not table:
        raise OrderError("Informe o número da mesa.")
    key = phone_key(phone) if phone else None
    if phone and not key:
        raise OrderError("Informe um telefone válido, com DDD.")

    # entrega só existe no site e no telefone; balcão e mesa são sempre no local
    withdraw = bool(p.get("withdraw")) if channel in ("site", "telefone") else True
    if not withdraw and not (_text(p, "street", 200) and _text(p, "number", 20)):
        raise OrderError("Informe o endereço de entrega.")

    cart = [price_item(tenant, it) for it in items]
    subtotal = sum((line["line_total"] for line in cart), Decimal("0"))
    if from_site and tenant.min_order and subtotal < tenant.min_order:
        raise OrderError(f"O pedido mínimo é de {brl(tenant.min_order)} (sem a entrega).")

    neighborhood = _text(p, "neighborhood", 120)
    fee, found = (Decimal("0"), True) if withdraw else calculate_fee(tenant.id, neighborhood)
    delivery_fee = fee if found else None
    total = subtotal + (delivery_fee or Decimal("0"))

    # previsão: entrega usa o tempo de entrega; retirada, balcão e mesa usam o tempo de retirada
    now = utcnow()
    minutes = tenant.eta_minutes if not withdraw else tenant.pickup_minutes
    eta_at = now + timedelta(minutes=minutes or 0)

    default_name = {"balcao": "Balcão", "mesa": f"Mesa {table}"}.get(channel, "")
    info = {
        "customer_name": name or default_name,
        "customer_phone": phone,
        "street": "" if withdraw else _text(p, "street", 200),
        "number": "" if withdraw else _text(p, "number", 20),
        "complement": "" if withdraw else _text(p, "complement", 120),
        "neighborhood_name": neighborhood if not withdraw and neighborhood else
        ("(outro bairro)" if not withdraw else {"mesa": "Comer na loja"}.get(channel, "Retirada na loja")),
        "reference": "" if withdraw else _text(p, "reference", 200),
        "payment_method": _text(p, "payment_method", 30),
        "change_for": _change_for(p.get("change_for")),
        "withdraw": withdraw,
        "eta": local_time(eta_at).strftime("%H:%M"),
    }

    customer = upsert_customer(tenant, key, info) if key else None
    db.session.flush()
    order = Order(
        tenant_id=tenant.id,
        customer_id=customer.id if customer else None,
        customer_name=info["customer_name"],
        customer_phone=info["customer_phone"],
        street=info["street"],
        number=info["number"],
        complement=info["complement"],
        neighborhood_name=info["neighborhood_name"],
        reference=info["reference"],
        payment_method=info["payment_method"],
        change_for=info["change_for"],
        subtotal=subtotal,
        delivery_fee=delivery_fee or Decimal("0"),
        total=total,
        channel=channel,
        delivery=not withdraw,
        table_label=table or None,
        status="pendente" if from_site else "confirmado",
        created_at=now,
        eta_at=eta_at,
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
            kind=line["kind"],
            category_name=line["category_name"],
            notes=line["notes"] or None,
            unit_price=line["unit_price"],
            quantity=line["quantity"],
            line_total=line["line_total"],
        )
        db.session.add(item)
        db.session.flush()
        for product, share in line["flavors"]:
            db.session.add(OrderItemFlavor(order_item_id=item.id, product_id=product.id, product_name=product.name, share=share))

    order.whatsapp_message = build_order_message(tenant, order.id, info, cart, delivery_fee, subtotal, total)
    db.session.commit()
    return order, delivery_fee
