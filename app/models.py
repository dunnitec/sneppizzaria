import json
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

MIN_PASSWORD_LENGTH = 8


# etapas do pedido; as três do meio são venda feita e entram nos relatórios
ORDER_STATUSES = {
    "pendente": "Pendente",
    "confirmado": "Confirmado",
    "saiu": "Saiu para entrega",
    "entregue": "Entregue",
    "cancelado": "Cancelado",
}
SOLD_STATUSES = ("confirmado", "saiu", "entregue")
# aparência do título de cada categoria no site
CATEGORY_ICONS = {"fatia": "Fatia de pizza", "coroa": "Coroa", "trem": "Trem", "copo": "Copo", "estrela": "Estrela",
                  "fogo": "Fogo", "coracao": "Coração", "lanche": "Hambúrguer", "tigela": "Tigela (açaí, marmita)"}
CATEGORY_ACCENTS = {"vermelho": "Vermelho", "dourado": "Dourado", "rosa": "Rosa", "laranja": "Laranja", "verde": "Verde"}
# de onde veio o pedido
CHANNELS = {"site": "Site", "balcao": "Balcão", "mesa": "Mesa", "telefone": "Telefone/WhatsApp"}


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
    role = db.Column(db.String(20), nullable=False, default="dono", server_default="dono")  # dono | funcionario
    # False enquanto a senha for a provisória (criada no comando ou por outra pessoa); True depois que a pessoa troca
    password_changed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)  # bloqueio temporário após senhas erradas seguidas
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PlatformAdmin(db.Model):
    """Quem administra a plataforma (/plataforma/): cria pizzarias, muda plano, suspende. O dono da loja não entra aqui."""

    __tablename__ = "platform_admins"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
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
    eta = db.Column(db.String(30), default="40-50 min")  # (antigo) texto livre; o site usa eta_minutes
    eta_minutes = db.Column(db.Integer, nullable=False, default=50, server_default="50")  # tempo de entrega
    pickup_minutes = db.Column(db.Integer, nullable=False, default=25, server_default="25")  # pronto para retirar
    notices = db.Column(db.Text)  # recados do topo do cardápio, um por linha
    min_order = db.Column(db.Numeric(8, 2))  # pedido mínimo (sem a entrega); vazio = sem mínimo
    background_image = db.Column(db.String(255))  # fundo enviado pelo painel (UPLOAD_FOLDER)
    app_icon = db.Column(db.String(255))  # ícone do app instalado no celular (PWA), quadrado (UPLOAD_FOLDER)
    hero_image = db.Column(db.String(255))  # foto do topo do site, atrás da marca (UPLOAD_FOLDER)
    slogan = db.Column(db.String(120))  # frase abaixo da marca, ex.: “A melhor pizzaria de Itu”
    # Pix com QR Code no pedido feito pelo site (ver app/services/pix.py); sem chave, não aparece
    pix_key = db.Column(db.String(80))
    pix_key_type = db.Column(db.String(10))  # email | celular | cpf | aleatoria
    pix_name = db.Column(db.String(25))  # nome no código Pix (o app do banco mostra o titular da conta)
    pix_city = db.Column(db.String(15))
    # fidelidade antiga (um cartão só): substituída por LoyaltyProgram; ficam só para a migração de dados
    loyalty_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    loyalty_goal = db.Column(db.Integer, nullable=False, default=8, server_default="8")
    loyalty_kinds = db.Column(db.String(40), nullable=False, default="pizza,doce", server_default="pizza,doce")  # o que conta selo
    loyalty_reward_category_id = db.Column(db.Integer)  # categoria da pizza grátis (sem FK: evita ciclo tenants <-> categories)
    loyalty_reward_size = db.Column(db.String(60))  # tamanho da pizza grátis; vazio = qualquer
    # desconto no 1º pedido de quem se cadastra
    first_order_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    first_order_type = db.Column(db.String(10), nullable=False, default="percent", server_default="percent")  # percent | amount
    first_order_value = db.Column(db.Numeric(8, 2), nullable=False, default=10, server_default="10")
    # impressora de etiquetas (Zebra): tamanho da etiqueta e se imprime sozinho ao confirmar
    label_width_mm = db.Column(db.Integer, nullable=False, default=100, server_default="100")
    label_height_mm = db.Column(db.Integer, nullable=False, default=150, server_default="150")
    auto_print = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # frete: "bairro" (tabela Neighborhood) ou "km" (distância até a loja, ver services/geo.py)
    delivery_mode = db.Column(db.String(10), nullable=False, default="bairro", server_default="bairro")
    store_lat = db.Column(db.Float)  # ponto da loja no mapa (aba Entrega → Localizar a pizzaria)
    store_lng = db.Column(db.Float)
    store_cep = db.Column(db.String(8))  # CEP e número da loja, para achar no mapa (aba Entrega)
    store_number = db.Column(db.String(20))
    store_city = db.Column(db.String(80))  # cidade/UF da loja: usadas quando o cliente não sabe o CEP
    store_uf = db.Column(db.String(2))
    km_price = db.Column(db.Numeric(8, 2))  # R$ por km
    # pizzaria | lanchonete | acai | restaurante | doceria | outro (services/business.py): muda só palavras
    business_type = db.Column(db.String(20), nullable=False, default="pizzaria", server_default="pizzaria")
    payment_fees = db.Column(db.Text)  # JSON {"Débito": 1.99, "Crédito": 3.49}: taxa da maquininha em % (aba Custos)
    km_base_km = db.Column(db.Numeric(6, 1))  # até X km cobra a taxa fixa abaixo; acima, só km × km_price
    km_base_fee = db.Column(db.Numeric(8, 2))  # vazios = só km × km_price
    km_max = db.Column(db.Numeric(6, 1))  # entrega até X km; vazio = sem limite
    # acréscimo na entrega por tipo de endereço (o motoboy sobe no prédio / passa pela portaria); vazio = sem acréscimo
    fee_apartment = db.Column(db.Numeric(8, 2))
    fee_condo = db.Column(db.Numeric(8, 2))
    site_options = db.Column(db.Text)  # JSON: como o site aparece e funciona (services/site_options.py)
    # plataforma (só /plataforma/ muda): plano contratado e loja no ar ou suspensa (ver services/plans.py)
    plan = db.Column(db.String(20), nullable=False, default="completo", server_default="completo")
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    platform_notes = db.Column(db.Text)  # anotações internas: contato, valor combinado, vencimento
    created_at = db.Column(db.DateTime, default=utcnow)

    categories = db.relationship("Category", backref="tenant", lazy=True, order_by="Category.sort_order")
    neighborhoods = db.relationship("Neighborhood", backref="tenant", lazy=True)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)  # Pizzas Promocionais, Pizzas Premium, Pizzas Doces
    slug = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(20), default="pizza")  # pizza | doce | lanche | montar | metro (combo) | bebida
    allows_addons = db.Column(db.Boolean, default=False, nullable=False)  # linha aceita adicionais por ingrediente
    sort_order = db.Column(db.Integer, default=0)

    # só para kind="metro" (combo de preço fixo), editável no painel
    combo_sources = db.Column(db.Text)  # JSON: slugs das linhas de onde saem os sabores, ex. ["premium"]
    combo_extras = db.Column(db.Text)  # o que acompanha o combo, um item por linha
    combo_choice_label = db.Column(db.String(60))  # pergunta ao cliente, ex. "Sabor do Kuat 2L"
    combo_choice_options = db.Column(db.String(255))  # respostas separadas por vírgula; vazio = sem pergunta
    # tamanhos da linha: [{"label": "Broto", "max_flavors": 1}, ...]; os preços ficam em ProductVariant
    sizes_json = db.Column(db.Text)
    # como o título da categoria aparece no site (ver CATEGORY_ICONS e CATEGORY_ACCENTS)
    subtitle = db.Column(db.String(80))
    icon = db.Column(db.String(20), nullable=False, default="fatia", server_default="fatia")
    accent = db.Column(db.String(20), nullable=False, default="vermelho", server_default="vermelho")
    banner_image = db.Column(db.String(255))  # foto à direita do título (UPLOAD_FOLDER)
    # só para kind="montar" (açaí, marmita): complementos grátis, um por linha; quantos o cliente marca
    # em cada tamanho fica em ProductVariant.max_flavors
    pick_label = db.Column(db.String(60))  # ex.: "Complementos" ou "Acompanhamentos"
    pick_options = db.Column(db.Text)
    # custo estimado da linha em % do preço (aba Custos): vale para o sabor sem custo em R$, borda e adicionais
    cost_percent = db.Column(db.Numeric(5, 2))

    def sizes(self):
        if self.sizes_json:
            return json.loads(self.sizes_json)
        found = {}
        for product in self.products:
            for variant in product.variants:
                found.setdefault(variant.label, variant.max_flavors)
        return [{"label": label, "max_flavors": n} for label, n in found.items()]

    def pick_settings(self):
        """Complementos do “monte o seu”: {"label", "options": [...]}."""
        options = [" ".join(line.split()) for line in (self.pick_options or "").splitlines() if line.strip()]
        return {"label": self.pick_label or "Complementos", "options": options}

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
    # calzone, esfiha...: o cliente não escolhe borda; numa meio a meio com este sabor também não
    accepts_border = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())

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
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())  # tamanho em estoque
    cost = db.Column(db.Numeric(8, 2))  # quanto custa fazer (ingredientes + caixa), aba Custos; vazio = usa o % da linha


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
    cost = db.Column(db.Numeric(8, 2))  # custo do recheio (aba Custos); vazio = usa o % da linha da pizza
    active = db.Column(db.Boolean, default=True)
    # onde a borda NÃO aparece: {"no_sizes": ["Broto"], "no_categories": ["premium"]}; vazio = em todas.
    # Guardar o que fica de fora faz um tamanho ou categoria criados depois já virem liberados.
    rules_json = db.Column(db.Text)

    def rules(self):
        data = json.loads(self.rules_json) if self.rules_json else {}
        return {"no_sizes": data.get("no_sizes", []), "no_categories": data.get("no_categories", [])}

    def allowed_for(self, category_slug, size_label):
        rules = self.rules()
        return size_label not in rules["no_sizes"] and category_slug not in rules["no_categories"]


