import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

DEV_SECRET_KEY = "dev-key-troque-em-producao"


class Config:
    # APP_ENV=production é definido no Dockerfile/fly.toml; local fica desligado
    PRODUCTION = os.environ.get("APP_ENV") == "production"

    # assina o cookie de login do painel; em produção a aplicação não sobe sem uma chave própria
    SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)
    SESSION_COOKIE_SECURE = PRODUCTION
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    _db_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'snep.db')}")
    # Fly.io/Heroku às vezes fornecem "postgres://", o SQLAlchemy exige "postgresql://"
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEFAULT_TENANT_SLUG = os.environ.get("DEFAULT_TENANT_SLUG", "snep")

    # Nome usado nas mensagens de pedido enviadas via WhatsApp
    SITE_NAME = "Delivery"
