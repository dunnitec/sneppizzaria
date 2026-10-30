import io
import json
import time
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, abort, current_app, make_response, redirect, render_template, request, send_from_directory, url_for
from PIL import Image, ImageDraw, ImageFont

from app.models import Tenant
from app.services.menu_data import PAY_ICONS, data_from_db

public_bp = Blueprint("public", __name__)


def get_tenant_or_404(slug):
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        abort(404)
    if not tenant.active:  # suspensa pela plataforma: site, pedidos e painel da loja ficam fora do ar
        abort(make_response(render_template("suspended.html", tenant=tenant), 503))
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
    from app.services.site_options import color_css, font_url

    return render_template("index.html", d=d, pay_icons=PAY_ICONS, inline=False, site_css=color_css(d["site"]),
                           font_url=font_url(d["site"]))


@public_bp.route("/<slug>/api/status")
def store_status(slug):
    """Aberta/fechada agora: o site e o painel consultam de tempos em tempos, para mudar sem recarregar."""
    from app.services.hours import is_open

    resp = make_response({"open": is_open(get_tenant_or_404(slug))})
    resp.headers["Cache-Control"] = "no-store"
    return resp


QUOTES_PER_10_MIN = 40
_quotes = defaultdict(deque)  # ip → horários das consultas de frete (protege o mapa grátis de abuso)


def fee_quote(tenant, args):
    """Frete por distância para o checkout (site e painel): preenche o endereço pelo CEP e calcula."""
    from app.services.geo import cep_digits, lookup_cep, quote

    cep = cep_digits(args.get("cep"))
    info = (lookup_cep(cep) if cep else None) or {}
    street = (args.get("street") or "").strip()[:200] or info.get("street", "")
    hood = (args.get("neighborhood") or "").strip()[:120] or info.get("neighborhood", "")
    q = quote(tenant, cep or "", street, hood, (args.get("number") or "").strip()[:20])
    return {"ok": True, "status": q["status"], "km": float(q["km"]) if q["km"] is not None else None,
            "fee": float(q["fee"]) if q["fee"] is not None else None, "cep_found": bool(info),
            "street": info.get("street", ""), "neighborhood": info.get("neighborhood", ""),
            "city": info.get("city", ""), "uf": info.get("uf", "")}


@public_bp.route("/<slug>/api/frete")
def delivery_quote(slug):
    tenant = get_tenant_or_404(slug)
    if tenant.delivery_mode != "km":
        abort(404)
    hits, now = _quotes[request.remote_addr or "?"], time.monotonic()
    while hits and now - hits[0] > 600:
        hits.popleft()
    if len(hits) >= QUOTES_PER_10_MIN:
        return {"ok": False, "error": "Muitas consultas seguidas. Espere alguns minutos."}, 429
    hits.append(now)
    resp = make_response(fee_quote(tenant, request.args))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- app no celular (PWA) ----------

ICON_SIZES = (96, 180, 192, 512)


@lru_cache(maxsize=64)
def _icon_png(upload_folder, image, letter, size, maskable):
    """Ícone quadrado: o logo enviado em Aparência (ou a inicial da loja) num fundo branco."""
    canvas = Image.new("RGB", (size, size), "white")
    if image:
        logo = Image.open(Path(upload_folder) / image).convert("RGBA")
        inner = int(size * (0.78 if maskable else 0.96))  # “maskable”: o Android recorta em círculo
        logo = logo.resize((inner, int(inner * logo.height / logo.width)), Image.LANCZOS)
        canvas.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    else:
        canvas = Image.new("RGB", (size, size), (227, 20, 27))
        font = None
        for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(name, int(size * 0.55))
                break
            except OSError:
                continue
        ImageDraw.Draw(canvas).text((size / 2, size / 2), letter, fill="white", anchor="mm",
                                    font=font or ImageFont.load_default())
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


@public_bp.route("/<slug>/icone-<int:size>.png")
@public_bp.route("/<slug>/icone-<int:size>-<variant>.png")
def app_icon(slug, size, variant=""):
    tenant = get_tenant_or_404(slug)
    if size not in ICON_SIZES or variant not in ("", "maskable"):
        abort(404)
    png = _icon_png(current_app.config["UPLOAD_FOLDER"], tenant.app_icon or "", (tenant.name or "?")[0].upper(),
                    size, variant == "maskable")
    resp = make_response(png)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@public_bp.route("/<slug>/manifest.webmanifest")
def manifest(slug):
    tenant = get_tenant_or_404(slug)
    icon = lambda size, purpose="any": {  # noqa: E731
        "src": url_for("public.app_icon", slug=slug, size=size, variant="maskable" if purpose == "maskable" else None),
        "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}
    data = {
        "name": tenant.name, "short_name": tenant.name[:12], "description": tenant.slogan or f"Peça na {tenant.name}",
        "id": f"/{slug}/", "start_url": f"/{slug}/?app=1", "scope": f"/{slug}/", "display": "standalone",
        "background_color": "#0b0b0c", "theme_color": "#0b0b0c", "lang": "pt-BR",
        "icons": [icon(192), icon(512), icon(512, "maskable")],
    }
    resp = make_response(json.dumps(data, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


@public_bp.route("/<slug>/sw.js")
def service_worker(slug):
    get_tenant_or_404(slug)
    resp = make_response(send_from_directory(current_app.static_folder, "js/sw.js", max_age=0))
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = f"/{slug}/"
    return resp