class Neighborhood(db.Model):
    """Bairro atendido e taxa de entrega associada."""

    __tablename__ = "neighborhoods"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    fee = db.Column(db.Numeric(8, 2), nullable=False)
    active = db.Column(db.Boolean, default=True)


class GeoCache(db.Model):
    """Consultas ao mapa já feitas (services/geo.py). lat/lng vazios = endereço não achado."""

    __tablename__ = "geo_cache"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False)
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    label = db.Column(db.String(255))
    city = db.Column(db.String(80))
    uf = db.Column(db.String(2))
    created_at = db.Column(db.DateTime, default=utcnow)

    def as_point(self):
        if self.lat is None or self.lng is None:
            return None
        return {"lat": self.lat, "lng": self.lng, "label": self.label or "", "city": self.city or "", "uf": self.uf or ""}


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
    residence = db.Column(db.String(12))  # casa | apartamento | condominio (RESIDENCES)
    building = db.Column(db.String(120))  # nome do prédio ou do condomínio
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow)
    # cadastro feito pelo próprio cliente no site (telefone + senha de números); sem isso, não entra na fidelidade
    pin_hash = db.Column(db.String(255))
    registered_at = db.Column(db.DateTime)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    locked_until = db.Column(db.DateTime)

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin):
        return bool(self.pin_hash) and check_password_hash(self.pin_hash, pin)


