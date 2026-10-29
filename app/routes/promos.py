"""Painel: promoções (desconto em categorias, sabores e tamanhos, com dias e período)."""

import json
from datetime import date
from decimal import Decimal

from flask import flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Category, Promotion
from app.routes.admin import FormError, _name, _price, _reject, admin_bp
from app.services.photos import PhotoError, delete_photo, save_photo
from app.services.promotions import WEEKDAY_NAMES, describe, discounted, status, store_today

MAX_PERCENT = 90
POPUP_IMAGE_SIDE = 1200
# ordem dos dias no formulário: segunda a domingo (0 = domingo no banco)
FORM_DAYS = [1, 2, 3, 4, 5, 6, 0]


def _promo_or_404(promo_id):
    return Promotion.query.filter_by(tenant_id=g.tenant.id, id=promo_id).first_or_404()


def _categories():
    return Category.query.filter_by(tenant_id=g.tenant.id).order_by(Category.sort_order, Category.id).all()


def _date(text, what):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FormError(f"Data inválida em {what}.") from None


def examples(promo, limit=4):
    """Alguns preços “de / por” para o dono conferir a promoção."""
    rows, skipped = [], []
    cat = promo.category
    ids = promo.product_id_list()
    for p in cat.products:
        if ids and p.id not in ids:
            continue
        for v in p.variants:
            if promo.size_label and v.label != promo.size_label:
                continue
            new = discounted(promo, v.price)
            label = p.name if cat.kind == "metro" else f"{p.name} {v.label}"
            if new < v.price:
                rows.append({"label": label, "regular": v.price, "price": new})
            else:
                skipped.append(label)
    return rows[:limit], len(rows), skipped


def _fill(promo, form):
    promo.name = _name(form.get("name"), "o nome da promoção", max_length=60)
    promo.message = " ".join(form.get("message", "").split())[:200] or None
    category = Category.query.filter_by(tenant_id=g.tenant.id, id=form.get("category_id", type=int)).first()
    if not category:
        raise FormError("Escolha em qual categoria vale a promoção.")
    promo.category_id, promo.category = category.id, category

    if category.kind != "metro" and form.get(f"which-{category.id}") == "some":
        valid = {p.id for p in category.products}
        ids = [int(x) for x in form.getlist(f"products-{category.id}") if x.isdigit() and int(x) in valid]
        if not ids:
            raise FormError("Marque pelo menos um sabor, ou escolha “Todos os sabores”.")
        promo.product_ids = json.dumps(ids)
    else:
        promo.product_ids = None

    sizes = [s["label"] for s in category.sizes()] if category.kind != "metro" else []
    size = form.get(f"size-{category.id}", "")
    if size and size not in sizes:
        raise FormError("Tamanho inválido. Atualize a página.")
    promo.size_label = size or None

    kind = form.get("discount_type")
    if kind == "percent":
        try:
            value = Decimal(form.get("percent", "").replace(",", ".").replace("%", "").strip())
        except Exception:
            raise FormError("Informe o desconto em %, por exemplo 15.") from None
        if not 1 <= value <= MAX_PERCENT:
            raise FormError(f"O desconto vai de 1% a {MAX_PERCENT}%.")
        promo.value = value.quantize(Decimal("0.01"))
    elif kind == "price":
        if len(sizes) > 1 and not promo.size_label:
            raise FormError("Preço fixo vale para um tamanho só: escolha o tamanho (ex.: Grande).")
        if not promo.size_label and sizes:
            # categoria de um tamanho só: grava esse tamanho, senão um tamanho criado depois (mais caro)
            # entraria na promoção com o mesmo preço fixo
            promo.size_label = sizes[0]
        promo.value = _price(form.get("price"), "o preço promocional", positive=True)
    else:
        raise FormError("Escolha o tipo de desconto: porcentagem ou preço fixo.")
    promo.discount_type = kind

    days = sorted({int(d) for d in form.getlist("days") if d.isdigit() and 0 <= int(d) <= 6})
    if not days:
        raise FormError("Marque pelo menos um dia da semana.")
    promo.weekdays = None if len(days) == 7 else ",".join(map(str, days))
    promo.starts_on = _date(form.get("starts_on"), "Começa em")
    promo.ends_on = _date(form.get("ends_on"), "Termina em")
    if promo.starts_on and promo.ends_on and promo.ends_on < promo.starts_on:
        raise FormError("A data de término é antes da data de início.")
    promo.show_popup = "show_popup" in form
    promo.active = "active" in form

    file = request.files.get("photo")
    if file and file.filename:
        try:
            name = save_photo(file.stream, g.tenant.slug, max_side=POPUP_IMAGE_SIDE)
        except PhotoError as e:
            raise FormError(str(e)) from None
        old, promo.image = promo.image, name
        if old:
            delete_photo(old)
    elif "remove_photo" in form and promo.image:
        delete_photo(promo.image)
        promo.image = None


