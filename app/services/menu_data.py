PAY_ICONS = {
    "Dinheiro": '<svg viewBox="0 0 34 24"><rect x="1" y="4" width="32" height="16" rx="2" fill="#2e9e4f"/><rect x="4" y="7" width="26" height="10" rx="1" fill="none" stroke="#fff" stroke-width="1.2"/><circle cx="17" cy="12" r="3.5" fill="#fff"/><text x="17" y="14" font-size="5" text-anchor="middle" fill="#2e9e4f" font-family="Arial" font-weight="700">$</text></svg>',
    "Pix": '<svg viewBox="0 0 24 24"><g fill="#32bcad"><path d="M12 2.5l4.2 4.2h-2.1a2 2 0 0 0-1.4.6L12 8l-.7-.7a2 2 0 0 0-1.4-.6H7.8z"/><path d="M12 21.5l-4.2-4.2h2.1a2 2 0 0 0 1.4-.6L12 16l.7.7a2 2 0 0 0 1.4.6h2.1z"/><path d="M2.5 12l4.2-4.2v2.1a2 2 0 0 0 .6 1.4L8 12l-.7.7a2 2 0 0 0-.6 1.4v2.1z"/><path d="M21.5 12l-4.2 4.2v-2.1a2 2 0 0 0-.6-1.4L16 12l.7-.7a2 2 0 0 0 .6-1.4V7.8z"/><rect x="9.2" y="9.2" width="5.6" height="5.6" rx="1.2" transform="rotate(45 12 12)"/></g></svg>',
    "Débito": '<svg viewBox="0 0 34 24"><rect x="1" y="3" width="32" height="18" rx="2.5" fill="#1e5aa8"/><rect x="1" y="7" width="32" height="4" fill="#0d3b75"/><rect x="5" y="14" width="10" height="3" rx="1" fill="#fff"/></svg>',
    "Crédito": '<svg viewBox="0 0 34 24"><rect x="1" y="3" width="32" height="18" rx="2.5" fill="#d9a400"/><rect x="1" y="7" width="32" height="4" fill="#a67c00"/><rect x="5" y="14" width="10" height="3" rx="1" fill="#fff"/></svg>',
    "Cartão": '<svg viewBox="0 0 34 24"><rect x="1" y="3" width="32" height="18" rx="2.5" fill="#555"/><rect x="1" y="7" width="32" height="4" fill="#333"/></svg>',
}

"""Monta o dicionário que alimenta o template/JS do cardápio.

Duas fontes, mesmo formato de saída:
  - data_from_db(tenant)        -> usado pelo site Flask
  - data_from_json(cardapio)    -> usado pelo build_static_preview.py (prévia sem servidor)
"""

WEEKDAYS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]


def _hours_rows(hours):
    """hours: {"0": [1080, 1310], "1": null, ...} (minutos desde 00:00; 0 = domingo)."""
    rows = []
    for d in (1, 2, 3, 4, 5, 6, 0):
        h = hours.get(str(d))
        if h:
            close = h[1] % 1440  # depois da meia-noite: fecha na madrugada do dia seguinte
            rows.append((WEEKDAYS[d], f"{h[0]//60:02d}:{h[0]%60:02d} às {close//60:02d}:{close%60:02d}"))
        else:
            rows.append((WEEKDAYS[d], "Fechado"))
    return rows


def _fmt_phone(wa):
    digits = "".join(ch for ch in (wa or "") if ch.isdigit())
    if len(digits) == 13:  # 55 11 97393 7104
        return f"({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    return wa or ""


def _finish(d, order_url, assets):
    from app.services.site_options import DEFAULTS as SITE_DEFAULTS

    t = d["tenant"]
    hours = {str(k): v for k, v in (d.get("hours") or {}).items()}
    fees = [n["fee"] for n in d.get("neighborhoods", [])] or [0]
    d.update(
        hours=hours,
        hours_rows=_hours_rows(hours),
        payments=[p.strip() for p in t.get("accepted_payments", "").split(",") if p.strip()],
        min_fee=min(fees),
        notices=d.get("notices", ["Pizzas meio a meio será cobrado pelo valor da maior!"]),
        min_order=d.get("min_order", 0),
        site=d.get("site") or dict(SITE_DEFAULTS),
        residence_fees=d.get("residence_fees") or {"apartamento": 0, "condominio": 0},
        order_url=order_url,
        assets=assets,
    )
    for c in d.get("categories", []):  # cardapio.json guarda as opções como texto, igual ao banco
        if isinstance((c.get("combo") or {}).get("choice_options"), str):
            from app.models import split_options

            c["combo"]["choice_options"] = split_options(c["combo"]["choice_options"])
    t["whatsapp_fmt"] = _fmt_phone(t.get("whatsapp"))
    t.setdefault("eta", "40-50 min")
    return d


def data_from_json(cardapio, order_url="#", assets=None):
    import copy

    d = copy.deepcopy(cardapio)
    return _finish(d, order_url, assets or {})


