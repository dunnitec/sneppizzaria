"""Cadastro automático de clientes: o telefone identifica o cliente, sem senha.

O cliente nasce no primeiro pedido e é atualizado a cada novo pedido (nome e,
quando é entrega, o endereço). Apagar um cliente remove os dados pessoais também
dos pedidos dele, mas mantém os valores para os relatórios.
"""

import re

from app.extensions import db
from app.models import Customer, Order, PushSubscription, utcnow


def phone_key(raw):
    """'(11) 99999-0000', '+55 11 99999-0000' -> '11999990000'. None se não parecer um telefone do Brasil."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    return digits if len(digits) in (10, 11) else None


def format_phone(key):
    """'11999990000' -> '(11) 99999-0000'"""
    if not key or len(key) not in (10, 11):
        return key or ""
    return f"({key[:2]}) {key[2:-4]}-{key[-4:]}"


def upsert_customer(tenant, key, info):
    """Acha o cliente pelo telefone (ou cria) e atualiza com os dados do pedido."""
    customer = Customer.query.filter_by(tenant_id=tenant.id, phone_key=key).first()
    if not customer:
        customer = Customer(tenant_id=tenant.id, phone_key=key, created_at=utcnow())
        db.session.add(customer)
    customer.name = info["customer_name"]
    customer.phone = info["customer_phone"]
    if not info["withdraw"]:
        customer.street = info["street"]
        customer.number = info["number"]
        customer.complement = info["complement"]
        customer.neighborhood = info["neighborhood_name"]
        customer.reference = info["reference"]
    customer.updated_at = utcnow()
    return customer


def erase_customer(customer):
    """LGPD: apaga o cliente e os dados pessoais dos pedidos dele (valores e bairro ficam para os relatórios)."""
    for order in Order.query.filter_by(customer_id=customer.id):
        order.customer_id = None
        order.customer_name = "Cliente removido"
        order.customer_phone = ""
        order.street = order.number = order.complement = order.reference = ""
        order.change_for = None
        order.whatsapp_message = None
    # celulares inscritos nos avisos por este cliente param de receber qualquer aviso
    PushSubscription.query.filter_by(customer_id=customer.id).delete()
    db.session.delete(customer)