# tipo de endereço de entrega: o dono pode cobrar acréscimo para apartamento e condomínio (aba Entrega)
RESIDENCES = {"casa": "Casa", "apartamento": "Apartamento", "condominio": "Condomínio"}


class Order(db.Model):
    __tablename__ = "orders"
    __table_args__ = (db.UniqueConstraint("tenant_id", "client_ref", name="uq_orders_client_ref"),)

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
    cep = db.Column(db.String(8))
    residence = db.Column(db.String(12))  # casa | apartamento | condominio (RESIDENCES)
    building = db.Column(db.String(120))  # nome do prédio ou do condomínio
    distance_km = db.Column(db.Numeric(6, 1))  # frete por distância (services/geo.py)
    fee_pending = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # entrega a combinar
    # código que o site gera ao abrir “Finalizar pedido”: reenviar (internet caiu) não cria pedido repetido
    client_ref = db.Column(db.String(40))

    payment_method = db.Column(db.String(30))  # Dinheiro | Pix | Débito | Crédito
    change_for = db.Column(db.Numeric(8, 2))  # troco para quanto (se dinheiro)
    split_people = db.Column(db.Integer)  # dividir a conta em partes iguais entre N pessoas (services/split.py)

    subtotal = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    delivery_fee = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(8, 2), nullable=False, default=0)

    status = db.Column(db.String(30), default="pendente")  # ver ORDER_STATUSES
    whatsapp_message = db.Column(db.Text)
    channel = db.Column(db.String(20), nullable=False, default="site", server_default="site")  # ver CHANNELS
    delivery = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # True = entregar no endereço
    table_label = db.Column(db.String(20))  # mesa (pedido de comer na loja)
    dispatch_id = db.Column(db.Integer, db.ForeignKey("dispatches.id"), index=True)  # comanda de saída do motoboy
    printed_at = db.Column(db.DateTime)

    def residence_text(self):
        """'Apartamento · Edifício Solar' para o cupom e o painel; '' para casa ou sem informação."""
        if self.residence not in ("apartamento", "condominio"):
            return ""
        return RESIDENCES[self.residence] + (f" · {self.building}" if self.building else "")

    def split_text(self):
        """Como dividir a conta, para o cupom, o painel e o acompanhamento ('' = não divide)."""
        if not self.split_people:
            return ""
        from app.services.split import describe

        return describe(self.total, self.split_people) + (" (sem a entrega)" if self.fee_pending else "")

    def split_groups(self):
        """Partes agrupadas por valor, para o cupom: [(1, 33.34), (2, 33.33)]."""
        from app.services.split import groups

        return groups(self.total, self.split_people) if self.split_people else []
    delivered_at = db.Column(db.DateTime)
    pix_paid_at = db.Column(db.DateTime)  # dono confirmou que o Pix caiu na conta
    confirmed_at = db.Column(db.DateTime)  # quando a loja confirmou (acompanhamento do pedido)
    track_token = db.Column(db.String(32), unique=True, index=True)  # link de acompanhamento para o cliente
    discount = db.Column(db.Numeric(8, 2), nullable=False, default=0, server_default="0")  # 1º pedido + fidelidade
    discount_note = db.Column(db.String(160))  # ex.: "1º pedido (10%) · Pizza grátis da fidelidade"
    first_order = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    loyalty_reward = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # usou pizza grátis
    loyalty_programs = db.Column(db.String(80))  # cartões cujo prêmio foi usado, ex.: ",1,2," (busca com LIKE)
    eta_at = db.Column(db.DateTime)  # previsão de chegada (entrega) ou de ficar pronto (retirada), em UTC

    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    category_id = db.Column(db.Integer, index=True)  # categoria na hora da venda (selos da fidelidade); sem FK de propósito

    product_names = db.Column(db.String(255), nullable=False)  # "Calabresa Acebolada" ou "1/2 Toscana + 1/2 Bauru"
    variant_label = db.Column(db.String(30))
    border_name = db.Column(db.String(60))
    addon_names = db.Column(db.String(255))
    extras = db.Column(db.String(255))  # o que acompanha um combo (brindes e escolha do cliente)
    notes = db.Column(db.String(255))
    promo_name = db.Column(db.String(120))  # promoção que baixou o preço, se houve
    kind = db.Column(db.String(20))  # tipo da linha na hora da venda: pizza | doce | metro | bebida
    category_name = db.Column(db.String(80))  # categoria na hora da venda (o cupom mostra “Premium”, “Doces”...)

    flavor_rows = db.relationship("OrderItemFlavor", lazy=True, order_by="OrderItemFlavor.id")

    unit_price = db.Column(db.Numeric(8, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(8, 2))  # custo na hora da venda (services/costs.py); vazio = sem custo cadastrado
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


class Banner(db.Model):
    """Imagem do carrossel do topo do site, enviada pelo painel."""

    __tablename__ = "banners"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    image = db.Column(db.String(255), nullable=False)  # arquivo em UPLOAD_FOLDER
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class LoyaltyProgram(db.Model):
    """Cartão fidelidade (services/loyalty.py). Ex.: “Promocional”: a cada 10 pizzas das categorias
    que contam, 1 pizza grátis da categoria do prêmio, só dos sabores que o dono liberou."""

    __tablename__ = "loyalty_programs"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_loyalty_programs_tenant_id"), nullable=False)
    name = db.Column(db.String(40), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    goal = db.Column(db.Integer, nullable=False, default=10)
    count_category_ids = db.Column(db.Text)  # JSON: categorias cujas pizzas valem selo
    reward_category_id = db.Column(db.Integer, db.ForeignKey("categories.id", name="fk_loyalty_programs_reward_category"))
    reward_size = db.Column(db.String(60))  # tamanho da pizza grátis; vazio = qualquer
    reward_product_ids = db.Column(db.Text)  # JSON: sabores que podem ser escolhidos no prêmio
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    reward_category = db.relationship("Category")

    def counted(self):
        return json.loads(self.count_category_ids) if self.count_category_ids else []

    def reward_products(self):
        return json.loads(self.reward_product_ids) if self.reward_product_ids else []


class PushSubscription(db.Model):
    """Celular/navegador que aceitou receber avisos (Web Push; ver services/push.py)."""

    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_push_subscriptions_tenant_id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", name="fk_push_subscriptions_customer_id"), index=True)
    endpoint = db.Column(db.String(600), nullable=False, unique=True)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(80), nullable=False)
    wants_promos = db.Column(db.Boolean, nullable=False, default=True)  # avisos de promoção (os do pedido sempre vão)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_sent_at = db.Column(db.DateTime)


class PushCampaign(db.Model):
    """Aviso que o dono manda (ou agenda) para os celulares inscritos."""

    __tablename__ = "push_campaigns"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_push_campaigns_tenant_id"), nullable=False)
    title = db.Column(db.String(60), nullable=False)
    body = db.Column(db.String(160), nullable=False)
    url = db.Column(db.String(200))  # para onde o toque leva (ex.: /snep/#cat-promocionais)
    audience = db.Column(db.String(20), nullable=False, default="todos")  # todos | cadastro | sumidos
    scheduled_at = db.Column(db.DateTime, index=True)  # UTC; vazio = enviar agora
    repeat_weekly = db.Column(db.Boolean, nullable=False, default=False)
    sent_at = db.Column(db.DateTime)
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)


