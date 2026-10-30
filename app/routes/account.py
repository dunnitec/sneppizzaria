"""Conta do cliente no site: cadastro pelo telefone + senha de números, histórico, fidelidade
e a página de acompanhamento do pedido.

O login fica num cookie assinado próprio (90 dias), separado da sessão do painel. A senha
não verifica o número por SMS; por isso o histórico mostra só os pedidos feitos depois do
cadastro, e o dono pode gerar uma senha nova em Clientes quando o cliente esquecer.
"""

import re

from flask import Blueprint, abort, current_app, jsonify, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.extensions import db
from app.models import CHANNELS, ORDER_STATUSES, Customer, Dispatch, Order, PushSubscription, utcnow
from app.routes.public import get_tenant_or_404
from app.services.customers import format_phone, phone_key
from app.services.hours import local_time
from app.services.loyalty import cards, first_order_eligible, first_order_text
from app.services.order_display import item_view
from app.services.pix import for_order
from app.services.plans import has as has_feature
from app.services.throttle import customer_logins

account_bp = Blueprint("account", __name__)

COOKIE_DAYS = 90
PIN = re.compile(r"\d{4,6}")  # senhas antigas podem ter 4 ou 5 números; as novas têm 6 (new_pin_error)
NEW_PIN = re.compile(r"\d{6}")
LOGIN_FAILED = "Telefone ou senha incorretos. Esqueceu a senha? Peça uma nova para a pizzaria pelo WhatsApp."


def weak_pin(pin):
    """Senha fácil de adivinhar: tudo igual (111111) ou em sequência (123456, 654321)."""
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    return len(steps) == 1 and steps <= {-1, 0, 1}


def new_pin_error(pin):
    if not NEW_PIN.fullmatch(pin):
        return "A senha precisa ter 6 números."
    if weak_pin(pin):
        return "Essa senha é fácil de adivinhar. Evite números repetidos ou em sequência (ex.: 111111, 123456)."
    return None


# rotas que dependem do plano da loja (services/plans.py); o acompanhamento do pedido vale em todos
PLAN_ENDPOINTS = {"account.me": "fidelidade", "account.register": "fidelidade", "account.login": "fidelidade",
                  "account.change_pin": "fidelidade", "account.push_subscribe": "app"}


@account_bp.before_request
def _check_plan():
    feature = PLAN_ENDPOINTS.get(request.endpoint)
    if feature and not has_feature(get_tenant_or_404((request.view_args or {}).get("slug")), feature):
        return _error("Esta função não está disponível nesta loja.", 404)


def _cookie_name(tenant):
    return f"cliente_{tenant.slug}"


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="conta-cliente")


def current_customer(tenant):
    """Cliente logado no site (ou None). Trocar a senha desloga os outros aparelhos."""
    raw = request.cookies.get(_cookie_name(tenant))
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=COOKIE_DAYS * 86400)
    except BadSignature:
        return None
    c = db.session.get(Customer, data.get("c"))
    if not c or c.tenant_id != tenant.id or not c.pin_hash or c.pin_hash[-12:] != data.get("v"):
        return None
    return c


