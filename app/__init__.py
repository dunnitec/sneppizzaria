from flask import Flask

from app.config import Config
from app.extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.routes.public import public_bp
    from app.routes.orders import orders_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(orders_bp)

    return app
