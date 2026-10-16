"""Painel: criação e exclusão de itens do cardápio, visual do site e usuários.

Complementa app/routes/admin.py (mesmo blueprint, mesmas regras de login e CSRF).
"""

import json
import re

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from app.extensions import db
from app.models import (
    MIN_PASSWORD_LENGTH,
    Addon,
    AdminUser,
    Banner,
    Border,
    Category,
    Neighborhood,
    OrderItemFlavor,
    Product,
    ProductVariant,
)
from app.routes.admin import FormError, _category_or_404, _category_url, _name, _price, _reject, _save, admin_bp
from app.services.photos import PhotoError, delete_photo, normalize, save_photo

MAX_SIZE_FLAVORS = 6
BANNER_SIDE = 1600
ROLES = {"dono": "Dono (acesso a tudo)", "funcionario": "Funcionário (só pedidos)"}


def _back(category_id=None, anchor=None):
    """Volta para a página da categoria ou, sem categoria, para o resumo do cardápio."""
    return _category_url(category_id, anchor) if category_id else redirect(url_for("admin.menu"))


def _max_flavors(text, what):
    try:
        n = int(text)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= MAX_SIZE_FLAVORS:
        raise FormError(f"{what}: o máximo de sabores vai de 1 a {MAX_SIZE_FLAVORS}.")
    return n


def _unique_slug(name):
    base = normalize(name).replace(" ", "-") or "linha"
    taken = {c.slug for c in Category.query.filter_by(tenant_id=g.tenant.id)}
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _ordered_categories():
    cats = Category.query.filter_by(tenant_id=g.tenant.id).order_by(Category.sort_order, Category.id).all()
    for i, c in enumerate(cats):
        c.sort_order = i
    return cats


# ---------- categorias (no código: Category; o dono vê "categoria") ----------

def _new_sizes(form, kind):
    """Tamanhos do formulário de nova categoria: size_label-0, size_max-0, ... (ou o par antigo size_label/size_max)."""
    pairs = [(form.get(f"size_label-{i}", ""), form.get(f"size_max-{i}")) for i in range(20)]
    if form.get("size_label"):
        pairs.insert(0, (form["size_label"], form.get("size_max")))
    sizes = []
    for label, max_text in pairs:
        if not label.strip():
            continue
        label = _name(label, "o nome do tamanho", max_length=30)
        sizes.append({"label": label, "max_flavors": 1 if kind == "bebida" else _max_flavors(max_text, label)})
    if not sizes:
        raise FormError("Informe pelo menos um tamanho (ex.: Inteira, ou Lata 350ml para bebida).")
    labels = [s["label"].lower() for s in sizes]
    if len(set(labels)) != len(labels):
        raise FormError("Há dois tamanhos com o mesmo nome.")
    return sizes


@admin_bp.route("/cardapio/linha/nova", methods=["POST"])
def line_new():
    form = request.form
    try:
        name = _name(form.get("name"), "o nome da categoria", max_length=80)
        kind = form.get("kind") if form.get("kind") in ("pizza", "doce", "bebida") else "pizza"
        sizes = _new_sizes(form, kind)
        cats = _ordered_categories()
        combos = [c for c in cats if c.kind == "metro"]
        position = combos[0].sort_order if combos else len(cats)  # nova linha entra antes do combo
        for c in cats:
            if c.sort_order >= position:
                c.sort_order += 1
        category = Category(
            tenant_id=g.tenant.id, name=name, slug=_unique_slug(name), kind=kind,
            allows_addons=kind != "bebida" and "allows_addons" in form, sort_order=position,
            sizes_json=json.dumps(sizes, ensure_ascii=False),
        )
        db.session.add(category)
        _save(f"Categoria “{name}” criada. Agora cadastre os itens com os preços.")
        db.session.refresh(category)
        return _back(category.id, "adicionar")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.category_new"))


