"""Painel do dono da loja: /<slug>/admin/

Cada usuário pertence a uma loja e só enxerga os dados dela. Todas as telas,
menos o login, exigem sessão; todo POST exige o token CSRF (app/extensions.py).
"""

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import (
    MIN_PASSWORD_LENGTH,
    Addon,
    AdminUser,
    Border,
    Category,
    CATEGORY_ACCENTS,
    CATEGORY_ICONS,
    CHANNELS,
    ORDER_STATUSES,
    SOLD_STATUSES,
    Customer,
    Neighborhood,
    Order,
    Product,
    ProductVariant,
    split_options,
    utcnow,
)
from app.routes.public import get_tenant_or_404
from app.services.hours import STORE_TZ, is_open, status_text
from app.services.plans import blocked_feature
from app.services.plans import has as has_feature
from app.services.menu_data import WEEKDAYS
from app.services.customers import erase_customer
from app.services.money import brl, parse_money
from app.services.photos import PhotoError, delete_photo, save_photo
from app.services.pix import KEY_TYPES as PIX_KEY_TYPES
from app.services.pix import PixKeyError
from app.services.pix import normalize_key as normalize_pix_key
from app.services.promotions import running_count
from app.services.push import notify_loyalty, notify_order
from app.services.reports import month_calendar, sales_report
from app.services.throttle import admin_logins

admin_bp = Blueprint("admin", __name__, url_prefix="/<slug>/admin")

# etapas e origens: ver app/models.py (ORDER_STATUSES, CHANNELS)
STORE_STATUS = {"auto": None, "open": True, "closed": False}
# o que um usuário "funcionario" pode abrir; o "dono" abre tudo
STAFF_ENDPOINTS = {"admin.login", "admin.logout", "admin.index", "admin.orders", "admin.orders_poll",
                   "admin.order_label", "admin.order_printed", "admin.order_new", "admin.dispatches", "admin.dispatch_new",
                   "admin.dispatch_return", "admin.dispatch_remove_order", "admin.dispatch_label",
                   "admin.order_status", "admin.order_pix", "admin.password", "admin.stock", "admin.stock_toggle", "admin.stock_bulk"}
PAYMENT_OPTIONS = ["Dinheiro", "Pix", "Débito", "Crédito"]
# papel da impressora (largura × altura, em mm). Altura 0 = bobina contínua de cupom, que corta no fim do pedido.
LABEL_SIZES = {"80x0": (80, 0), "58x0": (58, 0), "100x150": (100, 150), "100x100": (100, 100), "100x50": (100, 50)}
LABEL_NAMES = {"80x0": "Bobina 80 mm (cupom) — ex.: Bematech MP-4200 HS", "58x0": "Bobina 58 mm (cupom pequeno)",
               "100x150": "Etiqueta 100 × 150 mm", "100x100": "Etiqueta 100 × 100 mm", "100x50": "Etiqueta 100 × 50 mm"}
# tipos de categoria, com as palavras que o dono vê no painel
KINDS = {
    "pizza": {"icon": "🍕", "label": "Pizza salgada", "help": "Sabores com preço por tamanho. Aceita meio a meio, borda e adicionais."},
    "doce": {"icon": "🍫", "label": "Pizza doce", "help": "Igual à salgada, mas aparece separada no cardápio."},
    "bebida": {"icon": "🥤", "label": "Bebida", "help": "Refrigerantes, sucos, água. O cliente só escolhe o tamanho."},
    "metro": {"icon": "🎁", "label": "Combo de preço fixo", "help": ""},
}
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
        if user.role != "dono" and request.endpoint not in STAFF_ENDPOINTS:
            abort(403)
        if blocked_feature(g.tenant, request.endpoint):
            flash("Esta função não faz parte do seu plano. Para usar, fale com quem te vendeu o sistema.", "error")
            return redirect(url_for("admin.index"))
    elif request.endpoint != "admin.login":
        return redirect(url_for("admin.login"))