def data_from_db(tenant, order_url, assets):
    import json

    from app.models import Addon, Border, Category, Neighborhood
    from app.services.hours import is_open, open_hours
    from app.services.photos import photo_url
    from app.services.geo import km_on
    from app.services.business import biz
    from app.services.site_options import options as site_options
    from flask import current_app

    from app.services.loyalty import first_order_on, first_order_text
    from app.services.plans import has as has_feature
    from app.services.loyalty import public_info as loyalty_public
    from app.services.promotions import badge, best_price, describe, running

    promos = running(tenant)
    used = set()  # promoções que baixaram o preço de algum item à venda

    def variant_data(c, p, v):
        price, promo = best_price(promos, c.id, p.id, v.label, v.price)
        d = {"label": v.label, "price": float(price), "max_flavors": v.max_flavors}
        if promo:  # o site mostra o preço antigo riscado e o selo
            d.update(regular=float(v.price), promo=badge(promo), promo_id=promo.id)
            used.add(promo.id)
        return d

    # os ids vão para o navegador para que o pedido diga o que foi escolhido;
    # o preço é sempre recalculado no servidor (services/pricing.py)
    cats = []
    for c in Category.query.filter_by(tenant_id=tenant.id).order_by(Category.sort_order, Category.id):
        products = [p for p in c.products if p.active and any(v.active for v in p.variants)]
        if not products:
            continue  # linha sem nada à venda não aparece no site
        cats.append(
            {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "kind": c.kind,
                "allows_addons": c.allows_addons,
                "subtitle": c.subtitle or "",
                "icon": c.icon or "fatia",
                "accent": c.accent or "vermelho",
                "banner": photo_url(c.banner_image),
                **({"combo": c.combo_settings()} if c.kind == "metro" else {}),
                **({"picks": c.pick_settings()} if c.kind == "montar" else {}),
                "products": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "image": photo_url(p.image),
                        "description": p.description or "",
                        **({} if p.accepts_border else {"no_border": True}),
                        "variants": [variant_data(c, p, v) for v in p.variants if v.active],
                    }
                    for p in products
                ],
            }
        )
    d = {
        "tenant": {
            "slug": tenant.slug,
            "name": tenant.name,
            "slogan": tenant.slogan or "",
            "hero": photo_url(tenant.hero_image),
            "address": tenant.address,
            "instagram": tenant.instagram,
            "whatsapp": tenant.whatsapp,
            "accepted_payments": tenant.accepted_payments or "",
            "eta": f"~{tenant.eta_minutes} min",
            "eta_minutes": tenant.eta_minutes,
            "pickup_minutes": tenant.pickup_minutes,
        },
        "business": biz(tenant),  # tipo de loja: palavras do site (services/business.py)
        "hours": open_hours(tenant),
        "open": is_open(tenant),
        "pix": bool(tenant.pix_key),  # QR Code do Pix no pedido feito (app/services/pix.py)
        # cadastro do cliente: fidelidade e 1º pedido (app/services/loyalty.py); o desconto é calculado no servidor
        "loyalty": loyalty_public(tenant),  # cartões fidelidade ligados
        "first_order": ({"type": tenant.first_order_type, "value": float(tenant.first_order_value),
                         "text": first_order_text(tenant)} if first_order_on(tenant) else None),
        # cadastro do cliente só no plano com fidelidade (services/plans.py); vazio = site sem “Entrar”
        "account_url": f"/{tenant.slug}/api/conta" if has_feature(tenant, "fidelidade") else "",
        # frete por distância: o checkout pede o CEP e consulta quote_url (services/geo.py)
        "km": {"quote_url": f"/{tenant.slug}/api/frete", "price": float(tenant.km_price or 0),
               "max": float(tenant.km_max) if tenant.km_max else None}
        if km_on(tenant) else None,
        # app no celular e avisos (Web Push); sem chave VAPID os avisos ficam desligados
        "app": has_feature(tenant, "app"),
        "push_key": (current_app.config.get("VAPID_PUBLIC_KEY", "") if current_app.config.get("VAPID_PRIVATE_KEY")
                     and has_feature(tenant, "app") else ""),
        "notices": [line.strip() for line in (tenant.notices or "").splitlines() if line.strip()],
        "min_order": float(tenant.min_order or 0),
        # como o site aparece (Aparência → Como o site funciona) e acréscimo por tipo de endereço (Entrega)
        "site": site_options(tenant),
        "residence_fees": {"apartamento": float(tenant.fee_apartment or 0), "condominio": float(tenant.fee_condo or 0)},
        "categories": cats,
        # promoções no ar: viram selo no cardápio e o aviso que abre ao entrar no site
        "promotions": [
            {"id": p.id, "name": p.name, "message": p.message or "", "text": describe(p), "badge": badge(p),
             "category": p.category.slug, "image": photo_url(p.image), "popup": p.show_popup}
            for p in promos
            if p.id in used
        ],
        "addons": [
            {"id": a.id, "name": a.name, "price_whole": float(a.price_whole), "price_half": float(a.price_half)}
            for a in Addon.query.filter_by(tenant_id=tenant.id, active=True).order_by(Addon.id)
        ],
        "borders": [
            {"id": b.id, "group": b.group_name, "name": b.name, "price": float(b.price), **b.rules()}
            for b in Border.query.filter_by(tenant_id=tenant.id, active=True).order_by(Border.id)
        ],
        "neighborhoods": [
            {"name": n.name, "fee": float(n.fee)}
            for n in Neighborhood.query.filter_by(tenant_id=tenant.id, active=True).order_by(Neighborhood.name)
        ],
    }
    return _finish(d, order_url, assets)
