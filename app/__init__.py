from flask import Flask

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

    from app.cli import create_admin
    from app.routes.admin import admin_bp
    from app.routes.orders import orders_bp
    from app.routes.public import public_bp
    from app.services.hours import local_time
    from app.services.money import brl, money_input

    app.register_blueprint(public_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(admin_bp)
    # o pedido é uma API pública em JSON, sem sessão para proteger; o painel segue protegido
    csrf.exempt(orders_bp)

    app.cli.add_command(create_admin)
    app.jinja_env.filters.update(brl=brl, money_input=money_input, local_time=local_time)

    return app
