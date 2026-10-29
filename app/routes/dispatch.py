"""Entregas: motoboys e comandas de saída (despacho e baixa na volta).

Mesmo blueprint do painel (login, CSRF, regras de funcionário em app/routes/admin.py).
"""

from decimal import Decimal

from flask import flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Courier, Dispatch, Order, utcnow
from app.routes.admin import FormError, _name, _reject, admin_bp
from app.services.push import notify_order

CARD = ("Débito", "Crédito", "Cartão")


def money_summary(dispatch):
    """O que conferir com o motoboy: dinheiro a trazer, troco levado, maquininha, Pix e taxas de entrega."""
    s = {k: Decimal("0") for k in ("cash", "change", "card", "pix", "fees")}
    for o in dispatch.orders:
        if o.status == "cancelado":
            continue
        method = (o.payment_method or "").strip()
        if method == "Dinheiro":
            s["cash"] += o.total
            if o.change_for and o.change_for > o.total:
                s["change"] += o.change_for - o.total
        elif method in CARD:
            s["card"] += o.total
        elif method == "Pix":
            s["pix"] += o.total
        s["fees"] += o.delivery_fee or Decimal("0")
    return {k: v.quantize(Decimal("0.01")) for k, v in s.items()}


def _ready_orders():
    return (Order.query.filter_by(tenant_id=g.tenant.id, status="confirmado", delivery=True, dispatch_id=None)
            .order_by(Order.id).all())


@admin_bp.route("/entregas")
def dispatches():
    open_ones = (Dispatch.query.filter_by(tenant_id=g.tenant.id, returned_at=None)
                 .order_by(Dispatch.number.desc()).all())
    closed_today = (Dispatch.query.filter(Dispatch.tenant_id == g.tenant.id, Dispatch.returned_at.isnot(None))
                    .order_by(Dispatch.returned_at.desc()).limit(10).all())
    return render_template(
        "admin/dispatches.html",
        ready=_ready_orders(),
        open_dispatches=[(d, money_summary(d)) for d in open_ones],
        closed=[(d, money_summary(d)) for d in closed_today],
        couriers=Courier.query.filter_by(tenant_id=g.tenant.id).order_by(Courier.active.desc(), Courier.name).all(),
        print_dispatch=request.args.get("imprimir_comanda", type=int),
    )


@admin_bp.route("/entregas/nova", methods=["POST"])
def dispatch_new():
    courier = Courier.query.filter_by(tenant_id=g.tenant.id, id=request.form.get("courier_id", type=int), active=True).first()
    wanted = {int(i) for i in request.form.getlist("orders") if str(i).isdigit()}
    orders = [o for o in _ready_orders() if o.id in wanted]
    if not courier:
        flash("Escolha o motoboy que vai levar.", "error")
        return redirect(url_for("admin.dispatches"))
    if not orders:
        flash("Marque pelo menos um pedido para sair.", "error")
        return redirect(url_for("admin.dispatches"))
    last = db.session.query(db.func.max(Dispatch.number)).filter(Dispatch.tenant_id == g.tenant.id).scalar() or 0
    dispatch = Dispatch(tenant_id=g.tenant.id, number=last + 1, courier_id=courier.id, created_at=utcnow())
    db.session.add(dispatch)
    db.session.flush()
    for o in orders:
        o.dispatch_id, o.status = dispatch.id, "saiu"
    db.session.commit()
    for o in orders:
        notify_order(g.tenant, o, "saiu")
    flash(f"Comanda {dispatch.number} criada: {courier.name} saiu com {len(orders)} pedido(s).", "ok")
    return redirect(url_for("admin.dispatches", imprimir_comanda=dispatch.id if g.tenant.auto_print else None))


def _dispatch_or_404(dispatch_id):
    return Dispatch.query.filter_by(tenant_id=g.tenant.id, id=dispatch_id).first_or_404()


@admin_bp.route("/entregas/<int:dispatch_id>/baixa", methods=["POST"])
def dispatch_return(dispatch_id):
    dispatch = _dispatch_or_404(dispatch_id)
    now = utcnow()
    dispatch.returned_at = now
    for o in dispatch.orders:
        if o.status == "saiu":
            o.status, o.delivered_at = "entregue", now
    db.session.commit()
    flash(f"Comanda {dispatch.number} baixada: {dispatch.courier.name} voltou e os pedidos foram entregues.", "ok")
    return redirect(url_for("admin.dispatches"))


@admin_bp.route("/entregas/<int:dispatch_id>/tirar/<int:order_id>", methods=["POST"])
def dispatch_remove_order(dispatch_id, order_id):
    """Pedido que não foi entregue (cliente não estava, endereço errado): volta para a fila de saída."""
    dispatch = _dispatch_or_404(dispatch_id)
    order = Order.query.filter_by(tenant_id=g.tenant.id, id=order_id, dispatch_id=dispatch.id).first_or_404()
    order.dispatch_id = None
    if order.status in ("saiu", "entregue"):  # cancelado continua cancelado
        order.status = "confirmado"
    db.session.flush()
    if not Order.query.filter_by(dispatch_id=dispatch.id).count():
        # comanda sem nenhum pedido não aconteceu: some da lista em vez de ficar “na rua” vazia
        db.session.delete(dispatch)
        flash(f"Pedido #{order.id} voltou para “Prontos para sair” e a comanda {dispatch.number}, que ficou vazia, foi apagada.", "ok")
    else:
        flash(f"Pedido #{order.id} voltou para “Prontos para sair”.", "ok")
    db.session.commit()
    return redirect(url_for("admin.dispatches"))


@admin_bp.route("/entregas/<int:dispatch_id>/etiqueta")
def dispatch_label(dispatch_id):
    dispatch = _dispatch_or_404(dispatch_id)
    return render_template("admin/dispatch_label.html", d=dispatch, s=money_summary(dispatch))


# ---------- motoboys ----------

@admin_bp.route("/entregas/motoboys", methods=["POST"])
def courier_new():
    try:
        name = _name(request.form.get("name"), "o nome do motoboy", max_length=80)
        db.session.add(Courier(tenant_id=g.tenant.id, name=name, phone=request.form.get("phone", "").strip()[:30]))
        db.session.commit()
        flash(f"Motoboy “{name}” cadastrado.", "ok")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.dispatches", _anchor="motoboys"))


@admin_bp.route("/entregas/motoboys/<int:courier_id>/alternar", methods=["POST"])
def courier_toggle(courier_id):
    courier = Courier.query.filter_by(tenant_id=g.tenant.id, id=courier_id).first_or_404()
    courier.active = not courier.active
    db.session.commit()
    flash(f"{courier.name} {'voltou para a lista' if courier.active else 'saiu da lista de motoboys'}.", "ok")
    return redirect(url_for("admin.dispatches", _anchor="motoboys"))
