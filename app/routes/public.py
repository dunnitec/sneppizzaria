from pathlib import Path

from flask import Blueprint, abort, current_app, redirect, render_template, send_from_directory, url_for

from app.models import Tenant
from app.services.menu_data import PAY_ICONS, data_from_db

public_bp = Blueprint("public", __name__)


def get_tenant_or_404(slug):
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        abort(404)
    return tenant


def static_url(filename):
    """URL de um arquivo estático com a data de modificação (?v=...), para o navegador
    não mostrar a versão antiga guardada em cache depois que o arquivo é trocado."""
    path = Path(current_app.static_folder) / filename
    version = int(path.stat().st_mtime) if path.exists() else None
    return url_for("static", filename=filename, v=version)


def tenant_assets(tenant):
    """Banners e fundo enviados pelo painel; enquanto não houver, os padrões de app/static/img/<slug>/."""
    from app.models import Banner
    from app.services.photos import photo_url

    base = Path(current_app.static_folder) / "img" / tenant.slug
    url = lambda name: static_url(f"img/{tenant.slug}/{name}")  # noqa: E731
    banners = Banner.query.filter_by(tenant_id=tenant.id).order_by(Banner.sort_order, Banner.id).all()
    return {
        "logo": url("logo.webp") if (base / "logo.webp").exists() else "",
        "banners": [photo_url(b.image) for b in banners] or [url(p.name) for p in sorted(base.glob("banner*.webp"))],
        "fundo": photo_url(tenant.background_image) if tenant.background_image
        else (url("fundo.webp") if (base / "fundo.webp").exists() else ""),
    }


@public_bp.route("/uploads/<path:name>")
def uploaded_file(name):
    # nome com trecho aleatório: o arquivo nunca muda, pode ficar em cache por 1 ano
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], name, max_age=365 * 24 * 3600)


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
