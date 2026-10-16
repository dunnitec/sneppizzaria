"""Aberto/fechado calculado no servidor, no horário de Brasília.

O relógio do aparelho do cliente não é confiável; a decisão usa o horário
cadastrado em Tenant.hours_json e o botão manual do painel (is_open_override).
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo("America/Sao_Paulo")


def local_time(utc_naive):
    """Converte uma data gravada no banco (UTC, sem fuso) para o horário da loja."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(STORE_TZ) if utc_naive else None


def is_open(tenant, now=None):
    if tenant.is_open_override is not None:
        return tenant.is_open_override

    now = (now or datetime.now(STORE_TZ)).astimezone(STORE_TZ)
    hours = json.loads(tenant.hours_json) if tenant.hours_json else {}
    weekday = (now.weekday() + 1) % 7  # hours_json usa 0 = domingo
    today = hours.get(str(weekday))
    if not today:
        return False
    minute = now.hour * 60 + now.minute
    return today[0] <= minute < today[1]


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def status_text(tenant, now=None):
    """Frase curta para o painel: por que a loja está aberta/fechada e o que vem a seguir."""
    if tenant.is_open_override is True:
        return "Aberta por você, até você fechar ou voltar ao horário."
    if tenant.is_open_override is False:
        return "Fechada por você, até você abrir de novo."
    now = (now or datetime.now(STORE_TZ)).astimezone(STORE_TZ)
    hours = json.loads(tenant.hours_json) if tenant.hours_json else {}
    today = hours.get(str((now.weekday() + 1) % 7))
    if not today:
        return "Fechada agora. Hoje não abre."
    minute = now.hour * 60 + now.minute
    if minute < today[0]:
        return f"Fechada agora. Hoje abre às {_hhmm(today[0])}."
    if minute < today[1]:
        return f"Aberta, seguindo o horário. Fecha às {_hhmm(today[1])}."
    return "Fechada agora. Hoje já encerrou."
