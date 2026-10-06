from datetime import datetime

from app.extensions import db


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    categories = db.relationship("Category", backref="tenant", lazy=True, order_by="Category.sort_order")
    neighborhoods = db.relationship("Neighborhood", backref="tenant", lazy=True)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)  # Pizzas Promocionais, Pizzas Premium, Pizzas Doces
    slug = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(20), default="pizza")  # pizza | doce | adicional
    sort_order = db.Column(db.Integer, default=0)

    products = db.relationship("Product", backref="category", lazy=True, order_by="Product.name")


class Product(db.Model):
    """Um sabor de pizza (linha do cardápio)."""

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)  # ingredientes
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
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)

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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)

    product_names = db.Column(db.String(255), nullable=False)  # "Calabresa Acebolada" ou "1/2 Toscana + 1/2 Bauru"
    variant_label = db.Column(db.String(30))
    border_name = db.Column(db.String(60))
    addon_names = db.Column(db.String(255))
    notes = db.Column(db.String(255))

    unit_price = db.Column(db.Numeric(8, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    line_total = db.Column(db.Numeric(8, 2), nullable=False)
