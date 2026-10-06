import os

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-troque-em-producao")

    _db_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'snep.db')}")
    # Fly.io/Heroku às vezes fornecem "postgres://", o SQLAlchemy exige "postgresql://"
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEFAULT_TENANT_SLUG = os.environ.get("DEFAULT_TENANT_SLUG", "snep")

    # Nome usado nas mensagens de pedido enviadas via WhatsApp
    SITE_NAME = "Delivery"
