"""Cálculo da taxa de entrega.

Modo atual: por bairro, usando a tabela cadastrada em Neighborhood.
Isso é o que a Norbas e a maioria dos deliveries fazem na prática, e é o mais
simples de manter para o dono da pizzaria (edita a tabela sem depender de API
externa). Uma rota/serviço de cálculo por distância real (OSRM/Nominatim)
pode ser plugado aqui depois, mantendo a mesma assinatura de função.
"""

from decimal import Decimal

from app.models import Neighborhood


def get_active_neighborhoods(tenant_id):
    return (
        Neighborhood.query.filter_by(tenant_id=tenant_id, active=True)
        .order_by(Neighborhood.name)
        .all()
    )


def calculate_fee(tenant_id, neighborhood_name):
    """Retorna (fee: Decimal, found: bool). Se o bairro não estiver cadastrado,
    retorna None de taxa para o checkout pedir confirmação manual pelo WhatsApp."""
    if not neighborhood_name:
        return None, False

    hood = Neighborhood.query.filter_by(
        tenant_id=tenant_id, name=neighborhood_name, active=True
    ).first()
    if hood:
        return Decimal(str(hood.fee)), True
    return None, False