@admin_bp.route("/promocoes")
def promos():
    today = store_today()
    rows = []
    for p in Promotion.query.filter_by(tenant_id=g.tenant.id).order_by(Promotion.id.desc()):
        code, text = status(p, today)
        sample, total, skipped = examples(p)
        rows.append({"p": p, "code": code, "status": text, "text": describe(p), "sample": sample, "total": total,
                     "skipped": skipped})
    order = {"no_ar": 0, "hoje_nao": 1, "agendada": 2, "pausada": 3, "encerrada": 4}
    rows.sort(key=lambda r: order[r["code"]])
    return render_template("admin/promos.html", rows=rows)


@admin_bp.route("/promocoes/nova", methods=["GET", "POST"])
@admin_bp.route("/promocoes/<int:promo_id>", methods=["GET", "POST"])
def promo_edit(promo_id=None):
    promo = _promo_or_404(promo_id) if promo_id else None
    if request.method == "POST":
        is_new = promo is None
        if is_new:
            promo = Promotion(tenant_id=g.tenant.id)
        try:
            _fill(promo, request.form)
        except FormError as e:
            _reject(e)
            if is_new:
                promo = None
            else:
                db.session.refresh(promo)
            return _form(promo, request.form), 400
        if is_new:
            db.session.add(promo)
        db.session.commit()
        sample, total, skipped = examples(promo)
        if not total:
            flash(f"“{promo.name}” foi salva, mas não baixa o preço de nenhum item: confira o valor "
                  "(o preço promocional precisa ser menor que o normal).", "error")
        else:
            msg = f"Promoção “{promo.name}” salva."
            code, text = status(promo)
            msg += " Já está no ar no site." if code == "no_ar" else f" Situação: {text.lower()}."
            if skipped:
                msg += f" Não vale para: {', '.join(skipped[:5])} (o preço normal já é menor)."
            flash(msg, "ok")
        return redirect(url_for("admin.promos"))
    return _form(promo, None)


def _form(promo, posted):
    cats = [c for c in _categories() if c.products]
    sizes = {c.id: ([s["label"] for s in c.sizes()] if c.kind != "metro" else []) for c in cats}
    cats_json = json.dumps({c.id: {"kind": c.kind, "products": [
        {"id": p.id, "name": p.name, "variants": [{"label": v.label, "price": float(v.price)} for v in p.variants]}
        for p in c.products]} for c in cats}, ensure_ascii=False).replace("</", "<\\/")
    return render_template("admin/promo_form.html", promo=promo, posted=posted, cats=cats, sizes=sizes, cats_json=cats_json,
                           days=[(d, WEEKDAY_NAMES[d]) for d in FORM_DAYS], max_percent=MAX_PERCENT)


@admin_bp.route("/promocoes/<int:promo_id>/pausar", methods=["POST"])
def promo_toggle(promo_id):
    promo = _promo_or_404(promo_id)
    promo.active = not promo.active
    db.session.commit()
    flash(f"Promoção “{promo.name}” {'ligada de novo' if promo.active else 'pausada: saiu do site'}.", "ok")
    return redirect(url_for("admin.promos"))


@admin_bp.route("/promocoes/<int:promo_id>/excluir", methods=["POST"])
def promo_delete(promo_id):
    promo = _promo_or_404(promo_id)
    name, image = promo.name, promo.image
    db.session.delete(promo)
    db.session.commit()
    delete_photo(image)
    flash(f"Promoção “{name}” excluída.", "ok")
    return redirect(url_for("admin.promos"))


