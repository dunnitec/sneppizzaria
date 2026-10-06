from pathlib import Path

from flask import Blueprint, abort, current_app, redirect, render_template, url_for

from app.models import Tenant
from app.services.menu_data import PAY_ICONS, data_from_db

public_bp = Blueprint("public", __name__)


def get_tenant_or_404(slug):
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        abort(404)
    return tenant


def tenant_assets(tenant):
    """Imagens em app/static/img/<slug>/: logo.webp, banner*.webp, fundo.webp (todas opcionais)."""
    base = Path(current_app.static_folder) / "img" / tenant.slug
    url = lambda name: url_for("static", filename=f"img/{tenant.slug}/{name}")  # noqa: E731
    return {
        "logo": url("logo.webp") if (base / "logo.webp").exists() else "",
        "banners": [url(p.name) for p in sorted(base.glob("banner*.webp"))],
        "fundo": url("fundo.webp") if (base / "fundo.webp").exists() else "",
    }


@public_bp.route("/")
def home_redirect():
    return redirect(url_for("public.menu", slug=current_app.config["DEFAULT_TENANT_SLUG"]))


@public_bp.route("/<slug>/")
def menu(slug):
    tenant = get_tenant_or_404(slug)
    d = data_from_db(
        tenant,
        order_url=url_for("orders.create_order", slug=slug),
        assets=tenant_assets(tenant),
    )
    return render_template("index.html", d=d, pay_icons=PAY_ICONS, inline=False)