@admin_bp.route("/cardapio/<int:category_id>/linha", methods=["POST"])
def line_save(category_id):
    category = _category_or_404(category_id)
    if category.kind == "metro":
        abort(400)
    form = request.form
    try:
        category.name = _name(form.get("name"), "o nome da categoria", max_length=80)
        category.allows_addons = "allows_addons" in form
        old_sizes = category.sizes()
        new_sizes, renames, removed = [], {}, []
        for i, size in enumerate(old_sizes):
            if f"size-del-{i}" in form:
                removed.append(size["label"])
                continue
            label = _name(form.get(f"size-label-{i}", size["label"]), "o nome do tamanho", max_length=30)
            n = 1 if category.kind == "bebida" else _max_flavors(form.get(f"size-max-{i}"), label)
            new_sizes.append({"label": label, "max_flavors": n})
            renames[size["label"]] = new_sizes[-1]
        if form.get("new_size_label", "").strip():
            label = _name(form["new_size_label"], "o nome do novo tamanho", max_length=30)
            n = 1 if category.kind == "bebida" else _max_flavors(form.get("new_size_max"), label)
            new_sizes.append({"label": label, "max_flavors": n})
        labels = [s["label"].lower() for s in new_sizes]
        if not new_sizes:
            raise FormError("A categoria precisa ter pelo menos um tamanho.")
        if len(set(labels)) != len(labels):
            raise FormError("Há dois tamanhos com o mesmo nome.")
        orphans = [p.name for p in category.products if p.variants and all(v.label in removed for v in p.variants)]
        if orphans:
            raise FormError(f"Não dá para remover esse tamanho: {', '.join(orphans[:5])} só tem(êm) ele. "
                            "Coloque o preço de outro tamanho nesses itens primeiro, ou exclua os itens.")
        for product in category.products:
            for variant in list(product.variants):
                if variant.label in removed:
                    product.variants.remove(variant)
                elif variant.label in renames:  # renames: nome antigo -> tamanho novo
                    size = renames[variant.label]
                    variant.label, variant.max_flavors = size["label"], size["max_flavors"]
        category.sizes_json = json.dumps(new_sizes, ensure_ascii=False)
        _save(f"Configurações de “{category.name}” salvas.")
    except FormError as e:
        _reject(e)
    return _back(category.id)


@admin_bp.route("/cardapio/<int:category_id>/mover", methods=["POST"])
def line_move(category_id):
    category = _category_or_404(category_id)
    cats = _ordered_categories()
    i = cats.index(category)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(cats):
        cats[i].sort_order, cats[j].sort_order = cats[j].sort_order, cats[i].sort_order
    db.session.commit()
    return _back()


@admin_bp.route("/cardapio/<int:category_id>/excluir", methods=["POST"])
def line_delete(category_id):
    category = _category_or_404(category_id)
    if category.kind == "metro":
        abort(400)
    name, slug = category.name, category.slug
    for product in list(category.products):
        _delete_product(product)
    for combo in Category.query.filter_by(tenant_id=g.tenant.id, kind="metro"):
        sources = combo.combo_settings()["sources"]
        if slug in sources:
            combo.combo_sources = json.dumps([s for s in sources if s != slug])
    db.session.delete(category)
    db.session.commit()
    flash(f"Categoria “{name}” e os itens dela foram excluídos.", "ok")
    return _back()


# ---------- sabores ----------

def _delete_product(product):
    OrderItemFlavor.query.filter_by(product_id=product.id).update({"product_id": None})
    image = product.image
    db.session.delete(product)
    delete_photo(image)


@admin_bp.route("/cardapio/sabor/<int:product_id>/excluir", methods=["POST"])
def product_delete(product_id):
    product = Product.query.filter_by(tenant_id=g.tenant.id, id=product_id).first_or_404()
    name, category_id = product.name, product.category_id
    _delete_product(product)
    db.session.commit()
    flash(f"“{name}” excluído. Os pedidos antigos continuam nos relatórios.", "ok")
    return _back(category_id)


# ---------- bordas e adicionais ----------

@admin_bp.route("/extras/borda/nova", methods=["POST"])
def border_new():
    form = request.form
    try:
        group = _name(form.get("group"), "o tipo da borda", max_length=40)
        name = _name(form.get("name"), "o recheio da borda", max_length=60)
        db.session.add(Border(tenant_id=g.tenant.id, group_name=group, name=name, price=_price(form.get("price"), f"borda {name}")))
        _save(f"Borda “{group} — {name}” criada.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.extras"))


