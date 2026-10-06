"""Popula o banco a partir de data/<slug>/cardapio.json.

Uso:
    python seed.py data/snep/cardapio.json
"""

import json
import sys

from app import create_app
from app.extensions import db
from app.models import Addon, Border, Category, Product, ProductVariant, Tenant


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


def seed_from_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    t = data["tenant"]
    tenant = Tenant.query.filter_by(slug=t["slug"]).first()
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

    # limpa cardápio anterior deste tenant para reimportar do zero
    Category.query.filter_by(tenant_id=tenant.id).delete()
    Addon.query.filter_by(tenant_id=tenant.id).delete()
    Border.query.filter_by(tenant_id=tenant.id).delete()
    db.session.flush()

    for order, cat in enumerate(data.get("categories", [])):
        category = Category(
            tenant_id=tenant.id,
            name=cat["name"],
            slug=cat.get("slug") or slugify(cat["name"]),
            kind=cat.get("kind", "pizza"),
            sort_order=order,
        )
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
        from app.models import Neighborhood

        db.session.add(
            Neighborhood(tenant_id=tenant.id, name=hood["name"], fee=hood["fee"])
        )

    db.session.commit()
    print(f"Cardápio de '{tenant.name}' importado com sucesso ({len(data.get('categories', []))} categorias).")


if __name__ == "__main__":
    file_path = sys.argv[1] if len(sys.argv) > 1 else "data/snep/cardapio.json"
    app = create_app()
    with app.app_context():
        db.create_all()
        seed_from_file(file_path)