@admin_bp.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@admin_bp.context_processor
def _template_context():
    pending = Order.query.filter_by(tenant_id=g.tenant.id, status="pendente").count() if g.admin else 0
    return {"tenant": g.tenant, "admin": g.admin, "store_open": is_open(g.tenant),
            "is_owner": bool(g.admin and g.admin.role == "dono"), "pending_count": pending, "kinds": KINDS,
            "has_feature": lambda feature: has_feature(g.tenant, feature),
            "blocked_tab": lambda endpoint: blocked_feature(g.tenant, endpoint)}


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
        ip, account = request.remote_addr or "?", f"{g.tenant.id}:{username}"
        # o bloqueio é da conexão que errou, não do usuário: ninguém consegue trancar o dono por fora,
        # e usuário inexistente recebe as mesmas respostas (não dá para descobrir quais existem)
        if admin_logins.blocked(ip, account):
            flash("Muitas tentativas seguidas. Aguarde 15 minutos e tente de novo.", "error")
            return render_template("admin/login.html")
        user = AdminUser.query.filter_by(tenant_id=g.tenant.id, username=username).first()
        if user is None:
            check_password_hash(_DUMMY_HASH, password)
        elif user.check_password(password):
            admin_logins.success(ip, account)
            session.clear()
            session.permanent = True
            session["admin_id"] = user.id
            session["admin_key"] = _session_key(user)
            return redirect(url_for("admin.index"))
        admin_logins.fail(ip, account)
        flash("Usuário ou senha incorretos.", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
def index():
    if g.admin.role != "dono":
        return redirect(url_for("admin.orders"))
    today = datetime.now(STORE_TZ).date()
    tenant_products = Product.query.filter_by(tenant_id=g.tenant.id)
    sold_out = (tenant_products.filter_by(active=False).count()
                + Border.query.filter_by(tenant_id=g.tenant.id, active=False).count()
                + Addon.query.filter_by(tenant_id=g.tenant.id, active=False).count())
    without_photo = tenant_products.join(Category).filter(Product.image.is_(None), Category.kind != "metro").count()
    has_drinks = tenant_products.join(Category).filter(Category.kind == "bebida").first() is not None
    steps = [
        {"done": g.admin.password_changed, "text": "Trocar a senha temporária do painel por uma só sua",
         "url": url_for("admin.password"), "action": "Trocar senha"},
        {"done": without_photo == 0, "text": f"Pôr as fotos dos itens ({without_photo} ainda sem foto)",
         "url": url_for("admin.photos"), "action": "Pôr fotos"},
        {"done": has_drinks, "text": "Cadastrar as bebidas (refrigerantes, sucos...)",
         "url": url_for("admin.category_new"), "action": "Cadastrar bebidas"},
    ]
    return render_template(
        "admin/home.html", today=today, report=sales_report(g.tenant, today, today), sold_out=sold_out,
        steps=steps, status_line=status_text(g.tenant), promos_running=running_count(g.tenant),
    )


@admin_bp.route("/loja/agora", methods=["POST"])
def store_now():
    """Abrir/fechar com um toque na tela Início."""
    status = request.form.get("status")
    if status not in STORE_STATUS:
        abort(400)
    g.tenant.is_open_override = STORE_STATUS[status]
    db.session.commit()
    flash({"open": "Loja aberta. O site já aceita pedidos.", "closed": "Loja fechada. O site não aceita pedidos até você abrir.",
           "auto": "Pronto: a loja volta a abrir e fechar sozinha no horário."}[status], "ok")
    return redirect(url_for("admin.index"))


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
            g.admin.password_changed = True
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
    latest = db.session.query(db.func.max(Order.id)).filter(Order.tenant_id == g.tenant.id).scalar() or 0
    return render_template(
        "admin/orders.html",
        latest_id=latest,
        orders=query.order_by(Order.id.desc()).limit(100).all(),
        status=status if status in ORDER_STATUSES else None,
        statuses=ORDER_STATUSES,
        channel_labels=CHANNELS,
        print_id=request.args.get("imprimir", type=int),
    )


@admin_bp.route("/pedidos/novos")
def orders_poll():
    """Consultado pelo painel a cada 15 s: pedidos com número maior que ?desde= e total de pendentes."""
    try:
        since = int(request.args.get("desde", ""))
    except ValueError:
        since = None
    base = Order.query.filter_by(tenant_id=g.tenant.id)
    new = base.filter(Order.id > since).order_by(Order.id).limit(20).all() if since is not None else []
    latest = db.session.query(db.func.max(Order.id)).filter(Order.tenant_id == g.tenant.id).scalar() or 0
    return {
        "latest": latest,
        "pending": base.filter_by(status="pendente").count(),
        "new": [{"id": o.id, "name": o.customer_name, "total": brl(o.total)} for o in new],
    }


@admin_bp.route("/pedidos/<int:order_id>/status", methods=["POST"])
def order_status(order_id):
    order = Order.query.filter_by(tenant_id=g.tenant.id, id=order_id).first_or_404()
    status = request.form.get("status")
    if status not in ORDER_STATUSES:
        abort(400)
    changed = status != order.status
    # 1ª confirmação: avisa o cliente, conta os selos e imprime. Reabrir um pedido (“Voltar para
    # confirmado”) não repete nada disso.
    first_confirmation = status == "confirmado" and not order.confirmed_at
    order.status = status
    if first_confirmation:
        order.confirmed_at = utcnow()
    if status == "entregue" and not order.delivered_at:
        order.delivered_at = utcnow()
    if status == "cancelado" and order.dispatch_id:  # sai da comanda do motoboy e da conta do dinheiro
        order.dispatch_id = None
    db.session.commit()
    if first_confirmation or (status == "cancelado" and changed):  # avisa no celular do cliente (se ele ativou)
        notify_order(g.tenant, order, status)
        if first_confirmation:
            notify_loyalty(g.tenant, order)
    current_filter = request.form.get("filter")
    # confirmou: manda o cupom para a impressora (a página de pedidos imprime sozinha)
    to_print = order.id if first_confirmation and g.tenant.auto_print else None
    return redirect(url_for("admin.orders", status=current_filter if current_filter in ORDER_STATUSES else None,
                            imprimir=to_print))


@admin_bp.route("/pedidos/<int:order_id>/pix", methods=["POST"])
def order_pix(order_id):
    """Dono conferiu no app do banco: marca (ou desmarca) o Pix como recebido."""
    order = Order.query.filter_by(tenant_id=g.tenant.id, id=order_id).first_or_404()
    if order.payment_method != "Pix":
        abort(400)
    order.pix_paid_at = None if order.pix_paid_at else utcnow()
    db.session.commit()
    if order.pix_paid_at:
        notify_order(g.tenant, order, "pix")
    flash(f"Pedido #{order.id}: " + ("Pix marcado como recebido." if order.pix_paid_at else "Pix voltou para “conferir”."), "ok")
    current_filter = request.form.get("filter")
    return redirect(url_for("admin.orders", status=current_filter if current_filter in ORDER_STATUSES else None))


@admin_bp.route("/pedidos/<int:order_id>/etiqueta")
def order_label(order_id):
    order = Order.query.filter_by(tenant_id=g.tenant.id, id=order_id).first_or_404()
    return render_template("admin/label.html", o=order, channel_labels=CHANNELS)


@admin_bp.route("/pedidos/<int:order_id>/impresso", methods=["POST"])
def order_printed(order_id):
    order = Order.query.filter_by(tenant_id=g.tenant.id, id=order_id).first_or_404()
    order.printed_at = utcnow()
    db.session.commit()
    return {"ok": True}


# ---------- cardápio ----------

def category_sizes(category):
    """Tamanhos da linha como [(rótulo, máx. de sabores)], na ordem definida no painel."""
    return [(s["label"], s["max_flavors"]) for s in category.sizes()]


def _category_or_404(category_id):
    return Category.query.filter_by(tenant_id=g.tenant.id, id=category_id).first_or_404()


def save_category_look(category, form):
    """Subtítulo, ícone e cor do título da categoria no site (valor desconhecido volta ao padrão)."""
    if "icon" not in form:
        return
    category.subtitle = " ".join(form.get("subtitle", "").split())[:80] or None
    category.icon = form["icon"] if form["icon"] in CATEGORY_ICONS else "fatia"
    category.accent = form.get("accent") if form.get("accent") in CATEGORY_ACCENTS else "vermelho"


def _category_url(category_id, anchor=None):
    return redirect(url_for("admin.category_page", category_id=category_id, _anchor=anchor))


@admin_bp.route("/cardapio")
def menu():
    categories = Category.query.filter_by(tenant_id=g.tenant.id).order_by(Category.sort_order, Category.id).all()
    return render_template("admin/menu_overview.html", categories=categories)


@admin_bp.route("/cardapio/nova")
def category_new():
    return render_template("admin/category_new.html")


@admin_bp.route("/cardapio/<int:category_id>")
def category_page(category_id):
    category = _category_or_404(category_id)
    combo_lines = Category.query.filter(
        Category.tenant_id == g.tenant.id, Category.kind.notin_(("metro", "bebida"))
    ).order_by(Category.sort_order).all()
    return render_template("admin/category.html", c=category, sizes=category_sizes(category), combo_lines=combo_lines,
                           icons=CATEGORY_ICONS, accents=CATEGORY_ACCENTS)


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
            if "border_field" in form:
                product.accepts_border = f"border-{product.id}" in form
            for variant in list(product.variants):
                if f"price-{variant.id}" not in form:
                    continue
                if form[f"price-{variant.id}"].strip():
                    variant.price = _price(form[f"price-{variant.id}"], f"{product.name} ({variant.label})", positive=True)
                else:  # preço em branco: o sabor deixa de ter esse tamanho
                    product.variants.remove(variant)
            have = {v.label for v in product.variants}
            for i, (label, max_flavors) in enumerate(category_sizes(category)):
                text = form.get(f"newv-{product.id}-{i}", "").strip()
                if text and label not in have:
                    price = _price(text, f"{product.name} ({label})", positive=True)
                    product.variants.append(ProductVariant(label=label, max_flavors=max_flavors, price=price))
            if not product.variants:
                raise FormError(f"“{product.name}” precisa ter preço em pelo menos um tamanho. Para tirar do ar, use a aba Estoque.")
        _save(f"{category.name}: alterações salvas.")
    except FormError as e:
        _reject(e)
    return _category_url(category.id)


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
                accepts_border="border" in form if "border_field" in form else True,
                variants=variants,
            )
        )
        _save(f"“{name}” adicionado em {category.name}.")
    except FormError as e:
        _reject(e)
    return _category_url(category.id)


