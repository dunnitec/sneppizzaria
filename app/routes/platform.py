"""Painel da plataforma (/plataforma/): quem vende o sistema cria pizzarias, muda o plano e suspende.

O dono da pizzaria não tem acesso: o login é outro (PlatformAdmin, criado com `flask create-platform-admin`).
"""

from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import MIN_PASSWORD_LENGTH, SOLD_STATUSES, AdminUser, Order, PlatformAdmin, Tenant, utcnow
from app.services.plans import FEATURES, PLANS
from app.services.tenant_setup import SetupError, create_tenant, reset_owner_password
from app.services.throttle import admin_logins

platform_bp = Blueprint("platform", __name__, url_prefix="/plataforma")

_DUMMY_HASH = generate_password_hash("usuario-inexistente")


def _session_key(user):
    # muda quando a senha muda, derrubando as sessões abertas com a senha antiga
    return user.password_hash[-16:]


@platform_bp.before_request
def _require_login():
    g.platform_admin = None
    user = db.session.get(PlatformAdmin, session.get("platform_id") or 0)
    if user and session.get("platform_key") == _session_key(user):
        g.platform_admin = user
    elif request.endpoint != "platform.login":
        return redirect(url_for("platform.login"))


@platform_bp.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@platform_bp.context_processor
def _template_context():
    return {"me": g.get("platform_admin"), "plans": PLANS, "features": FEATURES}


def _tenant_or_404(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        abort(404)
    return tenant


# ---------- login ----------

@platform_bp.route("/entrar", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        ip, account = request.remote_addr or "?", f"plataforma:{username}"
        if admin_logins.blocked(ip, account):  # bloqueio da conexão, não do usuário (services/throttle.py)
            flash("Muitas tentativas seguidas. Aguarde 15 minutos e tente de novo.", "error")
            return render_template("platform/login.html")
        user = PlatformAdmin.query.filter_by(username=username).first()
        if user is None:
            check_password_hash(_DUMMY_HASH, password)
        elif user.check_password(password):
            admin_logins.success(ip, account)
            # não usa session.clear(): quem estiver também logado no painel de uma loja continua logado lá
            session.permanent = True
            session["platform_id"] = user.id
            session["platform_key"] = _session_key(user)
            return redirect(url_for("platform.index"))
        admin_logins.fail(ip, account)
        flash("Usuário ou senha incorretos.", "error")
    return render_template("platform/login.html")


@platform_bp.route("/sair", methods=["POST"])
def logout():
    session.pop("platform_id", None)
    session.pop("platform_key", None)
    return redirect(url_for("platform.login"))


@platform_bp.route("/senha", methods=["GET", "POST"])
def password():
    if request.method == "POST":
        me = g.platform_admin
        new = request.form.get("new", "")
        if not me.check_password(request.form.get("current", "")):
            flash("A senha atual está errada.", "error")
        elif len(new) < MIN_PASSWORD_LENGTH or new != request.form.get("confirm", ""):
            flash(f"A senha nova precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres e ser repetida igual.", "error")
        else:
            me.set_password(new)
            db.session.commit()
            session["platform_key"] = _session_key(me)
            flash("Senha trocada.", "ok")
            return redirect(url_for("platform.index"))
    return render_template("platform/password.html")


# ---------- pizzarias ----------

@platform_bp.route("/")
def index():
    since = utcnow() - timedelta(days=30)
    stats = dict(
        (tid, (count, total)) for tid, count, total in db.session.query(
            Order.tenant_id, func.count(Order.id), func.coalesce(func.sum(Order.total), 0)
        ).filter(Order.created_at >= since, Order.status.in_(SOLD_STATUSES)).group_by(Order.tenant_id)
    )
    last = dict(db.session.query(Order.tenant_id, func.max(Order.created_at)).group_by(Order.tenant_id))
    tenants = Tenant.query.order_by(Tenant.active.desc(), Tenant.name).all()
    rows = [{"t": t, "orders": stats.get(t.id, (0, 0))[0], "sold": stats.get(t.id, (0, 0))[1], "last": last.get(t.id)}
            for t in tenants]
    counts = {"active": sum(1 for t in tenants if t.active), "suspended": sum(1 for t in tenants if not t.active)}
    return render_template("platform/index.html", rows=rows, counts=counts)


@platform_bp.route("/lojas/nova", methods=["GET", "POST"])
def tenant_new():
    sources = Tenant.query.order_by(Tenant.name).all()
    if request.method == "POST":
        form = request.form
        source = db.session.get(Tenant, int(form["copy_from"])) if form.get("copy_from", "").isdigit() else None
        try:
            tenant, password = create_tenant(form.get("name"), form.get("slug"), form.get("whatsapp"), form.get("plan"),
                                             form.get("owner_username"), copy_from=source)
        except SetupError as e:
            db.session.rollback()
            flash(str(e), "error")
            return render_template("platform/new.html", sources=sources, form=form)
        owner = AdminUser.query.filter_by(tenant_id=tenant.id, role="dono").first()
        return render_template("platform/created.html", t=tenant, username=owner.username, password=password,
                               copied=source, new=True)
    return render_template("platform/new.html", sources=sources, form={})


@platform_bp.route("/lojas/<int:tenant_id>", methods=["GET", "POST"])
def tenant_edit(tenant_id):
    tenant = _tenant_or_404(tenant_id)
    if request.method == "POST":
        form = request.form
        if form.get("plan") in PLANS:
            tenant.plan = form["plan"]
        tenant.active = form.get("active") == "1"
        tenant.platform_notes = form.get("platform_notes", "").strip()[:4000] or None
        db.session.commit()
        flash(f"{tenant.name}: {'no ar' if tenant.active else 'SUSPENSA (site e painel fora do ar)'}, "
              f"plano {PLANS[tenant.plan]['name']}.", "ok")
        return redirect(url_for("platform.tenant_edit", tenant_id=tenant.id))
    owners = AdminUser.query.filter_by(tenant_id=tenant.id).order_by(AdminUser.role, AdminUser.username).all()
    return render_template("platform/edit.html", t=tenant, users=owners)


@platform_bp.route("/lojas/<int:tenant_id>/senha-do-dono", methods=["POST"])
def owner_password(tenant_id):
    tenant = _tenant_or_404(tenant_id)
    try:
        username, password = reset_owner_password(tenant)
    except SetupError as e:
        flash(str(e), "error")
        return redirect(url_for("platform.tenant_edit", tenant_id=tenant.id))
    return render_template("platform/created.html", t=tenant, username=username, password=password, new=False)


@platform_bp.route("/lojas/<int:tenant_id>/abrir-painel", methods=["POST"])
def open_panel(tenant_id):
    """Entra no painel da loja como o dono, para ajudar na implantação ou no suporte."""
    tenant = _tenant_or_404(tenant_id)
    if not tenant.active:
        flash("A loja está suspensa: o painel dela fica fora do ar. Reative para entrar.", "error")
        return redirect(url_for("platform.tenant_edit", tenant_id=tenant.id))
    owner = AdminUser.query.filter_by(tenant_id=tenant.id, role="dono").order_by(AdminUser.id).first()
    if not owner:
        flash("Esta loja não tem usuário dono.", "error")
        return redirect(url_for("platform.tenant_edit", tenant_id=tenant.id))
    session["admin_id"] = owner.id
    session["admin_key"] = owner.password_hash[-16:]
    return redirect(url_for("admin.index", slug=tenant.slug))
