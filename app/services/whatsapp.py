from urllib.parse import quote

from app.services.order_display import flavor_view


def brl(v):
    return f"R$ {float(v):.2f}".replace(".", ",")


def build_order_message(tenant, order_id, order, cart, delivery_fee, subtotal, total):
    lines = [f"*Novo pedido - {tenant.name}*", f"Pedido #{order_id}", ""]

    for item in cart:
        view = flavor_view(item.get("kind"), item.get("category_name"), [p.name for p, _ in item.get("flavors", [])],
                           item["product_names"])
        size = f"{view['tag']} {item['variant_label']}" if view["tag"] else item["variant_label"]
        lines.append(f"▪ {item['quantity']}x {view['head']} — {size}" if view["tag"] else
                     f"▪ {item['quantity']}x {view['head']} ({size})")
        lines += [f"   {extra}" for extra in view["lines"]]
        if item.get("border_name"):
            lines.append(f"   Borda: {item['border_name']}")
        if item.get("extras"):
            lines.append(f"   Acompanha: {item['extras']}")
        if item.get("addon_names"):
            lines.append(f"   Adicionais: {item['addon_names']}")
        if item.get("notes"):
            lines.append(f"   Obs: {item['notes']}")
        if item.get("promo_name"):
            lines.append(f"   Promoção: {item['promo_name']}")
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
    if order["payment_method"] == "Pix" and tenant.pix_key and order.get("from_site"):
        lines.append("Vou pagar pelo Pix do site e mandar o comprovante aqui.")
    if order.get("change_for"):
        lines.append(f"Troco para: {brl(float(order['change_for']))}")
    if order.get("eta"):  # previsão, como no iFood: entrega chega às HH:MM; retirada fica pronta às HH:MM
        lines += ["", f"*Previsão de entrega: {order['eta']}*" if not order.get("withdraw")
                  else f"*Pronto para retirar às {order['eta']}*"]

    return "\n".join(lines)


def build_whatsapp_link(whatsapp_number, message):
    number = "".join(ch for ch in whatsapp_number if ch.isdigit())
    return f"https://wa.me/{number}?text={quote(message)}"