class Promotion(db.Model):
    """Desconto que o dono liga pelo painel (regras em app/services/promotions.py).

    Vale para uma categoria inteira ou só alguns sabores dela, num tamanho ou em
    todos, com dias da semana e período opcionais. O preço com desconto é
    calculado no servidor, como os demais preços.
    """

    __tablename__ = "promotions"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_promotions_tenant_id"), nullable=False)
    name = db.Column(db.String(60), nullable=False)  # ex.: "Terça da Calabresa"
    message = db.Column(db.String(200))  # frase do aviso que abre no site
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", name="fk_promotions_category_id"), nullable=False)
    product_ids = db.Column(db.Text)  # JSON com os sabores escolhidos; vazio = todos da categoria
    size_label = db.Column(db.String(60))  # tamanho; vazio = todos
    discount_type = db.Column(db.String(10), nullable=False, default="percent")  # percent | price
    value = db.Column(db.Numeric(10, 2), nullable=False)  # % de desconto ou o preço promocional
    weekdays = db.Column(db.String(20))  # "2,4" (0 = domingo); vazio = todos os dias
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)
    active = db.Column(db.Boolean, nullable=False, default=True)  # False = pausada pelo dono
    show_popup = db.Column(db.Boolean, nullable=False, default=True)
    image = db.Column(db.String(255))  # imagem opcional do aviso (UPLOAD_FOLDER)
    created_at = db.Column(db.DateTime, default=utcnow)

    category = db.relationship("Category")

    def product_id_list(self):
        return json.loads(self.product_ids) if self.product_ids else []

    def weekday_list(self):
        return [int(d) for d in (self.weekdays or "").split(",") if d.strip().isdigit()]


