"""Planos da plataforma: o que cada pizzaria pode usar.

Só o painel da plataforma (/plataforma/) muda o plano. Função fora do plano some do
painel da loja e do site; os dados já cadastrados ficam guardados e voltam se o plano subir.
"""

# função -> nome que aparece nas telas
FEATURES = {
    "promocoes": "Promoções com selo e aviso na tela",
    "fidelidade": "Cadastro do cliente, desconto no 1º pedido e cartões fidelidade",
    "app": "App no celular e avisos ao cliente",
}

PLANS = {
    "essencial": {"name": "Essencial", "features": set()},
    "completo": {"name": "Completo", "features": set(FEATURES)},
}

# telas do painel da loja que dependem de cada função
ADMIN_ENDPOINTS = {
    "promocoes": {"admin.promos", "admin.promo_edit", "admin.promo_toggle", "admin.promo_delete"},
    "fidelidade": {"admin.loyalty", "admin.loyalty_program_save", "admin.loyalty_program_delete",
                   "admin.loyalty_first_order", "admin.customer_new_pin"},
    "app": {"admin.push_campaigns", "admin.push_campaign_cancel"},
}


def has(tenant, feature):
    plan = PLANS.get(tenant.plan) or PLANS["completo"]
    return feature in plan["features"]


def plan_name(tenant):
    return (PLANS.get(tenant.plan) or PLANS["completo"])["name"]


def blocked_feature(tenant, endpoint):
    """A tela pedida é de uma função fora do plano? Devolve a função ou None."""
    for feature, endpoints in ADMIN_ENDPOINTS.items():
        if endpoint in endpoints and not has(tenant, feature):
            return feature
    return None
