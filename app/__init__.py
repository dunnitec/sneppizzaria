import mimetypes

from flask import Flask

# fotos e banners são .webp; algumas instalações (Windows) não conhecem esse tipo
mimetypes.add_type("image/webp", ".webp")

from app.config import DEV_SECRET_KEY, Config
from app.extensions import csrf, db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    if app.config["PRODUCTION"] and app.config["SECRET_KEY"] == DEV_SECRET_KEY:
        raise RuntimeError("Defina a variável SECRET_KEY em produção (ela protege o login do painel).")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from app.cli import create_admin, import_photos, import_static_banners
    from app.routes import admin_manage  # noqa: F401  (rotas extras do painel, mesmo blueprint)
    from app.routes.admin import admin_bp
    from app.routes.orders import orders_bp
    from app.routes.public import public_bp, static_url
    from app.services.customers import format_phone
    from app.services.hours import local_time
    from app.services.money import brl, money_input

    app.register_blueprint(public_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(admin_bp)
    # o pedido é uma API pública em JSON, sem sessão para proteger; o painel segue protegido
    csrf.exempt(orders_bp)

    app.cli.add_command(create_admin)
    app.cli.add_command(import_photos)
    app.cli.add_command(import_static_banners)
    app.jinja_env.filters.update(phone=format_phone, brl=brl, money_input=money_input, local_time=local_time)
    app.jinja_env.globals.update(static_url=static_url)

    return app
