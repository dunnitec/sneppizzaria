"""Painel: avisos no celular dos clientes (enviar agora, agendar, repetir toda semana) e ícone do app."""

import threading
import time
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, g, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Category, Customer, Order, PushCampaign, PushSubscription, Tenant, utcnow
from app.routes.admin import FormError, _name, _reject, admin_bp
from app.services.hours import STORE_TZ, local_time
from app.services.push import enabled, send

MAX_PER_WEEK = 3  # avisos de promoção por semana: mais que isso o cliente desliga
AUDIENCES = {"todos": "Todos que ativaram os avisos", "cadastro": "Só quem tem cadastro no site",
             "sumidos": "Quem não pede há mais de 30 dias"}


def audience_subs(tenant, audience):
    q = PushSubscription.query.filter_by(tenant_id=tenant.id, wants_promos=True)
    if audience == "cadastro":
        q = q.join(Customer, Customer.id == PushSubscription.customer_id).filter(Customer.registered_at.isnot(None))
    elif audience == "sumidos":
        recent = db.session.query(Order.customer_id).filter(Order.tenant_id == tenant.id,
                                                            Order.created_at >= utcnow() - timedelta(days=30))
        q = q.filter(PushSubscription.customer_id.isnot(None), PushSubscription.customer_id.notin_(recent))
    return q.all()


def _week_count(tenant, around):
    """Avisos enviados ou agendados nos 7 dias antes e depois da data (limite por semana)."""
    lo, hi = around - timedelta(days=7), around + timedelta(days=7)
    sent = PushCampaign.query.filter(PushCampaign.tenant_id == tenant.id, PushCampaign.sent_at >= lo,
                                     PushCampaign.sent_at <= around).count()
    waiting = PushCampaign.query.filter(PushCampaign.tenant_id == tenant.id, PushCampaign.sent_at.is_(None),
                                        PushCampaign.scheduled_at >= around, PushCampaign.scheduled_at <= hi).count()
    return sent + waiting


def run_campaign(campaign):
    """Envia o aviso (já marcado como enviado por quem chamou) e agenda a próxima semana se repetir."""
    tenant = db.session.get(Tenant, campaign.tenant_id)
    campaign.sent_count = send(tenant, audience_subs(tenant, campaign.audience), campaign.title, campaign.body,
                               campaign.url or f"/{tenant.slug}/", tag=f"aviso-{campaign.id}")
    if campaign.repeat_weekly and campaign.scheduled_at:
        db.session.add(PushCampaign(tenant_id=tenant.id, title=campaign.title, body=campaign.body, url=campaign.url,
                                    audience=campaign.audience, repeat_weekly=True,
                                    scheduled_at=campaign.scheduled_at + timedelta(days=7)))
    db.session.commit()


def run_due():
    """Avisos agendados que chegaram na hora. Cada um é “pego” com um UPDATE para não sair duas vezes
    quando o servidor roda em mais de um processo."""
    now = utcnow()
    due = PushCampaign.query.filter(PushCampaign.sent_at.is_(None), PushCampaign.scheduled_at <= now).all()
    for c in due:
        claimed = PushCampaign.query.filter(PushCampaign.id == c.id, PushCampaign.sent_at.is_(None)) \
            .update({"sent_at": now}, synchronize_session=False)
        db.session.commit()
        if claimed:
            db.session.refresh(c)
            run_campaign(c)


_scheduler_started = False


def start_scheduler(app):
    """Confere os avisos agendados a cada minuto (thread em segundo plano)."""
    global _scheduler_started
    if _scheduler_started or app.config.get("TESTING"):
        return
    _scheduler_started = True

    def loop():
        while True:
            time.sleep(60)
            try:
                with app.app_context(), app.test_request_context():
                    run_due()
            except Exception:  # um erro aqui não pode parar os próximos avisos
                app.logger.exception("falha nos avisos agendados")

    threading.Thread(target=loop, daemon=True, name="avisos-agendados").start()


@admin_bp.before_app_request
def _boot_scheduler():
    start_scheduler(current_app._get_current_object())


def _links(tenant):
    links = [("", "Página inicial do cardápio")]
    for c in Category.query.filter_by(tenant_id=tenant.id).order_by(Category.sort_order, Category.id):
        links.append((f"/{tenant.slug}/#cat-{c.slug}", c.name))
    return links