@admin_bp.route("/extras/borda/<int:border_id>/excluir", methods=["POST"])
def border_delete(border_id):
    border = Border.query.filter_by(tenant_id=g.tenant.id, id=border_id).first_or_404()
    db.session.delete(border)
    db.session.commit()
    flash(f"Borda “{border.group_name} — {border.name}” excluída.", "ok")
    return redirect(url_for("admin.extras"))


@admin_bp.route("/extras/adicional/novo", methods=["POST"])
def addon_new():
    form = request.form
    try:
        name = _name(form.get("name"), "o nome do adicional", max_length=80)
        db.session.add(Addon(
            tenant_id=g.tenant.id, name=name,
            price_whole=_price(form.get("price_whole"), f"adicional {name} (inteira)"),
            price_half=_price(form.get("price_half"), f"adicional {name} (broto)"),
        ))
        _save(f"Adicional “{name}” criado.")
    except FormError as e:
        _reject(e)
    return redirect(url_for("admin.extras"))


@admin_bp.route("/extras/adicional/<int:addon_id>/excluir", methods=["POST"])
def addon_delete(addon_id):
    addon = Addon.query.filter_by(tenant_id=g.tenant.id, id=addon_id).first_or_404()
    db.session.delete(addon)
    db.session.commit()
    flash(f"Adicional “{addon.name}” excluído.", "ok")
    return redirect(url_for("admin.extras"))


# ---------- bairros ----------

@admin_bp.route("/entrega/<int:hood_id>/excluir", methods=["POST"])
def delivery_delete(hood_id):
    hood = Neighborhood.query.filter_by(tenant_id=g.tenant.id, id=hood_id).first_or_404()
    db.session.delete(hood)
    db.session.commit()
    flash(f"Bairro “{hood.name}” excluído.", "ok")
    return redirect(url_for("admin.delivery"))


# ---------- visual: banners e fundo ----------

def _ordered_banners():
    banners = Banner.query.filter_by(tenant_id=g.tenant.id).order_by(Banner.sort_order, Banner.id).all()
    for i, b in enumerate(banners):
        b.sort_order = i
    return banners


@admin_bp.route("/visual")
def visual():
    return render_template("admin/visual.html", banners=_ordered_banners())


def _uploaded_image():
    file = request.files.get("photo")
    if not file or not file.filename:
        raise PhotoError("Escolha uma imagem para enviar.")
    return save_photo(file.stream, g.tenant.slug, max_side=BANNER_SIDE)


@admin_bp.route("/visual/banner", methods=["POST"])
def banner_new():
    try:
        name = _uploaded_image()
    except PhotoError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.visual"))
    db.session.add(Banner(tenant_id=g.tenant.id, image=name, sort_order=len(_ordered_banners())))
    db.session.commit()
    flash("Banner adicionado ao carrossel.", "ok")
    return redirect(url_for("admin.visual"))


@admin_bp.route("/visual/banner/<int:banner_id>/mover", methods=["POST"])
def banner_move(banner_id):
    banners = _ordered_banners()
    banner = next((b for b in banners if b.id == banner_id), None) or abort(404)
    i = banners.index(banner)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(banners):
        banners[i].sort_order, banners[j].sort_order = banners[j].sort_order, banners[i].sort_order
    db.session.commit()
    return redirect(url_for("admin.visual"))


@admin_bp.route("/visual/banner/<int:banner_id>/excluir", methods=["POST"])
def banner_delete(banner_id):
    banner = Banner.query.filter_by(tenant_id=g.tenant.id, id=banner_id).first_or_404()
    image = banner.image
    db.session.delete(banner)
    db.session.commit()
    delete_photo(image)
    flash("Banner removido.", "ok")
    return redirect(url_for("admin.visual"))


@admin_bp.route("/visual/fundo", methods=["POST"])
def background_upload():
    try:
        name = _uploaded_image()
    except PhotoError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.visual"))
    old, g.tenant.background_image = g.tenant.background_image, name
    db.session.commit()
    delete_photo(old)
    flash("Imagem de fundo trocada.", "ok")
    return redirect(url_for("admin.visual"))


@admin_bp.route("/visual/fundo/remover", methods=["POST"])
def background_remove():
    old, g.tenant.background_image = g.tenant.background_image, None
    db.session.commit()
    delete_photo(old)
    flash("Imagem de fundo removida; o site volta ao fundo padrão.", "ok")
    return redirect(url_for("admin.visual"))


