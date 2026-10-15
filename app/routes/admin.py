"""Painel do dono da loja: /<slug>/admin/

Cada usuário pertence a uma loja e só enxerga os dados dela. Todas as telas,
menos o login, exigem sessão; todo POST exige o token CSRF (app/extensions.py).
"""

import json
import re
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import (
    MIN_PASSWORD_LENGTH,
    Addon,
    AdminUser,
    Border,
    Category,
    Neighborhood,
    Order,
    Product,
    ProductVariant,
    split_options,
    utcnow,
)
from app.routes.public import get_tenant_or_404
from app.services.hours import is_open
from app.services.menu_data import WEEKDAYS
from app.services.money import parse_money

admin_bp = Blueprint("admin", __name__, url_prefix="/<slug>/admin")

MAX_FAILED_LOGINS = 5
LOCK_TIME = timedelta(minutes=15)
ORDER_STATUSES = ("pendente", "confirmado", "cancelado")
STORE_STATUS = {"auto": None, "open": True, "closed": False}
# gasta o mesmo tempo de uma conferência de senha quando o usuário não existe,
# para a resposta não revelar quais usuários existem
_DUMMY_HASH = generate_password_hash("usuario-inexistente")


class FormError(ValueError):
    """Dado inválido digitado no painel; a mensagem é mostrada ao usuário e nada é salvo."""


@admin_bp.url_value_preprocessor
def _pull_tenant(endpoint, values):
    g.tenant = get_tenant_or_404(values.pop("slug"))


@admin_bp.url_defaults
def _add_slug(endpoint, values):
    if "slug" not in values and g.get("tenant"):
        values["slug"] = g.tenant.slug


def _session_key(user):
    # muda quando a senha muda, derrubando as sessões abertas com a senha antiga
    return user.password_hash[-16:]


@admin_bp.before_request
def _require_login():
    g.admin = None
    user = db.session.get(AdminUser, session.get("admin_id") or 0)
    if user and user.tenant_id == g.tenant.id and session.get("admin_key") == _session_key(user):
        g.admin = user
    elif request.endpoint != "admin.login":
        return redirect(url_for("admin.login"))


@admin_bp.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@admin_bp.context_processor
def _template_context():
    return {"tenant": g.tenant, "admin": g.admin, "store_open": is_open(g.tenant)}


def _price(text, what, positive=False):
    try:
        value = parse_money(text)
    except ValueError:
        raise FormError(f"Valor inválido em {what}: “{text}”. Use o formato 65,00.") from None
    if positive and value <= 0:
        raise FormError(f"O preço de {what} precisa ser maior que zero.")
    return value


def _name(text, what, max_length=120):
    name = " ".join(str(text or "").split())
    if not name or len(name) > max_length:
        raise FormError(f"Informe {what} (até {max_length} caracteres).")
    return name


def _save(message):
    """Grava as alterações da requisição; em caso de FormError nada é salvo."""
    db.session.commit()
    flash(message, "ok")


def _reject(error):
    db.session.rollback()
    flash(str(error), "error")