MAX_COMBO_FLAVORS = 6


@admin_bp.route("/cardapio/<int:category_id>/combo", methods=["POST"])
def combo_save(category_id):
    category = _category_or_404(category_id)
    if category.kind != "metro":
        abort(400)
    form = request.form
    try:
        category.name = _name(form.get("name"), "o nome do combo", max_length=80)
        save_category_look(category, form)
        lines = Category.query.filter(Category.tenant_id == g.tenant.id, Category.kind.notin_(("metro", "bebida")))
        valid = {c.slug for c in lines}
        sources = [s for s in form.getlist("sources") if s in valid]
        if not sources:
            raise FormError("Marque pelo menos uma categoria de onde o cliente escolhe os sabores do combo.")
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
    return _category_url(category.id)


# ---------- relatórios ----------

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]


def _date(text):
    try:
        return date.fromisoformat(text or "")
    except ValueError:
        return None


def _period_label(start, end):
    if start == end:
        return f"{start.day} de {MONTHS[start.month - 1]} de {start.year}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day} a {end.day} de {MONTHS[start.month - 1]} de {start.year}"
    return f"{start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}"


@admin_bp.route("/relatorios")
def reports():
    today = datetime.now(STORE_TZ).date()
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    presets = [
        ("Hoje", today, today),
        ("Ontem", today - timedelta(days=1), today - timedelta(days=1)),
        ("Últimos 7 dias", today - timedelta(days=6), today),
        ("Este mês", month_start, today),
        ("Mês passado", last_month_end.replace(day=1), last_month_end),
    ]
    start = _date(request.args.get("inicio")) or month_start
    end = _date(request.args.get("fim")) or today
    if end < start:
        start, end = end, start
    end = min(end, start + timedelta(days=366))  # no máximo um ano por consulta
    report = sales_report(g.tenant, start, end)
    cal_month = _date((request.args.get("mes") or "") + "-01") or end.replace(day=1)
    prev_month = (cal_month - timedelta(days=1)).replace(day=1)
    next_month = (cal_month + timedelta(days=32)).replace(day=1)
    return render_template(
        "admin/reports.html",
        r=report,
        period=_period_label(start, end),
        presets=presets,
        weeks=month_calendar(g.tenant, cal_month.year, cal_month.month),
        cal_label=f"{MONTHS[cal_month.month - 1]} de {cal_month.year}",
        cal_month=cal_month,
        prev_month=prev_month,
        next_month=next_month,
        today=today,
    )