class Courier(db.Model):
    """Motoboy."""

    __tablename__ = "couriers"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(30))
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # como o dono paga este motoboy (aba Equipe; services/finance.py): ver COURIER_PAY
    pay_mode = db.Column(db.String(16), nullable=False, default="taxa", server_default="taxa")
    pay_per_delivery = db.Column(db.Numeric(8, 2))  # valor por entrega (por_entrega, diaria_entrega)
    pay_daily = db.Column(db.Numeric(8, 2))  # diária (diaria, diaria_entrega)


# formas de pagar o motoboy: nome que o dono vê
COURIER_PAY = {
    "taxa": "Fica com a taxa de entrega",
    "por_entrega": "Valor fixo por entrega",
    "diaria": "Diária",
    "diaria_entrega": "Diária + valor por entrega",
}
# categorias de gasto (aba Contas); motoboys e funcionários entram sozinhos pela aba Equipe
EXPENSE_CATEGORIES = {
    "mercado": "Mercado", "bebidas": "Bebidas", "embalagens": "Embalagens", "gas": "Gás", "aluguel": "Aluguel",
    "contas": "Luz, água e internet", "manutencao": "Manutenção", "outros": "Outros",
    "motoboys": "Motoboys", "funcionarios": "Funcionários",
}
MANUAL_CATEGORIES = ("mercado", "bebidas", "embalagens", "gas", "aluguel", "contas", "manutencao", "outros")