# ---------- login ----------

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = AdminUser.query.filter_by(tenant_id=g.tenant.id, username=username).first()
        now = utcnow()
        if user is None:
            check_password_hash(_DUMMY_HASH, password)
        elif user.locked_until and user.locked_until > now:
            flash("Muitas tentativas seguidas. Aguarde 15 minutos e tente de novo.", "error")
            return render_template("admin/login.html")
        elif user.check_password(password):
            user.failed_attempts = 0
            user.locked_until = None
            db.session.commit()
            session.clear()
            session.permanent = True
            session["admin_id"] = user.id
            session["admin_key"] = _session_key(user)
            return redirect(url_for("admin.orders"))
        else:
            user.failed_attempts += 1
            if user.failed_attempts >= MAX_FAILED_LOGINS:
                user.failed_attempts = 0
                user.locked_until = now + LOCK_TIME
            db.session.commit()
        flash("Usuário ou senha incorretos.", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
def index():
    return redirect(url_for("admin.orders"))


@admin_bp.route("/senha", methods=["GET", "POST"])
def password():
    if request.method == "POST":
        new = request.form.get("new", "")
        if not g.admin.check_password(request.form.get("current", "")):
            flash("A senha atual não confere.", "error")
        elif len(new) < MIN_PASSWORD_LENGTH:
            flash(f"A nova senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.", "error")
        elif new != request.form.get("confirm", ""):
            flash("A confirmação não é igual à nova senha.", "error")
        else:
            g.admin.set_password(new)
            db.session.commit()
            session["admin_key"] = _session_key(g.admin)
            flash("Senha alterada.", "ok")
        return redirect(url_for("admin.password"))
    return render_template("admin/password.html")


# ---------- pedidos ----------

@admin_bp.route("/pedidos")
def orders():
    status = request.args.get("status")
    query = Order.query.filter_by(tenant_id=g.tenant.id)
    if status in ORDER_STATUSES:
        query = query.filter_by(status=status)
    return render_template(
        "admin/orders.html",
        orders=query.order_by(Order.id.desc()).limit(100).all(),
        status=status if status in ORDER_STATUSES else None,
        statuses=ORDER_STATUSES,
    )


@admin_bp.route("/pedidos/<int:order_id>/status", methods=["POST"])
def order_status(order_id):
    order = Order.query.filter_by(tenant_id=g.tenant.id, id=order_id).first_or_404()
    status = request.form.get("status")
    if status not in ORDER_STATUSES:
        abort(400)
    order.status = status
    db.session.commit()
    current_filter = request.form.get("filter")
    return redirect(url_for("admin.orders", status=current_filter if current_filter in ORDER_STATUSES else None))


# ---------- cardápio ----------

def category_sizes(category):
    """Tamanhos da categoria como [(rótulo, máx. de sabores)], na ordem em que aparecem."""
    sizes = {}
    for product in category.products:
        for variant in product.variants:
            sizes.setdefault(variant.label, variant.max_flavors)
    return list(sizes.items())


def _category_or_404(category_id):
    return Category.query.filter_by(tenant_id=g.tenant.id, id=category_id).first_or_404()


@admin_bp.route("/cardapio")
def menu():
    categories = Category.query.filter_by(tenant_id=g.tenant.id).order_by(Category.sort_order, Category.id).all()
    lines = [c for c in categories if c.kind != "metro"]
    return render_template(
        "admin/menu.html", categories=categories, lines=lines, sizes={c.id: category_sizes(c) for c in categories}
    )


@admin_bp.route("/cardapio/<int:category_id>", methods=["POST"])
def menu_save(category_id):
    category = _category_or_404(category_id)
    form = request.form
    try:
        for product in category.products:
            if f"name-{product.id}" not in form:
                continue
            product.name = _name(form[f"name-{product.id}"], "o nome do sabor")
            product.description = form.get(f"desc-{product.id}", "").strip()[:500]
            product.active = f"active-{product.id}" in form
            for variant in product.variants:
                if f"price-{variant.id}" in form:
                    variant.price = _price(form[f"price-{variant.id}"], f"{product.name} ({variant.label})", positive=True)
        _save(f"{category.name}: alterações salvas.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.menu", _anchor=f"cat-{category.id}"))


@admin_bp.route("/cardapio/<int:category_id>/novo", methods=["POST"])
def product_new(category_id):
    category = _category_or_404(category_id)
    if category.kind == "metro":
        abort(400)
    form = request.form
    try:
        name = _name(form.get("name"), "o nome do sabor")
        if any(p.name.lower() == name.lower() for p in category.products):
            raise FormError(f"Já existe “{name}” em {category.name}.")
        variants = [
            ProductVariant(label=label, max_flavors=max_flavors, price=_price(form[f"newprice-{i}"], f"{name} ({label})", positive=True))
            for i, (label, max_flavors) in enumerate(category_sizes(category))
            if form.get(f"newprice-{i}", "").strip()
        ]
        if not variants:
            raise FormError("Informe o preço de pelo menos um tamanho.")
        db.session.add(
            Product(
                tenant_id=g.tenant.id,
                category_id=category.id,
                name=name,
                description=form.get("desc", "").strip()[:500],
                variants=variants,
            )
        )
        _save(f"“{name}” adicionado em {category.name}.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.menu", _anchor=f"cat-{category.id}"))


MAX_COMBO_FLAVORS = 6


@admin_bp.route("/cardapio/<int:category_id>/combo", methods=["POST"])
def combo_save(category_id):
    category = _category_or_404(category_id)
    if category.kind != "metro":
        abort(400)
    form = request.form
    try:
        category.name = _name(form.get("name"), "o nome do combo", max_length=80)
        lines = Category.query.filter(Category.tenant_id == g.tenant.id, Category.kind != "metro")
        valid = {c.slug for c in lines}
        sources = [s for s in form.getlist("sources") if s in valid]
        if not sources:
            raise FormError("Marque pelo menos uma linha de onde o cliente escolhe os sabores do combo.")
        try:
            max_flavors = int(form.get("max_flavors", ""))
        except ValueError:
            max_flavors = 0
        if not 1 <= max_flavors <= MAX_COMBO_FLAVORS:
            raise FormError(f"A quantidade de sabores do combo vai de 1 a {MAX_COMBO_FLAVORS}.")
        extras = [" ".join(line.split()) for line in form.get("extras", "").splitlines() if line.strip()]
        if any(len(line) > 80 for line in extras):
            raise FormError("Cada item que acompanha o combo pode ter até 80 caracteres.")
        category.combo_sources = json.dumps(sources)
        category.combo_extras = "\n".join(extras)
        category.combo_choice_label = " ".join(form.get("choice_label", "").split())[:60] or None
        category.combo_choice_options = ", ".join(split_options(form.get("choice_options")))[:255] or None
        for product in category.products:
            for variant in product.variants:
                variant.max_flavors = max_flavors
        _save(f"{category.name}: configuração do combo salva.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.menu", _anchor=f"cat-{category.id}"))