# ---------- clientes ----------

def customer_rows(tenant_id, q=""):
    """Clientes com nº de pedidos confirmados, total gasto e data do último pedido."""
    stats = dict(
        (cid, (n, total, last))
        for cid, n, total, last in db.session.query(
            Order.customer_id, db.func.count(Order.id), db.func.sum(Order.total), db.func.max(Order.created_at)
        )
        .filter(Order.tenant_id == tenant_id, Order.status.in_(SOLD_STATUSES), Order.customer_id.isnot(None))
        .group_by(Order.customer_id)
    )
    last_any = dict(
        db.session.query(Order.customer_id, db.func.max(Order.created_at))
        .filter(Order.tenant_id == tenant_id, Order.customer_id.isnot(None))
        .group_by(Order.customer_id)
    )
    query = Customer.query.filter_by(tenant_id=tenant_id)
    q = q.strip()
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = Customer.name.ilike(f"%{q}%")
        if digits:
            cond = cond | Customer.phone_key.like(f"%{digits}%")
        query = query.filter(cond)
    rows = []
    for c in query:
        n, total, _ = stats.get(c.id, (0, None, None))
        rows.append({
            "customer": c,
            "orders": n,
            "spent": Decimal(str(total)) if total is not None else Decimal("0"),
            "last_order": last_any.get(c.id),
        })
    rows.sort(key=lambda r: r["last_order"] or datetime.min, reverse=True)
    return rows