class Employee(db.Model):
    """Funcionário (aba Equipe): diarista (ganha por dia trabalhado) ou mensalista (salário)."""

    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(60))  # função, ex.: pizzaiolo, atendente
    pay_type = db.Column(db.String(10), nullable=False, default="diaria")  # diaria | mensal
    pay_amount = db.Column(db.Numeric(8, 2), nullable=False, default=0)  # valor da diária ou do salário
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    created_at = db.Column(db.DateTime, default=utcnow)


class WorkDay(db.Model):
    """Dia em que o diarista trabalhou (marcado em “Quem trabalhou hoje”)."""

    __tablename__ = "work_days"
    __table_args__ = (db.UniqueConstraint("employee_id", "day", name="uq_work_days_employee_day"),)

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False)


class Expense(db.Model):
    """Gasto (aba Contas). Pagamento de motoboy e de funcionário (e vale) também vira gasto."""

    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False, index=True)  # dia do gasto (horário de Brasília)
    category = db.Column(db.String(20), nullable=False)  # EXPENSE_CATEGORIES
    description = db.Column(db.String(160))
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    courier_id = db.Column(db.Integer, db.ForeignKey("couriers.id"))  # pagamento de motoboy
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"))  # pagamento ou vale de funcionário
    is_advance = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # vale
    created_at = db.Column(db.DateTime, default=utcnow)

    courier = db.relationship("Courier")
    employee = db.relationship("Employee")

    @property
    def category_name(self):
        return EXPENSE_CATEGORIES.get(self.category, self.category)


class Dispatch(db.Model):
    """Comanda de saída: um motoboy levando um ou mais pedidos. Fecha quando ele volta (baixa)."""

    __tablename__ = "dispatches"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    number = db.Column(db.Integer, nullable=False)  # nº da comanda, sequencial por loja
    courier_id = db.Column(db.Integer, db.ForeignKey("couriers.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)  # saída
    returned_at = db.Column(db.DateTime)  # volta (baixa)

    courier = db.relationship("Courier")
    orders = db.relationship("Order", backref="dispatch", lazy=True, order_by="Order.id")
