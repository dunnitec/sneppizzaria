from pathlib import Path

import click

from app.extensions import db
from app.models import MIN_PASSWORD_LENGTH, AdminUser, Tenant


@click.command("create-admin")
@click.argument("slug")
@click.argument("username")
@click.option("--password", prompt="Senha", hide_input=True, confirmation_prompt="Repita a senha")
def create_admin(slug, username, password):
    """Cria o usuário do painel de uma loja (ou redefine a senha, se já existir).

    Exemplo: flask create-admin snep dono
    """
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        raise click.ClickException(f"Loja '{slug}' não encontrada. Rode o seed primeiro.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise click.ClickException(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")

    username = username.strip().lower()
    if not 1 <= len(username) <= 60:
        raise click.ClickException("O nome de usuário precisa ter de 1 a 60 caracteres.")
    user = AdminUser.query.filter_by(tenant_id=tenant.id, username=username).first()
    created = user is None
    if created:
        user = AdminUser(tenant_id=tenant.id, username=username)
        db.session.add(user)
    user.set_password(password)
    user.password_changed = False
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    click.echo(f"Usuário '{username}' {'criado' if created else 'atualizado'}. Painel: /{slug}/admin/")


@click.command("import-photos")
@click.argument("slug")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def import_photos(slug, folder):
    """Importa as fotos de uma pasta, casando o nome do arquivo com o nome do sabor.

    Aceita "Paulista.jpg" ou, quando o nome existe em mais de uma linha,
    "Premium - Toscana.jpg". Acentos, maiúsculas e "c/" x "com" não importam.
    """
    from app.models import Product
    from app.services.photos import IMAGE_EXTENSIONS, PhotoError, delete_photo, match_product, save_photo

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        raise click.ClickException(f"Loja '{slug}' não encontrada.")
    products = Product.query.filter_by(tenant_id=tenant.id).all()
    done, skipped = 0, []
    for path in sorted(Path(folder).iterdir()):
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        product = match_product(path.name, products)
        if not product:
            skipped.append(path.name)
            continue
        try:
            with path.open("rb") as f:
                new = save_photo(f, slug)
        except PhotoError:
            skipped.append(path.name)
            continue
        old, product.image = product.image, new
        db.session.commit()
        delete_photo(old)
        done += 1
        click.echo(f"ok  {path.name} -> {product.category.name} / {product.name}")
    click.echo(f"{done} foto(s) importada(s).")
    for name in skipped:
        click.echo(f"NÃO IMPORTADA (sabor não encontrado ou nome repetido em outra linha): {name}")


@click.command("import-static-banners")
@click.argument("slug")
def import_static_banners(slug):
    """Copia os banners padrão (app/static/img/<slug>/banner*.webp) para o painel, onde o dono passa a gerenciá-los.

    Não faz nada se a loja já tiver banners cadastrados.
    """
    from flask import current_app

    from app.models import Banner
    from app.services.photos import save_photo

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        raise click.ClickException(f"Loja '{slug}' não encontrada.")
    if Banner.query.filter_by(tenant_id=tenant.id).first():
        click.echo("A loja já tem banners no painel; nada a fazer.")
        return
    files = sorted((Path(current_app.static_folder) / "img" / slug).glob("banner*.webp"))
    for i, path in enumerate(files):
        with path.open("rb") as f:
            db.session.add(Banner(tenant_id=tenant.id, image=save_photo(f, slug, max_side=1600), sort_order=i))
    db.session.commit()
    click.echo(f"{len(files)} banner(s) copiado(s) para o painel.")
