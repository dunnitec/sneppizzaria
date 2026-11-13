"""Painel: cupons de desconto (criar, pausar, excluir). Regras em app/services/coupons.py."""

from datetime import date
from decimal import Decimal

from flask import flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Coupon
from app.routes.admin import FormError, _optional_km, _price, _reject, admin_bp
from app.services.coupons import FREE, describe, normalize, status, uses
from app.services.hours import work_day

MAX_PERCENT = 90


def _coupon_or_404(coupon_id):
    return Coupon.query.filter_by(tenant_id=g.tenant.id, id=coupon_id).first_or_404()


def _date(text, what):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FormError(f"Data inválida em {what}.") from None


def _new_coupon(form):
    code = normalize(form.get("code"))
    if len(code) < 3:
        raise FormError("O código precisa ter pelo menos 3 letras ou números (ex.: SEXTOU10).")
    if Coupon.query.filter_by(tenant_id=g.tenant.id, code=code).first():
        raise FormError(f"Já existe um cupom {code}.")
    kind = form.get("discount_type") if form.get("discount_type") in ("amount", FREE) else "percent"
    if kind == FREE:
        value, max_km = Decimal("0"), _optional_km(form.get("max_km"), "em “até quantos km”")
    else:
        value, max_km = _price(form.get("value"), "valor do desconto", positive=True), None
    if kind == "percent" and value > MAX_PERCENT:
        raise FormError(f"O desconto pode ser de no máximo {MAX_PERCENT}%.")
    minimum = form.get("min_order", "").strip()
    starts, ends = _date(form.get("starts_on"), "início"), _date(form.get("ends_on"), "fim")
    if starts and ends and ends < starts:
        raise FormError("A data de fim tem que ser depois do início.")
    limit = form.get("max_uses", "").strip()
    if limit and (not limit.isdigit() or int(limit) < 1):
        raise FormError("Limite de usos: use um número inteiro, ou deixe vazio.")
    return Coupon(tenant_id=g.tenant.id, code=code, title=" ".join(form.get("title", "").split())[:60] or None,
                  discount_type=kind, value=value, max_km=max_km, min_order=_price(minimum, "pedido mínimo") if minimum else None,
                  starts_on=starts, ends_on=ends, max_uses=int(limit) if limit else None,
                  per_customer="per_customer" in form, show_on_site="show_on_site" in form)


@admin_bp.route("/cupons", methods=["GET", "POST"])
def coupons():
    if request.method == "POST":
        try:
            coupon = _new_coupon(request.form)
        except FormError as e:
            _reject(e)
            return redirect(url_for("admin.coupons"))
        db.session.add(coupon)
        db.session.commit()
        flash(f"Cupom {coupon.code} criado.", "ok")
        return redirect(url_for("admin.coupons"))
    today = work_day(g.tenant)
    rows = []
    for c in Coupon.query.filter_by(tenant_id=g.tenant.id).order_by(Coupon.id.desc()):
        code, text = status(c, today)
        rows.append({"c": c, "code": code, "status": text, "text": describe(c), "uses": uses(c)})
    return render_template("admin/coupons.html", rows=rows, max_percent=MAX_PERCENT)


@admin_bp.route("/cupons/<int:coupon_id>/pausar", methods=["POST"])
def coupon_toggle(coupon_id):
    coupon = _coupon_or_404(coupon_id)
    coupon.active = not coupon.active
    db.session.commit()
    flash(f"Cupom {coupon.code} {'ligado de novo' if coupon.active else 'pausado: não vale mais no site'}.", "ok")
    return redirect(url_for("admin.coupons"))


@admin_bp.route("/cupons/<int:coupon_id>/excluir", methods=["POST"])
def coupon_delete(coupon_id):
    coupon = _coupon_or_404(coupon_id)
    code = coupon.code
    db.session.delete(coupon)
    db.session.commit()
    flash(f"Cupom {code} excluído. Os pedidos que já usaram continuam com o desconto.", "ok")
    return redirect(url_for("admin.coupons"))
