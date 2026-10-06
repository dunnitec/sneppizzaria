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
            rows.append((WEEKDAYS[d], f"{h[0]//60:02d}:{h[0]%60:02d} às {h[1]//60:02d}:{h[1]%60:02d}"))
        else:
            rows.append((WEEKDAYS[d], "Fechado"))
    return rows


def _fmt_phone(wa):
    digits = "".join(ch for ch in (wa or "") if ch.isdigit())
    if len(digits) == 13:  # 55 11 97393 7104
        return f"({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    return wa or ""


def _finish(d, order_url, assets):
    t = d["tenant"]
    hours = {str(k): v for k, v in (d.get("hours") or {}).items()}
    fees = [n["fee"] for n in d.get("neighborhoods", [])] or [0]
    d.update(
        hours=hours,
        hours_rows=_hours_rows(hours),
        payments=[p.strip() for p in t.get("accepted_payments", "").split(",") if p.strip()],
        min_fee=min(fees),
        order_url=order_url,
        assets=assets,
    )
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

    cats = []
    for c in Category.query.filter_by(tenant_id=tenant.id).order_by(Category.sort_order, Category.id):
        cats.append(
            {
                "name": c.name,
                "slug": c.slug,
                "kind": c.kind,
                "products": [
                    {
                        "name": p.name,
                        "description": p.description or "",
                        "variants": [
                            {"label": v.label, "price": float(v.price), "max_flavors": v.max_flavors}
                            for v in p.variants
                        ],
                    }
                    for p in c.products
                    if p.active
                ],
            }
        )
    d = {
        "tenant": {
            "slug": tenant.slug,
            "name": tenant.name,
            "address": tenant.address,
            "instagram": tenant.instagram,
            "whatsapp": tenant.whatsapp,
            "accepted_payments": tenant.accepted_payments or "",
            "eta": tenant.eta or "40-50 min",
        },
        "hours": json.loads(tenant.hours_json) if tenant.hours_json else {},
        "categories": cats,
        "addons": [
            {"name": a.name, "price_whole": float(a.price_whole), "price_half": float(a.price_half)}
            for a in Addon.query.filter_by(tenant_id=tenant.id, active=True).order_by(Addon.id)
        ],
        "borders": [
            {"group": b.group_name, "name": b.name, "price": float(b.price)}
            for b in Border.query.filter_by(tenant_id=tenant.id, active=True).order_by(Border.id)
        ],
        "neighborhoods": [
            {"name": n.name, "fee": float(n.fee)}
            for n in Neighborhood.query.filter_by(tenant_id=tenant.id, active=True).order_by(Neighborhood.name)
        ],
    }
    return _finish(d, order_url, assets)
