from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models import Addon, Border, Product, ProductVariant
from app.routes.public import get_tenant_or_404
from app.services import cart as cart_service
from app.services.delivery import calculate_fee, get_active_neighborhoods
from app.services.whatsapp import build_order_message, build_whatsapp_link

cart_bp = Blueprint("cart", __name__)


@cart_bp.route("/<slug>/carrinho/adicionar", methods=["POST"])
def add_to_cart(slug):
    tenant = get_tenant_or_404(slug)

    product = Product.query.filter_by(id=request.form["product_id"], tenant_id=tenant.id).first_or_404()
    variant = ProductVariant.query.filter_by(id=request.form["variant_id"], product_id=product.id).first_or_404()

    names = [product.name]
    price = Decimal(str(variant.price))

    second_flavor_id = request.form.get("second_flavor_id")
    if second_flavor_id:
        second_product = Product.query.filter_by(id=second_flavor_id, tenant_id=tenant.id).first_or_404()
        second_variant = ProductVariant.query.filter_by(
            product_id=second_product.id, label=variant.label
        ).first()
        if second_variant:
            names = [f"1/2 {product.name}", f"1/2 {second_product.name}"]
            # regra: meio a meio cobra o sabor mais caro
            price = max(price, Decimal(str(second_variant.price)))

    addon_names = []
    addon_ids = request.form.getlist("addon_ids")
    is_whole = "inteira" in variant.label.lower() or "grande" in variant.label.lower()
    for addon_id in addon_ids:
        addon = Addon.query.filter_by(id=addon_id, tenant_id=tenant.id).first()
        if addon:
            addon_price = Decimal(str(addon.price_whole if is_whole else addon.price_half))
            price += addon_price
            addon_names.append(addon.name)

    border_name = None
    border_id = request.form.get("border_id")
    if border_id:
        border = Border.query.filter_by(id=border_id, tenant_id=tenant.id).first()
        if border:
            price += Decimal(str(border.price))
            border_name = border.name

    quantity = int(request.form.get("quantity", 1) or 1)
    notes = request.form.get("notes", "").strip()

    cart_service.add_item(
        tenant.id,
        {
            "product_names": " + ".join(names),
            "variant_label": variant.label,
            "border_name": border_name,
            "addon_names": ", ".join(addon_names),
            "unit_price": price,
            "quantity": quantity,
            "notes": notes,
        },
    )
    flash("Item adicionado ao carrinho.", "success")
    return redirect(url_for("cart.view_cart", slug=slug))


@cart_bp.route("/<slug>/carrinho")
def view_cart(slug):
    tenant = get_tenant_or_404(slug)
    cart = cart_service.get_cart(tenant.id)
    subtotal = cart_service.cart_subtotal(cart)
    return render_template(
        "cart.html",
        tenant=tenant,
        cart=cart,
        subtotal=subtotal,
        cart_count=cart_service.cart_item_count(cart),
    )


@cart_bp.route("/<slug>/carrinho/atualizar/<item_id>", methods=["POST"])
def update_item(slug, item_id):
    tenant = get_tenant_or_404(slug)
    quantity = request.form.get("quantity", 1)
    cart_service.update_quantity(tenant.id, item_id, quantity)
    return redirect(url_for("cart.view_cart", slug=slug))


@cart_bp.route("/<slug>/carrinho/remover/<item_id>", methods=["POST"])
def remove_item(slug, item_id):
    tenant = get_tenant_or_404(slug)
    cart_service.remove_item(tenant.id, item_id)
    flash("Item removido do carrinho.", "info")
    return redirect(url_for("cart.view_cart", slug=slug))


@cart_bp.route("/<slug>/checkout", methods=["GET", "POST"])
def checkout(slug):
    tenant = get_tenant_or_404(slug)
    cart = cart_service.get_cart(tenant.id)
    if not cart:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("public.menu", slug=slug))

    neighborhoods = get_active_neighborhoods(tenant.id)
    subtotal = cart_service.cart_subtotal(cart)

    if request.method == "POST":
        neighborhood_name = request.form.get("neighborhood_name", "").strip()
        fee, found = calculate_fee(tenant.id, neighborhood_name)
        delivery_fee = float(fee) if found else None
        total = round(subtotal + (delivery_fee or 0), 2)

        order = {
            "customer_name": request.form.get("customer_name", "").strip(),
            "customer_phone": request.form.get("customer_phone", "").strip(),
            "street": request.form.get("street", "").strip(),
            "number": request.form.get("number", "").strip(),
            "complement": request.form.get("complement", "").strip(),
            "neighborhood_name": neighborhood_name,
            "reference": request.form.get("reference", "").strip(),
            "payment_method": request.form.get("payment_method", "").strip(),
            "change_for": request.form.get("change_for") or None,
        }

        message = build_order_message(tenant, order, cart, delivery_fee, subtotal, total)
        wa_link = build_whatsapp_link(tenant.whatsapp, message)

        cart_service.clear_cart(tenant.id)
        return render_template("order_success.html", tenant=tenant, wa_link=wa_link)

    return render_template(
        "checkout.html",
        tenant=tenant,
        cart=cart,
        subtotal=subtotal,
        neighborhoods=neighborhoods,
        cart_count=cart_service.cart_item_count(cart),
    )
