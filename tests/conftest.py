import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Tenant
from seed import seed_from_file

CARDAPIO = Path(__file__).resolve().parent.parent / "data" / "snep" / "cardapio.json"


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "chave-de-teste"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False


class CsrfConfig(TestConfig):
    WTF_CSRF_ENABLED = True


@contextmanager
def seeded_app(config):
    app = create_app(config)
    with app.app_context():
        db.create_all()
        seed_from_file(CARDAPIO)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def cardapio():
    return json.loads(CARDAPIO.read_text(encoding="utf-8"))


@pytest.fixture
def app():
    with seeded_app(TestConfig) as app:
        yield app


@pytest.fixture
def csrf_app():
    with seeded_app(CsrfConfig) as app:
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def tenant(app):
    return Tenant.query.filter_by(slug="snep").one()


@pytest.fixture
def open_store(tenant):
    """Deixa a loja aberta independente do horário em que o teste roda."""
    tenant.is_open_override = True
    db.session.commit()
    return tenant


@pytest.fixture(autouse=True)
def _clear_login_limits():
    """Bloqueios de login ficam em memória (services/throttle.py): cada teste começa limpo."""
    from app.services.throttle import admin_logins, customer_logins

    admin_logins.clear()
    customer_logins.clear()
