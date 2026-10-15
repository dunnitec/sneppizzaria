"""Carga inicial do banco a partir de data/<slug>/cardapio.json.

Depois da primeira carga, o cardápio passa a ser editado pelo painel
(/<slug>/admin/) e o banco é a fonte da verdade. Por isso a reimportação só
acontece com --reset, que apaga o cardápio da loja (pedidos são preservados)
e descarta as alterações feitas pelo painel.

Uso:
    flask db upgrade                              # cria/atualiza as tabelas
    python seed.py data/snep/cardapio.json        # primeira carga
    python seed.py data/snep/cardapio.json --reset
"""

import json
import sys

from app import create_app
from app.extensions import db
from app.models import Addon, Border, Category, Neighborhood, Product, ProductVariant, Tenant


class SeedError(Exception):
    pass


def slugify(text):
    return (
        text.lower()
        .replace(" ", "-")
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("ú", "u")
    )


def clear_menu(tenant_id):
    """Apaga o cardápio de uma loja, dos filhos para os pais (respeita as chaves estrangeiras)."""
    product_ids = db.select(Product.id).where(Product.tenant_id == tenant_id)
    db.session.execute(db.delete(ProductVariant).where(ProductVariant.product_id.in_(product_ids)))
    for model in (Product, Category, Addon, Border, Neighborhood):
        db.session.execute(db.delete(model).where(model.tenant_id == tenant_id))
    db.session.flush()


def seed_from_file(path, reset=False):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    t = data["tenant"]
    tenant = Tenant.query.filter_by(slug=t["slug"]).first()
    if tenant and Category.query.filter_by(tenant_id=tenant.id).first():
        if not reset:
            raise SeedError(
                f"A loja '{t['slug']}' já tem cardápio no banco. Altere pelo painel, "
                "ou use --reset para apagar o cardápio atual e reimportar do arquivo."
            )
        clear_menu(tenant.id)
    if not tenant:
        tenant = Tenant(slug=t["slug"])
        db.session.add(tenant)

    tenant.name = t["name"]
    tenant.address = t.get("address")
    tenant.instagram = t.get("instagram")
    tenant.whatsapp = t.get("whatsapp")
    tenant.schedule_text = t.get("schedule_text")
    tenant.accepted_payments = t.get("accepted_payments", "Dinheiro,Pix,Débito,Crédito")
    tenant.hours_json = json.dumps(data.get("hours") or {})
    tenant.eta = t.get("eta", "40-50 min")
    db.session.flush()

    for order, cat in enumerate(data.get("categories", [])):
        category = Category(
            tenant_id=tenant.id,
            name=cat["name"],
            slug=cat.get("slug") or slugify(cat["name"]),
            kind=cat.get("kind", "pizza"),
            allows_addons=bool(cat.get("allows_addons", False)),
            sort_order=order,
        )
        combo = cat.get("combo")
        if combo:
            category.combo_sources = json.dumps(combo.get("sources") or [])
            category.combo_extras = "\n".join(combo.get("extras") or [])
            category.combo_choice_label = combo.get("choice_label") or None
            category.combo_choice_options = combo.get("choice_options") or None
        db.session.add(category)
        db.session.flush()

        for prod in cat.get("products", []):
            product = Product(
                tenant_id=tenant.id,
                category_id=category.id,
                name=prod["name"],
                description=prod.get("description"),
            )
            db.session.add(product)
            db.session.flush()

            for variant in prod.get("variants", []):
                db.session.add(
                    ProductVariant(
                        product_id=product.id,
                        label=variant["label"],
                        price=variant["price"],
                        max_flavors=variant.get("max_flavors", 1),
                    )
                )

    for addon in data.get("addons", []):
        db.session.add(
            Addon(
                tenant_id=tenant.id,
                name=addon["name"],
                price_whole=addon["price_whole"],
                price_half=addon["price_half"],
            )
        )

    for border in data.get("borders", []):
        db.session.add(
            Border(
                tenant_id=tenant.id,
                group_name=border["group"],
                name=border["name"],
                price=border["price"],
            )
        )

    for hood in data.get("neighborhoods", []):
        db.session.add(Neighborhood(tenant_id=tenant.id, name=hood["name"], fee=hood["fee"]))

    db.session.commit()
    return tenant


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    file_path = args[0] if args else "data/snep/cardapio.json"
    app = create_app()
    with app.app_context():
        try:
            tenant = seed_from_file(file_path, reset="--reset" in sys.argv)
        except SeedError as e:
            sys.exit(str(e))
        print(f"Cardápio de '{tenant.name}' importado com sucesso.")