def _login_response(tenant, customer, payload):
    resp = jsonify(payload)
    token = _serializer().dumps({"c": customer.id, "v": customer.pin_hash[-12:]})
    resp.set_cookie(_cookie_name(tenant), token, max_age=COOKIE_DAYS * 86400, httponly=True, samesite="Lax",
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
    return resp


def _json_body():
    if not request.is_json:  # pedido de outro site não consegue mandar JSON sem permissão do navegador
        return None
    return request.get_json(silent=True) or {}


def _error(msg, code=400):
    return jsonify(ok=False, error=msg), code


def _hm(dt):
    return local_time(dt).strftime("%H:%M") if dt else None


def order_summary(order, slug):
    return {
        "id": order.id,
        "date": local_time(order.created_at).strftime("%d/%m/%Y %H:%M"),
        "status": ORDER_STATUSES.get(order.status, order.status),
        "status_code": order.status,
        "total": float(order.total),
        "eta": _hm(order.eta_at),
        "items": [f"{i.quantity}x {item_view(i)['head']}" for i in order.items][:6],
        "track_url": url_for("account.track", slug=slug, token=order.track_token) if order.track_token else None,
    }


def account_data(tenant, c):
    orders = (Order.query.filter(Order.customer_id == c.id, Order.created_at >= c.registered_at)
              .order_by(Order.id.desc()).limit(30).all())
    return {
        "ok": True, "logged": True,
        "name": c.name, "phone": format_phone(c.phone_key),
        "address": {"rua": c.street or "", "num": c.number or "", "comp": c.complement or "",
                    "bairro": c.neighborhood or "", "ref": c.reference or "",
                    "tipo": c.residence or "", "predio": c.building or ""},
        "loyalty": cards(tenant, c),
        "first_order": first_order_text(tenant) if first_order_eligible(tenant, c) else None,
        "orders": [order_summary(o, tenant.slug) for o in orders],
    }


@account_bp.route("/<slug>/api/conta")
def me(slug):
    tenant = get_tenant_or_404(slug)
    c = current_customer(tenant)
    if not c:
        return jsonify(ok=True, logged=False)
    return jsonify(account_data(tenant, c))


@account_bp.route("/<slug>/api/conta/cadastro", methods=["POST"])
def register(slug):
    tenant = get_tenant_or_404(slug)
    data = _json_body()
    if data is None:
        return _error("Pedido inválido.")
    name = " ".join(str(data.get("name") or "").split())[:120]
    key = phone_key(data.get("phone"))
    pin = str(data.get("pin") or "")
    if len(name) < 2:
        return _error("Informe seu nome.")
    if not key:
        return _error("Informe um telefone válido, com DDD.")
    if new_pin_error(pin):
        return _error(new_pin_error(pin))
    c = Customer.query.filter_by(tenant_id=tenant.id, phone_key=key).first()
    if c and c.pin_hash:
        return _error("Este telefone já tem cadastro. Use “Entrar” com a sua senha.", 409)
    if not c:
        c = Customer(tenant_id=tenant.id, phone_key=key, created_at=utcnow())
        db.session.add(c)
    else:
        # quem já pediu antes ganha o cadastro no mesmo cliente, mas sem o endereço guardado: o número
        # não é verificado, então quem cadastra o telefone de outra pessoa não pode ver onde ela mora
        # (os pedidos e selos de antes do cadastro também não aparecem: registered_at)
        c.street = c.number = c.complement = c.neighborhood = c.reference = c.residence = c.building = None
    c.name, c.phone = name, format_phone(key)
    c.set_pin(pin)
    c.registered_at = utcnow()
    c.failed_attempts, c.locked_until = 0, None
    db.session.commit()
    return _login_response(tenant, c, account_data(tenant, c))


@account_bp.route("/<slug>/api/conta/entrar", methods=["POST"])
def login(slug):
    tenant = get_tenant_or_404(slug)
    data = _json_body()
    if data is None:
        return _error("Pedido inválido.")
    key = phone_key(data.get("phone"))
    pin = str(data.get("pin") or "")
    ip, account = request.remote_addr or "?", f"{tenant.id}:{key}"
    # mesma resposta para telefone sem cadastro e senha errada: não revela quem é cliente
    if customer_logins.blocked(ip, account):
        return _error("Muitas tentativas seguidas. Espere 15 minutos ou peça uma senha nova para a pizzaria "
                      "pelo WhatsApp.", 429)
    c = Customer.query.filter_by(tenant_id=tenant.id, phone_key=key).first() if key else None
    if not c or not c.pin_hash or not c.check_pin(pin):
        customer_logins.fail(ip, account)
        return _error(LOGIN_FAILED, 401)
    customer_logins.success(ip, account)
    return _login_response(tenant, c, account_data(tenant, c))


@account_bp.route("/<slug>/api/conta/sair", methods=["POST"])
def logout(slug):
    tenant = get_tenant_or_404(slug)
    resp = jsonify(ok=True, logged=False)
    resp.delete_cookie(_cookie_name(tenant))
    return resp


@account_bp.route("/<slug>/api/conta/senha", methods=["POST"])
def change_pin(slug):
    tenant = get_tenant_or_404(slug)
    c = current_customer(tenant)
    data = _json_body()
    if not c or data is None:
        return _error("Entre na sua conta de novo.", 401)
    if not c.check_pin(str(data.get("pin") or "")):
        return _error("A senha atual está errada.", 401)
    new = str(data.get("new_pin") or "")
    if new_pin_error(new):
        return _error(new_pin_error(new))
    c.set_pin(new)
    db.session.commit()
    return _login_response(tenant, c, {**account_data(tenant, c), "message": "Senha trocada."})


# ---------- acompanhamento do pedido ----------

def track_steps(order):
    """Etapas com horário, como no iFood. done=True já aconteceu."""
    out_at = None
    if order.dispatch_id:
        d = db.session.get(Dispatch, order.dispatch_id)
        out_at = d.created_at if d else None
    steps = [("Pedido recebido", order.created_at, True),
             ("Confirmado pela pizzaria", order.confirmed_at, order.status in ("confirmado", "saiu", "entregue"))]
    if order.delivery:
        steps.append(("Saiu para entrega", out_at, order.status in ("saiu", "entregue")))
        steps.append(("Entregue", order.delivered_at, order.status == "entregue"))
    else:
        steps.append(("Retirado" if order.channel == "site" else "Entregue", order.delivered_at, order.status == "entregue"))
    return [{"label": label, "time": _hm(at), "done": done} for label, at, done in steps]


@account_bp.route("/<slug>/pedido/<token>")
def track(slug, token):
    tenant = get_tenant_or_404(slug)
    from app.services.plans import has

    if not has(tenant, "rastreio"):
        abort(404)
    order = Order.query.filter_by(tenant_id=tenant.id, track_token=token).first_or_404()
    show_pix = (order.payment_method == "Pix" and order.channel == "site" and not order.pix_paid_at
                and order.status != "cancelado" and not order.fee_pending)
    return render_template(
        "track.html", tenant=tenant, o=order, steps=track_steps(order), eta=_hm(order.eta_at),
        created=local_time(order.created_at), status=ORDER_STATUSES.get(order.status, order.status),
        first_name=(order.customer_name or "").split(" ")[0], channel=CHANNELS.get(order.channel, ""),
        pix=for_order(tenant, order) if show_pix else None,
    )


# ---------- avisos no celular (Web Push) ----------

@account_bp.route("/<slug>/api/push", methods=["POST"])
def push_subscribe(slug):
    """O navegador aceitou os avisos: guarda o endereço do aparelho e liga ao cliente, se der."""
    tenant = get_tenant_or_404(slug)
    data = _json_body()
    if data is None:
        return _error("Pedido inválido.")
    sub = data.get("subscription") or {}
    endpoint, keys = str(sub.get("endpoint") or ""), sub.get("keys") or {}
    if not endpoint.startswith("https://") or len(endpoint) > 600 or not keys.get("p256dh") or not keys.get("auth"):
        return _error("Inscrição inválida.")
    s = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if not s:
        s = PushSubscription(endpoint=endpoint, created_at=utcnow())
        db.session.add(s)
    s.tenant_id, s.p256dh, s.auth = tenant.id, str(keys["p256dh"])[:200], str(keys["auth"])[:80]
    account = current_customer(tenant)
    order = Order.query.filter_by(tenant_id=tenant.id, track_token=str(data.get("track") or "")).first() if data.get("track") else None
    if account:
        s.customer_id = account.id
    elif order and order.customer_id:
        s.customer_id = order.customer_id
    db.session.commit()
    return jsonify(ok=True, promos=s.wants_promos)


@account_bp.route("/<slug>/api/push/preferencias", methods=["POST"])
def push_prefs(slug):
    """Cliente desliga os avisos de promoção (os do pedido continuam) ou todos os avisos."""
    tenant = get_tenant_or_404(slug)
    data = _json_body()
    if data is None:
        return _error("Pedido inválido.")
    s = PushSubscription.query.filter_by(tenant_id=tenant.id, endpoint=str(data.get("endpoint") or "")).first()
    if not s:
        return jsonify(ok=True, subscribed=False)
    if data.get("off"):
        db.session.delete(s)
        db.session.commit()
        return jsonify(ok=True, subscribed=False)
    s.wants_promos = bool(data.get("promos"))
    db.session.commit()
    return jsonify(ok=True, subscribed=True, promos=s.wants_promos)