@admin_bp.route("/clientes")
def customers():
    q = request.args.get("q", "")
    rows = customer_rows(g.tenant.id, q)
    from app.routes.loyalty_admin import loyalty_cards

    return render_template("admin/customers.html", rows=rows[:300], total=len(rows), q=q, loyalty_cards=loyalty_cards)


@admin_bp.route("/clientes/<int:customer_id>/apagar", methods=["POST"])
def customer_erase(customer_id):
    customer = Customer.query.filter_by(tenant_id=g.tenant.id, id=customer_id).first_or_404()
    name = customer.name
    erase_customer(customer)
    db.session.commit()
    flash(f"Dados de “{name}” apagados. Os valores dos pedidos continuam nos relatórios.", "ok")
    return redirect(url_for("admin.customers"))


# ---------- fotos ----------

@admin_bp.route("/fotos")
def photos():
    categories = Category.query.filter(Category.tenant_id == g.tenant.id, Category.kind != "metro")
    return render_template("admin/photos.html", categories=categories.order_by(Category.sort_order, Category.id).all())


def _product_or_404(product_id):
    return Product.query.filter_by(tenant_id=g.tenant.id, id=product_id).first_or_404()


@admin_bp.route("/fotos/<int:product_id>", methods=["POST"])
def photo_upload(product_id):
    product = _product_or_404(product_id)
    # foto enviada da página da categoria volta para ela; da aba Fotos, volta para a aba
    back = (_category_url(product.category_id) if request.form.get("back")
            else redirect(url_for("admin.photos", _anchor=f"p-{product.id}")))
    file = request.files.get("photo")
    if not file or not file.filename:
        flash("Escolha uma foto para enviar.", "error")
        return back
    try:
        new = save_photo(file.stream, g.tenant.slug)
    except PhotoError as e:
        flash(str(e), "error")
        return back
    old, product.image = product.image, new
    db.session.commit()
    delete_photo(old)
    flash(f"Foto de “{product.name}” salva.", "ok")
    return back