# ---------- usuários ----------

USERNAME = re.compile(r"[a-z0-9._-]{1,60}")


@admin_bp.route("/usuarios", methods=["GET", "POST"])
def users():
    if request.method == "POST":
        form = request.form
        username = form.get("username", "").strip().lower()
        role = form.get("role") if form.get("role") in ROLES else "funcionario"
        if not USERNAME.fullmatch(username):
            flash("Usuário inválido: use letras minúsculas, números, ponto, hífen ou _ (sem espaço).", "error")
        elif AdminUser.query.filter_by(tenant_id=g.tenant.id, username=username).first():
            flash(f"Já existe o usuário “{username}”.", "error")
        elif len(form.get("password", "")) < MIN_PASSWORD_LENGTH:
            flash(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.", "error")
        else:
            user = AdminUser(tenant_id=g.tenant.id, username=username, role=role)
            user.set_password(form["password"])
            db.session.add(user)
            db.session.commit()
            flash(f"Usuário “{username}” criado. Passe a senha para a pessoa e peça para ela trocar.", "ok")
        return redirect(url_for("admin.users"))
    accounts = AdminUser.query.filter_by(tenant_id=g.tenant.id).order_by(AdminUser.username).all()
    return render_template("admin/users.html", accounts=accounts, roles=ROLES)


def _user_or_404(user_id):
    return AdminUser.query.filter_by(tenant_id=g.tenant.id, id=user_id).first_or_404()


@admin_bp.route("/usuarios/<int:user_id>/senha", methods=["POST"])
def user_password(user_id):
    user = _user_or_404(user_id)
    password = request.form.get("password", "")
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.", "error")
    else:
        user.set_password(password)
        user.failed_attempts, user.locked_until = 0, None
        db.session.commit()
        flash(f"Senha de “{user.username}” redefinida.", "ok")
    return redirect(url_for("admin.users"))


@admin_bp.route("/usuarios/<int:user_id>/excluir", methods=["POST"])
def user_delete(user_id):
    user = _user_or_404(user_id)
    if user.id == g.admin.id:
        flash("Você não pode excluir o próprio usuário.", "error")
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f"Usuário “{user.username}” excluído.", "ok")
    return redirect(url_for("admin.users"))


# ---------- estoque: liga/desliga rápido, salva na hora ----------

STOCK_TYPES = {"product": Product, "variant": ProductVariant, "border": Border, "addon": Addon}


@admin_bp.route("/estoque")
def stock():
    categories = Category.query.filter_by(tenant_id=g.tenant.id).order_by(Category.sort_order, Category.id).all()
    return render_template(
        "admin/stock.html",
        categories=[c for c in categories if c.products],
        borders=Border.query.filter_by(tenant_id=g.tenant.id).order_by(Border.id).all(),
        addons=Addon.query.filter_by(tenant_id=g.tenant.id).order_by(Addon.id).all(),
    )


def _stock_item(kind, item_id):
    model = STOCK_TYPES.get(kind)
    if model is None or not isinstance(item_id, int):
        abort(400)
    if model is ProductVariant:
        item = ProductVariant.query.join(Product).filter(ProductVariant.id == item_id, Product.tenant_id == g.tenant.id).first()
    else:
        item = model.query.filter_by(tenant_id=g.tenant.id, id=item_id).first()
    return item or abort(404)


@admin_bp.route("/estoque/alternar", methods=["POST"])
def stock_toggle():
    data = request.get_json(silent=True) or {}
    item = _stock_item(data.get("type"), data.get("id"))
    item.active = bool(data.get("active"))
    db.session.commit()
    return jsonify(ok=True, active=item.active)


@admin_bp.route("/estoque/lote", methods=["POST"])
def stock_bulk():
    """Liga ou desliga vários sabores de uma vez (ex.: todos que levam calabresa)."""
    data = request.get_json(silent=True) or {}
    ids = [i for i in data.get("ids") or [] if isinstance(i, int)][:500]
    products = Product.query.filter(Product.tenant_id == g.tenant.id, Product.id.in_(ids)).all() if ids else []
    for p in products:
        p.active = bool(data.get("active"))
    db.session.commit()
    return jsonify(ok=True, changed=len(products))
