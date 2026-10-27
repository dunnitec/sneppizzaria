"""Nova pizzaria na plataforma: cria a loja, o usuário do dono e, se pedido, copia o cardápio de outra loja.

Usado pelo painel da plataforma (/plataforma/). A cópia leva categorias, sabores com preços e fotos,
bordas e adicionais; não leva bairros, promoções, fidelidade, clientes nem pedidos.
"""

import json
import re
import secrets
import shutil
import unicodedata

from app.extensions import db
from app.models import AdminUser, Addon, Border, Category, Product, ProductVariant, Tenant
from app.services.photos import upload_folder

# endereços que não podem virar nome de loja (/<slug>/)
RESERVED_SLUGS = {"plataforma", "static", "uploads", "admin", "api", "www", "app"}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# loja nova: aberta todos os dias das 18:00 às 23:00 (o dono ajusta em Loja)
DEFAULT_HOURS = {str(d): [18 * 60, 23 * 60] for d in range(7)}


class SetupError(ValueError):
    """Dado inválido no cadastro da pizzaria; a mensagem vai para a tela."""


def slugify(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40]


def check_slug(slug):
    if not (3 <= len(slug) <= 40 and SLUG.fullmatch(slug)):
        raise SetupError("Endereço inválido: use de 3 a 40 letras minúsculas, números e hífen (ex.: pizzaria-do-joao).")
    if slug in RESERVED_SLUGS or Tenant.query.filter_by(slug=slug).first():
        raise SetupError(f"O endereço “{slug}” já está em uso. Escolha outro.")
    return slug


def new_password():
    """Senha provisória fácil de ditar: 3 grupos de letras e números (o dono troca no 1º acesso)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def _copy_photo(name, slug):
    """Cada loja tem a própria cópia do arquivo: apagar a foto numa loja não some com a da outra."""
    if not name:
        return None
    src = upload_folder() / name
    if not src.exists():
        return None
    copy = f"{slug}-{secrets.token_hex(6)}{src.suffix}"
    shutil.copyfile(src, upload_folder() / copy)
    return copy


def _clone(row, **changes):
    data = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "id"}
    data.update(changes)
    return type(row)(**data)


def copy_menu(source, target):
    """Copia o cardápio de uma loja para outra (que ainda não tem cardápio)."""
    for cat in Category.query.filter_by(tenant_id=source.id).order_by(Category.sort_order, Category.id):
        new_cat = _clone(cat, tenant_id=target.id, banner_image=_copy_photo(cat.banner_image, target.slug))
        db.session.add(new_cat)
        db.session.flush()
        for prod in Product.query.filter_by(category_id=cat.id).order_by(Product.id):
            new_prod = _clone(prod, tenant_id=target.id, category_id=new_cat.id, image=_copy_photo(prod.image, target.slug))
            db.session.add(new_prod)
            db.session.flush()
            for v in ProductVariant.query.filter_by(product_id=prod.id).order_by(ProductVariant.id):
                db.session.add(_clone(v, product_id=new_prod.id))
    for model in (Border, Addon):
        for row in model.query.filter_by(tenant_id=source.id).order_by(model.id):
            db.session.add(_clone(row, tenant_id=target.id))


def create_tenant(name, slug, whatsapp, plan, owner_username="dono", copy_from=None):
    """Cria a pizzaria e o usuário do dono. Devolve (loja, senha provisória do dono)."""
    from app.services.plans import PLANS

    name = " ".join(str(name or "").split())
    if not 2 <= len(name) <= 120:
        raise SetupError("Informe o nome da pizzaria.")
    slug = check_slug(slugify(slug or name))
    whatsapp = re.sub(r"\D", "", str(whatsapp or ""))
    if not re.fullmatch(r"55\d{10,11}", whatsapp):
        raise SetupError("WhatsApp inválido. Use 55 + DDD + número, ex.: 5511973937104.")
    if plan not in PLANS:
        raise SetupError("Escolha o plano.")
    owner_username = str(owner_username or "").strip().lower() or "dono"
    if not re.fullmatch(r"[a-z0-9._-]{3,60}", owner_username):
        raise SetupError("Usuário do dono inválido: use de 3 a 60 letras minúsculas, números, ponto ou hífen.")

    tenant = Tenant(name=name, slug=slug, whatsapp=whatsapp, plan=plan, active=True,
                    hours_json=json.dumps(DEFAULT_HOURS))
    db.session.add(tenant)
    db.session.flush()
    password = new_password()
    owner = AdminUser(tenant_id=tenant.id, username=owner_username, role="dono", password_changed=False)
    owner.set_password(password)
    db.session.add(owner)
    if copy_from:
        copy_menu(copy_from, tenant)
    db.session.commit()
    return tenant, password


def reset_owner_password(tenant):
    """Senha provisória nova para o dono (ele esqueceu). Devolve (usuário, senha)."""
    owner = (AdminUser.query.filter_by(tenant_id=tenant.id, role="dono").order_by(AdminUser.id).first())
    if not owner:
        raise SetupError("Esta loja não tem usuário dono.")
    password = new_password()
    owner.set_password(password)
    owner.password_changed = False
    owner.failed_attempts, owner.locked_until = 0, None
    db.session.commit()
    return owner.username, password
