from urllib.parse import quote


def brl(v):
    return f"R$ {float(v):.2f}".replace(".", ",")


def build_order_message(tenant, order_id, order, cart, delivery_fee, subtotal, total):
    lines = [f"*Novo pedido - {tenant.name}*", f"Pedido #{order_id}", ""]

    for item in cart:
        lines.append(f"▪ {item['quantity']}x {item['product_names']} ({item['variant_label']})")
        if item.get("border_name"):
            lines.append(f"   Borda: {item['border_name']}")
        if item.get("addon_names"):
            lines.append(f"   Adicionais: {item['addon_names']}")
        if item.get("notes"):
            lines.append(f"   Obs: {item['notes']}")
        lines.append(f"   {brl(item['line_total'])}")

    lines += [
        "",
        f"Subtotal: {brl(subtotal)}",
    ]
    if order.get("withdraw"):
        lines.append("Retirada na loja")
        lines.append(f"*Total: {brl(total)}*")
    elif delivery_fee is not None:
        lines.append(f"Entrega: {brl(delivery_fee)}")
        lines.append(f"*Total: {brl(total)}*")
    else:
        lines.append("Entrega: a confirmar")
        lines.append(f"*Total (sem entrega): {brl(total)}*")

    lines += [
        "",
        f"*Cliente:* {order['customer_name']}",
        f"*Telefone:* {order['customer_phone']}",
    ]
    if not order.get("withdraw"):
        lines.append(f"*Endereço:* {order['street']}, {order['number']} - {order['neighborhood_name']}")
    if order.get("complement"):
        lines.append(f"Complemento: {order['complement']}")
    if order.get("reference"):
        lines.append(f"Referência: {order['reference']}")

    lines.append(f"*Pagamento:* {order['payment_method']}")
    if order.get("change_for"):
        lines.append(f"Troco para: {brl(float(order['change_for']))}")

    return "\n".join(lines)


def build_whatsapp_link(whatsapp_number, message):
    number = "".join(ch for ch in whatsapp_number if ch.isdigit())
    return f"https://wa.me/{number}?text={quote(message)}"
