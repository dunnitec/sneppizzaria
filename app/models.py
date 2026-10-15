import json
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

MIN_PASSWORD_LENGTH = 8


def split_options(text):
    """'Guaraná, Guaraná Zero' -> ['Guaraná', 'Guaraná Zero']"""
    return [o.strip() for o in (text or "").split(",") if o.strip()]


def utcnow():
    """Data/hora atual em UTC, sem fuso (como as colunas DateTime guardam)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminUser(db.Model):
    """Quem pode entrar no painel (/<slug>/admin/) de uma loja."""

    __tablename__ = "admin_users"
    __table_args__ = (db.UniqueConstraint("tenant_id", "username", name="uq_admin_users_tenant_username"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    username = db.Column(db.String(60), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # nunca a senha em si
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)  # bloqueio temporário após senhas erradas seguidas
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Tenant(db.Model):
    """Uma pizzaria/loja dentro da plataforma multi-tenant."""

    __tablename__ = "tenants"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)  # ex: "snep"
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    instagram = db.Column(db.String(120))
    whatsapp = db.Column(db.String(30))  # formato E.164 sem "+", ex: 5511973937104
    schedule_text = db.Column(db.Text)  # texto livre exibido no cabeçalho
    is_open_override = db.Column(db.Boolean, default=None, nullable=True)  # forçar aberto/fechado manualmente
    logo_url = db.Column(db.String(255))
    banner_url = db.Column(db.String(255))
    accepted_payments = db.Column(db.String(255), default="Dinheiro,Pix,Débito,Crédito")
    hours_json = db.Column(db.Text)  # {"0":[1080,1310],"1":null,...} minutos, 0=domingo
    eta = db.Column(db.String(30), default="40-50 min")  # tempo de entrega exibido
    created_at = db.Column(db.DateTime, default=utcnow)

    categories = db.relationship("Category", backref="tenant", lazy=True, order_by="Category.sort_order")
    neighborhoods = db.relationship("Neighborhood", backref="tenant", lazy=True)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)  # Pizzas Promocionais, Pizzas Premium, Pizzas Doces
    slug = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(20), default="pizza")  # pizza | doce | metro
    allows_addons = db.Column(db.Boolean, default=False, nullable=False)  # linha aceita adicionais por ingrediente
    sort_order = db.Column(db.Integer, default=0)

    # só para kind="metro" (combo de preço fixo), editável no painel
    combo_sources = db.Column(db.Text)  # JSON: slugs das linhas de onde saem os sabores, ex. ["premium"]
    combo_extras = db.Column(db.Text)  # o que acompanha o combo, um item por linha
    combo_choice_label = db.Column(db.String(60))  # pergunta ao cliente, ex. "Sabor do Kuat 2L"
    combo_choice_options = db.Column(db.String(255))  # respostas separadas por vírgula; vazio = sem pergunta

    def combo_settings(self):
        """Configuração do combo já interpretada (listas no lugar de texto)."""
        sources = json.loads(self.combo_sources) if self.combo_sources else []
        return {
            "sources": sources,
            "extras": [line.strip() for line in (self.combo_extras or "").splitlines() if line.strip()],
            "choice_label": self.combo_choice_label or "",
            "choice_options": split_options(self.combo_choice_options),
        }

    products = db.relationship("Product", backref="category", lazy=True, order_by="Product.name")


class Product(db.Model):
    """Um sabor de pizza (linha do cardápio)."""

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)  # ingredientes
    image = db.Column(db.String(255))  # arquivo da foto em UPLOAD_FOLDER (services/photos.py)
    active = db.Column(db.Boolean, default=True)

    variants = db.relationship(
        "ProductVariant", backref="product", lazy=True, cascade="all, delete-orphan", order_by="ProductVariant.id"
    )


class ProductVariant(db.Model):
    """Tamanho/preço de um produto: Grande (promocional), Broto ou Inteira (premium/doce)."""

    __tablename__ = "product_variants"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    label = db.Column(db.String(30), nullable=False)  # "Grande (8 pedaços)", "Broto", "Inteira"
    max_flavors = db.Column(db.Integer, default=1)  # quantos sabores podem ser combinados nessa variante
    price = db.Column(db.Numeric(8, 2), nullable=False)


class Addon(db.Model):
    """Adicional por ingrediente (só disponível na linha Premium)."""

    __tablename__ = "addons"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    price_whole = db.Column(db.Numeric(8, 2), nullable=False)  # inteira
    price_half = db.Column(db.Numeric(8, 2), nullable=False)  # meia
    active = db.Column(db.Boolean, default=True)


class Border(db.Model):
    """Borda recheada, agrupada por tipo (Tradicional, Caracol, Vulcão)."""

    __tablename__ = "borders"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    group_name = db.Column(db.String(40), nullable=False)  # Tradicional | Caracol | Vulcão
    name = db.Column(db.String(60), nullable=False)  # Catupiry, Cheddar, Mussarela com Bacon...
    price = db.Column(db.Numeric(8, 2), nullable=False)
    active = db.Column(db.Boolean, default=True)


class Neighborhood(db.Model):
    """Bairro atendido e taxa de entrega associada."""

    __tablename__ = "neighborhoods"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    fee = db.Column(db.Numeric(8, 2), nullable=False)
    active = db.Column(db.Boolean, default=True)


class Customer(db.Model):
    """Cliente cadastrado automaticamente no primeiro pedido (services/customers.py)."""

    __tablename__ = "customers"
    __table_args__ = (db.UniqueConstraint("tenant_id", "phone_key", name="uq_customers_tenant_phone"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)  # como o cliente digitou
    phone_key = db.Column(db.String(20), nullable=False)  # só dígitos, com DDD: identifica o cliente
    street = db.Column(db.String(200))  # último endereço de entrega
    number = db.Column(db.String(20))
    complement = db.Column(db.String(120))
    neighborhood = db.Column(db.String(120))
    reference = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow)


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)

    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True)
    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(30), nullable=False)

    street = db.Column(db.String(200))
    number = db.Column(db.String(20))
    complement = db.Column(db.String(120))
    neighborhood_name = db.Column(db.String(120))
    reference = db.Column(db.String(200))

    payment_method = db.Column(db.String(30))  # Dinheiro | Pix | Débito | Crédito
    change_for = db.Column(db.Numeric(8, 2))  # troco para quanto (se dinheiro)

    subtotal = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    delivery_fee = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(8, 2), nullable=False, default=0)

    status = db.Column(db.String(30), default="pendente")  # pendente | confirmado | cancelado
    whatsapp_message = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)

    product_names = db.Column(db.String(255), nullable=False)  # "Calabresa Acebolada" ou "1/2 Toscana + 1/2 Bauru"
    variant_label = db.Column(db.String(30))
    border_name = db.Column(db.String(60))
    addon_names = db.Column(db.String(255))
    extras = db.Column(db.String(255))  # o que acompanha um combo (brindes e escolha do cliente)
    notes = db.Column(db.String(255))

    unit_price = db.Column(db.Numeric(8, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    line_total = db.Column(db.Numeric(8, 2), nullable=False)


class OrderItemFlavor(db.Model):
    """Sabor de um item do pedido e a fração dele (1 = inteira, 0.5 = meia...). Alimenta o ranking de sabores."""

    __tablename__ = "order_item_flavors"

    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey("order_items.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    product_name = db.Column(db.String(120), nullable=False)  # nome na hora da venda
    share = db.Column(db.Numeric(6, 4), nullable=False)
