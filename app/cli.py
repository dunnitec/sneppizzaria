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
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    click.echo(f"Usuário '{username}' {'criado' if created else 'atualizado'}. Painel: /{slug}/admin/")