# ---------- bordas e adicionais ----------

@admin_bp.route("/extras", methods=["GET", "POST"])
def extras():
    borders = Border.query.filter_by(tenant_id=g.tenant.id).order_by(Border.id).all()
    addons = Addon.query.filter_by(tenant_id=g.tenant.id).order_by(Addon.id).all()
    if request.method == "POST":
        form = request.form
        try:
            for border in borders:
                if f"border-price-{border.id}" in form:
                    border.price = _price(form[f"border-price-{border.id}"], f"borda {border.name}")
                    border.active = f"border-active-{border.id}" in form
            for addon in addons:
                if f"addon-whole-{addon.id}" in form:
                    addon.price_whole = _price(form[f"addon-whole-{addon.id}"], f"adicional {addon.name} (inteira)")
                    addon.price_half = _price(form.get(f"addon-half-{addon.id}"), f"adicional {addon.name} (broto)")
                    addon.active = f"addon-active-{addon.id}" in form
            _save("Bordas e adicionais salvos.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.extras"))
    return render_template("admin/extras.html", borders=borders, addons=addons)


# ---------- entrega ----------

@admin_bp.route("/entrega", methods=["GET", "POST"])
def delivery():
    hoods = Neighborhood.query.filter_by(tenant_id=g.tenant.id).order_by(Neighborhood.name).all()
    if request.method == "POST":
        form = request.form
        try:
            for hood in hoods:
                if f"fee-{hood.id}" in form:
                    hood.fee = _price(form[f"fee-{hood.id}"], f"taxa de {hood.name}")
                    hood.active = f"active-{hood.id}" in form
            _save("Taxas de entrega salvas.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.delivery"))
    return render_template("admin/delivery.html", hoods=hoods)


@admin_bp.route("/entrega/novo", methods=["POST"])
def delivery_new():
    try:
        name = _name(request.form.get("name"), "o nome do bairro")
        exists = Neighborhood.query.filter(
            Neighborhood.tenant_id == g.tenant.id, db.func.lower(Neighborhood.name) == name.lower()
        ).first()
        if exists:
            raise FormError(f"O bairro “{exists.name}” já está na lista.")
        db.session.add(Neighborhood(tenant_id=g.tenant.id, name=name, fee=_price(request.form.get("fee"), f"taxa de {name}")))
        _save(f"Bairro “{name}” adicionado.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.delivery"))


# ---------- loja ----------

def _minutes(text):
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(text or ""))
    return int(match[1]) * 60 + int(match[2]) if match else None


@admin_bp.route("/loja", methods=["GET", "POST"])
def store():
    tenant = g.tenant
    if request.method == "POST":
        form = request.form
        try:
            if form.get("status") not in STORE_STATUS:
                raise FormError("Escolha se a loja segue o horário, fica aberta ou fica fechada.")
            whatsapp = re.sub(r"\D", "", form.get("whatsapp", ""))
            if not re.fullmatch(r"55\d{10,11}", whatsapp):
                raise FormError("WhatsApp inválido. Use 55 + DDD + número, ex.: 5511973937104.")
            hours = {}
            for day in range(7):
                if f"closed-{day}" in form:
                    hours[str(day)] = None
                    continue
                opens, closes = _minutes(form.get(f"open-{day}")), _minutes(form.get(f"close-{day}"))
                if opens is None or closes is None or opens >= closes:
                    raise FormError(
                        f"Horário inválido em {WEEKDAYS[day]}: o fechamento precisa ser depois da abertura, no mesmo dia (até 23:59)."
                    )
                hours[str(day)] = [opens, closes]
            tenant.eta = _name(form.get("eta"), "o tempo de entrega", max_length=30)
            tenant.whatsapp = whatsapp
            tenant.is_open_override = STORE_STATUS[form["status"]]
            tenant.hours_json = json.dumps(hours)
            _save("Dados da loja salvos.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.store"))

    hours = json.loads(tenant.hours_json) if tenant.hours_json else {}
    fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"  # noqa: E731
    days = [
        {"n": d, "name": WEEKDAYS[d], "closed": not hours.get(str(d)),
         "open": fmt(hours[str(d)][0]) if hours.get(str(d)) else "18:00",
         "close": fmt(hours[str(d)][1]) if hours.get(str(d)) else "22:00"}
        for d in (1, 2, 3, 4, 5, 6, 0)
    ]
    status = next(k for k, v in STORE_STATUS.items() if v is tenant.is_open_override)
    return render_template("admin/store.html", days=days, status=status)