@admin_bp.route("/fotos/<int:product_id>/remover", methods=["POST"])
def photo_remove(product_id):
    product = _product_or_404(product_id)
    old, product.image = product.image, None
    db.session.commit()
    delete_photo(old)
    flash(f"Foto de “{product.name}” removida.", "ok")
    return redirect(url_for("admin.photos", _anchor=f"p-{product.id}"))


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
                    if f"border-name-{border.id}" in form:
                        if f"border-group-{border.id}" in form:
                            border.group_name = _name(form[f"border-group-{border.id}"], "o tipo da borda", max_length=40)
                        border.name = _name(form[f"border-name-{border.id}"], "o recheio da borda", max_length=60)
                    border.price = _price(form[f"border-price-{border.id}"], f"borda {border.name}")
                    border.active = f"border-active-{border.id}" in form
            _save_border_groups(form, borders)
            for addon in addons:
                if f"addon-whole-{addon.id}" in form:
                    if f"addon-name-{addon.id}" in form:
                        addon.name = _name(form[f"addon-name-{addon.id}"], "o nome do adicional", max_length=80)
                    addon.price_whole = _price(form[f"addon-whole-{addon.id}"], f"adicional {addon.name} (inteira)")
                    addon.price_half = _price(form.get(f"addon-half-{addon.id}"), f"adicional {addon.name} (broto)")
                    addon.active = f"addon-active-{addon.id}" in form
            _save("Bordas e adicionais salvos.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.extras"))
    sizes, lines = pizza_sizes_and_lines()
    groups = {}
    for b in borders:
        groups.setdefault(b.group_name, []).append(b)
    return render_template(
        "admin/extras.html", borders=borders, addons=addons, sizes=sizes, lines=lines,
        groups=[{"name": name, "borders": bs, "rules": bs[0].rules()} for name, bs in groups.items()],
    )


def pizza_sizes_and_lines():
    """Tamanhos (sem repetir) e categorias de pizza, onde borda faz sentido; bebida e combo ficam de fora."""
    lines = Category.query.filter(Category.tenant_id == g.tenant.id, Category.kind.in_(("pizza", "doce"))).order_by(
        Category.sort_order, Category.id).all()
    sizes = []
    for c in lines:
        for s in c.sizes():
            if s["label"] not in sizes:
                sizes.append(s["label"])
    return sizes, lines


def _save_border_groups(form, borders):
    """Caixinhas “Onde aparece” de cada tipo de borda: grp-ids-N, grp-size-N, grp-cat-N."""
    sizes, lines = pizza_sizes_and_lines()
    by_id = {b.id: b for b in borders}
    for i in range(100):
        if f"grp-ids-{i}" not in form:
            continue
        group = [by_id[int(x)] for x in form[f"grp-ids-{i}"].split(",") if x.isdigit() and int(x) in by_id]
        if not group:
            continue
        on_sizes, on_lines = form.getlist(f"grp-size-{i}"), form.getlist(f"grp-cat-{i}")
        if not on_sizes or not on_lines:
            raise FormError(f"{group[0].group_name}: marque pelo menos um tamanho e uma categoria em “Onde aparece”. "
                            "Para tirar a borda do site, desmarque “à venda”.")
        if f"grp-name-{i}" in form:  # o nome do tipo aparece uma vez só, no topo do quadro
            group_name = _name(form[f"grp-name-{i}"], "o tipo da borda", max_length=40)
            for b in group:
                b.group_name = group_name
        rules = json.dumps({"no_sizes": [s for s in sizes if s not in on_sizes],
                            "no_categories": [c.slug for c in lines if c.slug not in on_lines]}, ensure_ascii=False)
        for b in group:
            b.rules_json = rules


# ---------- entrega ----------

@admin_bp.route("/entrega", methods=["GET", "POST"])
def delivery():
    hoods = Neighborhood.query.filter_by(tenant_id=g.tenant.id).order_by(Neighborhood.name).all()
    if request.method == "POST":
        form = request.form
        try:
            for hood in hoods:
                if f"fee-{hood.id}" in form:
                    if f"name-{hood.id}" in form:
                        hood.name = _name(form[f"name-{hood.id}"], "o nome do bairro")
                    hood.fee = _price(form[f"fee-{hood.id}"], f"taxa de {hood.name}")
                    hood.active = f"active-{hood.id}" in form
            _save("Taxas de entrega salvas.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.delivery"))
    return render_template("admin/delivery.html", hoods=hoods)


MAX_KM = Decimal("100")


def _optional_money(text, what):
    return None if not str(text or "").strip() else _price(text, what)