@admin_bp.route("/avisos", methods=["GET", "POST"])
def push_campaigns():
    t = g.tenant
    links = _links(t)
    if request.method == "POST":
        form = request.form
        try:
            title = _name(form.get("title"), "o título do aviso", max_length=60)
            body = _name(form.get("body"), "o texto do aviso", max_length=160)
            url = form.get("url", "")
            if url not in dict(links):
                raise FormError("Escolha para onde o aviso leva.")
            audience = form.get("audience") if form.get("audience") in AUDIENCES else "todos"
            when = None
            if form.get("when") == "agendar":
                try:
                    local = datetime.strptime(f"{form.get('date')} {form.get('time')}", "%Y-%m-%d %H:%M")
                except ValueError:
                    raise FormError("Informe o dia e a hora do aviso agendado.") from None
                when = local.replace(tzinfo=STORE_TZ).astimezone(timezone.utc).replace(tzinfo=None)  # banco guarda UTC
                if when < utcnow() - timedelta(minutes=1):
                    raise FormError("Esse horário já passou. Escolha um dia e hora no futuro.")
            if _week_count(t, when or utcnow()) >= MAX_PER_WEEK:
                raise FormError(f"Limite de {MAX_PER_WEEK} avisos por semana. Mais que isso o cliente costuma desligar os avisos.")
            c = PushCampaign(tenant_id=t.id, title=title, body=body, url=url or None, audience=audience,
                             scheduled_at=when, repeat_weekly=bool(when and "repeat" in form))
            db.session.add(c)
            db.session.commit()
            if when:
                flash(f"Aviso agendado para {local_time(when).strftime('%d/%m às %H:%M')}"
                      f"{' (repete toda semana)' if c.repeat_weekly else ''}.", "ok")
            else:
                c.sent_at = utcnow()
                db.session.commit()
                run_campaign(c)
                flash(f"Aviso enviado para {c.sent_count} celular(es).", "ok")
        except FormError as e:
            _reject(e)
        return redirect(url_for("admin.push_campaigns"))
    subs = PushSubscription.query.filter_by(tenant_id=t.id)
    stats = {"total": subs.count(), "promos": subs.filter_by(wants_promos=True).count(),
             "registered": subs.join(Customer, Customer.id == PushSubscription.customer_id)
             .filter(Customer.registered_at.isnot(None)).count()}
    waiting = PushCampaign.query.filter(PushCampaign.tenant_id == t.id, PushCampaign.sent_at.is_(None)) \
        .order_by(PushCampaign.scheduled_at).all()
    sent = PushCampaign.query.filter(PushCampaign.tenant_id == t.id, PushCampaign.sent_at.isnot(None)) \
        .order_by(PushCampaign.sent_at.desc()).limit(20).all()
    week = _week_count(t, utcnow())
    return render_template("admin/push.html", stats=stats, waiting=waiting, sent=sent, links=links, audiences=AUDIENCES,
                           enabled=enabled(), week=week, max_week=MAX_PER_WEEK,
                           today=datetime.now(STORE_TZ).date().isoformat(), counts={a: len(audience_subs(t, a)) for a in AUDIENCES})


@admin_bp.route("/avisos/<int:campaign_id>/cancelar", methods=["POST"])
def push_campaign_cancel(campaign_id):
    c = PushCampaign.query.filter_by(tenant_id=g.tenant.id, id=campaign_id).first_or_404()
    if c.sent_at:
        flash("Esse aviso já foi enviado.", "error")
    else:
        db.session.delete(c)
        db.session.commit()
        flash("Aviso agendado cancelado.", "ok")
    return redirect(url_for("admin.push_campaigns"))



@admin_bp.route("/visual/icone", methods=["POST"])
def app_icon_upload():
    from app.routes.admin_manage import _uploaded_image
    from app.services.photos import PhotoError, delete_photo

    try:
        name = _uploaded_image()
    except PhotoError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.visual"))
    old, g.tenant.app_icon = g.tenant.app_icon, name
    db.session.commit()
    delete_photo(old)
    flash("Ícone do app trocado. Quem já instalou vê o novo ícone quando o celular atualizar o app.", "ok")
    return redirect(url_for("admin.visual"))


@admin_bp.route("/visual/icone/remover", methods=["POST"])
def app_icon_remove():
    from app.services.photos import delete_photo

    old, g.tenant.app_icon = g.tenant.app_icon, None
    db.session.commit()
    delete_photo(old)
    flash("Ícone do app removido: volta a inicial da loja.", "ok")
    return redirect(url_for("admin.visual"))
