"""Avisos no celular do cliente (Web Push, o padrão dos navegadores — sem Firebase).

As chaves VAPID ficam nas variáveis VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY (Fly: `fly secrets`).
Sem elas, nada é enviado e o site não oferece os avisos. Trocar as chaves invalida todas as
inscrições (os clientes precisam ativar de novo), então guarde-as.

O envio roda em segundo plano para o painel não esperar; aparelho que desinstalou ou
bloqueou (resposta 404/410) sai da lista sozinho.
"""

import json
from concurrent.futures import ThreadPoolExecutor

from flask import current_app, url_for

from app.extensions import db
from app.models import PushSubscription, utcnow
from app.services.plans import has as has_feature
from app.services.hours import local_time

_pool = ThreadPoolExecutor(max_workers=4)


def enabled():
    cfg = current_app.config
    return bool(cfg.get("VAPID_PUBLIC_KEY") and cfg.get("VAPID_PRIVATE_KEY"))


def _post(info, data, private_key, claims):
    """Envia um aviso. Devolve "ok", "gone" (aparelho não existe mais) ou "error"."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(subscription_info=info, data=data, vapid_private_key=private_key, vapid_claims=dict(claims), ttl=6 * 3600)
        return "ok"
    except WebPushException as e:
        return "gone" if getattr(e.response, "status_code", None) in (404, 410) else "error"
    except Exception:  # rede, chave inválida: não derruba o painel
        current_app.logger.exception("falha ao enviar aviso")
        return "error"


def send(tenant, subs, title, body, url, tag=None):
    """Manda o aviso para os aparelhos. Devolve quantos foram tentados."""
    subs = list(subs)
    if not enabled() or not subs or not has_feature(tenant, "app"):
        return 0
    app = current_app._get_current_object()
    payload = json.dumps({
        "title": title[:60], "body": body[:160], "url": url, "tag": tag,
        "icon": url_for("public.app_icon", slug=tenant.slug, size=192),
        "badge": url_for("public.app_icon", slug=tenant.slug, size=96),
    })
    jobs = [(s.id, {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}) for s in subs]
    key = app.config["VAPID_PRIVATE_KEY"]
    claims = {"sub": app.config.get("VAPID_SUBJECT") or "https://sneppizzaria.com.br"}

    def run():
        results = [(sid, _post(info, payload, key, claims)) for sid, info in jobs]
        with app.app_context():
            for sid, result in results:
                sub = db.session.get(PushSubscription, sid)
                if not sub:
                    continue
                if result == "gone":
                    db.session.delete(sub)
                elif result == "ok":
                    sub.last_sent_at = utcnow()
            db.session.commit()

    if app.config.get("PUSH_SYNC"):  # testes
        run()
    else:
        _pool.submit(run)
    return len(jobs)


def customer_subs(tenant, customer_id, promos_only=False):
    if not customer_id:
        return []
    q = PushSubscription.query.filter_by(tenant_id=tenant.id, customer_id=customer_id)
    return q.filter_by(wants_promos=True).all() if promos_only else q.all()


# ---------- avisos automáticos ----------

def _track(tenant, order):
    return url_for("account.track", slug=tenant.slug, token=order.track_token) if order.track_token else f"/{tenant.slug}/"


def notify_order(tenant, order, event):
    """Pedido mudou: confirmado, saiu, cancelado ou Pix recebido."""
    if order.channel != "site" and event != "saiu":
        return 0
    eta = local_time(order.eta_at).strftime("%H:%M") if order.eta_at else ""
    messages = {
        "confirmado": (f"Pedido #{order.id} confirmado ✓",
                       f"{'Previsão de entrega' if order.delivery else 'Pronto para retirar'}: {eta}." if eta else "Já estamos preparando."),
        "saiu": ("Seu pedido saiu para entrega 🛵", f"Pedido #{order.id}" + (f" chega por volta das {eta}." if eta else " está a caminho.")),
        "cancelado": (f"Pedido #{order.id} cancelado", "Ficou com dúvida? Fale com a pizzaria pelo WhatsApp."),
        "pix": ("Pix recebido ✓", f"O pagamento do pedido #{order.id} foi confirmado."),
    }
    if event not in messages:
        return 0
    title, body = messages[event]
    return send(tenant, customer_subs(tenant, order.customer_id), title, body, _track(tenant, order), tag=f"pedido-{order.id}")


def notify_loyalty(tenant, order):
    """Pedido confirmado: avisa quem ganhou a pizza grátis ou está a 1–2 pizzas dela."""
    from app.models import Customer
    from app.services.loyalty import programs, stamps

    customer = db.session.get(Customer, order.customer_id) if order.customer_id else None
    if not customer or not customer.registered_at:
        return 0
    subs = customer_subs(tenant, customer.id)
    if not subs:
        return 0
    sent = 0
    for p in programs(tenant):
        here = sum(i.quantity for i in order.items if i.category_id in p.counted())
        if not here:
            continue
        total = stamps(p, customer)
        if total // p.goal > (total - here) // p.goal:
            sent += send(tenant, subs, f"🎁 Você ganhou uma pizza {p.name} grátis!",
                         f"Seu cartão {p.name} completou {p.goal} selos. Use no próximo pedido.", f"/{tenant.slug}/",
                         tag=f"fidelidade-{p.id}")
        elif 0 < p.goal - total % p.goal <= 2:
            falta = p.goal - total % p.goal
            sent += send(tenant, subs, f"Falta{'m' if falta > 1 else ''} {falta} para a sua pizza grátis 🍕",
                         f"Cartão {p.name}: {total % p.goal} de {p.goal} selos.", f"/{tenant.slug}/", tag=f"fidelidade-{p.id}")
    return sent