def _optional_km(text, what):
    text = str(text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        km = Decimal(text)
    except ArithmeticError:
        km = None
    if km is None or not km.is_finite() or not 0 < km <= MAX_KM:
        raise FormError(f"Valor inválido {what}: “{text}”. Use um número de km, ex.: 8 ou 7,5.")
    return km.quantize(Decimal("0.1"))


def _locate_store(tenant, coords_text):
    """Põe a loja no mapa: coordenadas coladas do Google Maps ou o endereço da aba Loja."""
    from app.services.geo import geocode, parse_coords

    if coords_text.strip():
        coords = parse_coords(coords_text)
        if not coords:
            raise FormError("Coordenadas inválidas. No Google Maps, toque e segure no ponto da pizzaria e copie "
                            "os números que aparecem, ex.: -23.2641, -47.2995.")
        tenant.store_lat, tenant.store_lng = coords
        return
    address = (tenant.address or "").strip()
    if not address:
        raise FormError("Preencha o endereço da pizzaria na aba Loja para acharmos ela no mapa.")
    point = geocode(q=address) or geocode(q=re.sub(r"\d+", " ", address))
    if not point:
        raise FormError(f"Não achamos “{address}” no mapa. Confira o endereço na aba Loja (rua, número, cidade e "
                        "estado) ou cole as coordenadas do Google Maps no campo abaixo.")
    tenant.store_lat, tenant.store_lng = point["lat"], point["lng"]
    tenant.store_city, tenant.store_uf = point["city"] or tenant.store_city, point["uf"] or tenant.store_uf


@admin_bp.route("/entrega/modo", methods=["POST"])
def delivery_mode():
    """Como cobrar a entrega: por bairro (tabela) ou por distância (km até a loja)."""
    tenant, form = g.tenant, request.form
    mode = form.get("delivery_mode")
    try:
        if mode not in ("bairro", "km"):
            raise FormError("Escolha como cobrar a entrega.")
        if mode == "km":
            tenant.km_price = _price(form.get("km_price"), "o preço por km", positive=True)
            tenant.km_base_km = _optional_km(form.get("km_base_km"), "na distância da taxa fixa")
            tenant.km_base_fee = _optional_money(form.get("km_base_fee"), "a taxa fixa")
            if (tenant.km_base_km is None) != (tenant.km_base_fee is None):
                raise FormError("Para a taxa fixa de perto, preencha os dois campos: até quantos km e o valor. "
                                "Para cobrar só pelo km, deixe os dois em branco.")
            tenant.km_max = _optional_km(form.get("km_max"), "na distância máxima")
            if form.get("store_coords", "").strip() or form.get("relocate") or tenant.store_lat is None:
                _locate_store(tenant, form.get("store_coords", ""))
        tenant.delivery_mode = mode
        _save("Entrega pela distância salva." if mode == "km" else "Entrega por bairro salva.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.delivery"))


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

MIN_TIME, MAX_TIME = 5, 180


def _minutes_field(text, what):
    try:
        value = int(str(text).strip())
    except (TypeError, ValueError):
        value = 0
    if not MIN_TIME <= value <= MAX_TIME:
        raise FormError(f"{what}: use um número de minutos entre {MIN_TIME} e {MAX_TIME}.")
    return value


@admin_bp.route("/loja/tempo", methods=["POST"])
def store_time():
    """Botões −5 / +5 do Início: ajusta o tempo de entrega ou de retirada na hora."""
    field = {"entrega": "eta_minutes", "retirada": "pickup_minutes"}.get(request.form.get("which"))
    try:
        delta = int(request.form.get("delta", "0"))
    except ValueError:
        delta = 0
    if not field or abs(delta) > 60:
        abort(400)
    value = min(MAX_TIME, max(MIN_TIME, getattr(g.tenant, field) + delta))
    setattr(g.tenant, field, value)
    db.session.commit()
    flash(f"Tempo de {request.form['which']} agora: {value} min. Vale para os próximos pedidos.", "ok")
    return redirect(url_for("admin.index"))


def _minutes(text):
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(text or ""))
    return int(match[1]) * 60 + int(match[2]) if match else None


LATEST_NEXT_DAY_CLOSE = 6 * 60  # fechar até as 06:00 = madrugada do dia seguinte; depois disso é engano


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
                opens, closes = _minutes(form.get(f"open-{day}")), _minutes(form.get(f"close-{day}"))
                if opens is not None and closes is not None and closes < opens and closes <= LATEST_NEXT_DAY_CLOSE:
                    closes += 1440  # fecha depois da meia-noite, na madrugada do dia seguinte
                valid = opens is not None and closes is not None and opens < closes
                if f"closed-{day}" in form:
                    # dia fechado guarda o horário digitado, para valer quando o dono reabrir o dia
                    hours[str(day)] = [opens, closes, 0] if valid else None
                    continue
                if not valid:
                    raise FormError(
                        f"Horário inválido em {WEEKDAYS[day]}: o fechamento precisa ser depois da abertura "
                        "(ou de madrugada, até as 06:00)."
                    )
                hours[str(day)] = [opens, closes]
            if "name" in form:
                tenant.name = _name(form.get("name"), "o nome da loja")
                tenant.address = form.get("address", "").strip()[:255]
                tenant.instagram = form.get("instagram", "").strip().lstrip("@")[:120]
            if "slogan" in form:
                tenant.slogan = " ".join(form["slogan"].split())[:120] or None
            if "other_payments" in form:
                chosen = [p for p in PAYMENT_OPTIONS if p in form.getlist("payments")]
                chosen += [p.strip()[:30] for p in form["other_payments"].split(",") if p.strip()]
                if not chosen:
                    raise FormError("Marque pelo menos uma forma de pagamento.")
                tenant.accepted_payments = ",".join(dict.fromkeys(chosen))
            if "pix_key_type" in form:
                _save_pix(tenant, form)
            if "notices" in form:
                lines = [" ".join(line.split())[:200] for line in form["notices"].splitlines() if line.strip()]
                tenant.notices = "\n".join(lines[:10])
            if "min_order" in form:
                text = form["min_order"].strip()
                tenant.min_order = _price(text, "pedido mínimo") if text else None
            if form.get("label_size") in LABEL_SIZES:
                tenant.label_width_mm, tenant.label_height_mm = LABEL_SIZES[form["label_size"]]
                tenant.auto_print = "auto_print" in form
            if "eta_minutes" in form:
                tenant.eta_minutes = _minutes_field(form["eta_minutes"], "Tempo de entrega")
                tenant.pickup_minutes = _minutes_field(form.get("pickup_minutes"), "Tempo para retirada")
            tenant.whatsapp = whatsapp
            tenant.is_open_override = STORE_STATUS[form["status"]]
            tenant.hours_json = json.dumps(hours)
            _save("Dados da loja salvos.")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.store"))

    hours = json.loads(tenant.hours_json) if tenant.hours_json else {}
    fmt = lambda m: f"{m % 1440 // 60:02d}:{m % 60:02d}"  # noqa: E731
    days = [
        {"n": d, "name": WEEKDAYS[d],
         "closed": not hours.get(str(d)) or (len(hours[str(d)]) > 2 and not hours[str(d)][2]),
         "open": fmt(hours[str(d)][0]) if hours.get(str(d)) else "18:00",
         "close": fmt(hours[str(d)][1]) if hours.get(str(d)) else "22:00"}
        for d in (1, 2, 3, 4, 5, 6, 0)
    ]
    status = next(k for k, v in STORE_STATUS.items() if v is tenant.is_open_override)
    payments = [p for p in (tenant.accepted_payments or "").split(",") if p]
    return render_template(
        "admin/store.html", days=days, status=status, payment_options=PAYMENT_OPTIONS, label_sizes=LABEL_NAMES,
        label_size=f"{tenant.label_width_mm}x{tenant.label_height_mm}",
        payments=payments, other_payments=", ".join(p for p in payments if p not in PAYMENT_OPTIONS),
        pix_types=PIX_KEY_TYPES,
    )


def _save_pix(tenant, form):
    """Chave Pix do QR Code do site. Chave em branco desliga o Pix pelo site."""
    text = form.get("pix_key", "").strip()
    if not text:
        tenant.pix_key = tenant.pix_key_type = tenant.pix_name = tenant.pix_city = None
        return
    try:
        tenant.pix_key = normalize_pix_key(form.get("pix_key_type"), text)
    except PixKeyError as e:
        raise FormError(str(e)) from None
    tenant.pix_key_type = form.get("pix_key_type")
    tenant.pix_name = " ".join(form.get("pix_name", "").split())[:25] or None
    city = " ".join(form.get("pix_city", "").split())[:15]
    if not city:
        raise FormError("Pix: informe a cidade da loja (ex.: Itu).")
    tenant.pix_city = city
