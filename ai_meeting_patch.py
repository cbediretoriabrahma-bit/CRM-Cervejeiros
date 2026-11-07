"""Agendamento da 1a reuniao pelo WhatsApp com horarios reais do CRM.

Ativo somente com AI_WHATSAPP_ENABLED=1 e AI_MEETING_ENABLED=1.
A agenda usa as tarefas pendentes do CRM e fuso America/Sao_Paulo.
"""
import os
import re
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from sqlalchemy import text as sql_text

import patched_app as p
import sitecustomize as sc

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")
_SLOT_KEYS = ("AI_MTG_SLOT_1", "AI_MTG_SLOT_2", "AI_MTG_SLOT_3", "AI_MTG_SLOT_4")
_WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


def _enabled():
    return (os.getenv("AI_WHATSAPP_ENABLED") == "1" and
            os.getenv("AI_MEETING_ENABLED") == "1")


def _available(slot):
    now = datetime.now(TZ)
    if slot <= now + timedelta(hours=2) or slot.weekday() >= 5:
        return False
    if slot.hour not in range(9, 21) or slot.minute != 0:
        return False
    start = slot.astimezone(UTC).replace(tzinfo=None)
    # Verifica sobreposicao contra reunioes de uma hora (1a ou 2a).
    return crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at > start - timedelta(hours=1),
        crm.Task.due_at < start + timedelta(hours=1),
    ).first() is None


def _format(slot):
    return f"{_WEEKDAYS[slot.weekday()]}, {slot:%d/%m/%Y} às {slot:%H:%M}"


def _new_options():
    now = datetime.now(TZ)
    morning, afternoon = [], []
    for offset in range(0, 21):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() >= 5:
            continue
        for hour in range(9, 21):
            slot = datetime.combine(day, time(hour, 0), tzinfo=TZ)
            if not _available(slot):
                continue
            target = morning if hour < 12 else afternoon
            if len(target) < 2:
                target.append(slot)
        if len(morning) >= 2 and len(afternoon) >= 2:
            break
    return morning + afternoon


def _save_options(lead, options):
    for i, key in enumerate(_SLOT_KEYS):
        sc._set_tag(lead, key, options[i].isoformat() if i < len(options) else "")
    sc._set_tag(lead, "AI_MTG_PENDING", "choose" if options else "")


def _read_options(lead):
    options = []
    for key in _SLOT_KEYS:
        raw = sc._tag_value(lead, key)
        if not raw:
            continue
        try:
            slot = datetime.fromisoformat(raw)
            slot = slot.replace(tzinfo=TZ) if slot.tzinfo is None else slot.astimezone(TZ)
            options.append(slot)
        except (ValueError, TypeError):
            pass
    return options


def _offer(lead):
    options = _new_options()
    _save_options(lead, options)
    if not options:
        return ("Não encontrei horários livres nos próximos dias úteis. "
                "Vou pedir que nossa equipe verifique a agenda com você.")
    listing = "\n".join(f"{i}. {_format(slot)}" for i, slot in enumerate(options, 1))
    return ("📅 Temos estes horários disponíveis para uma primeira reunião "
            "comercial rápida com a Cervejeiros:\n\n" + listing +
            "\n\nResponda com o *número da opção* (1 a " + str(len(options)) +
            ") para confirmar. Os horários estão sujeitos à disponibilidade "
            "no momento da confirmação.")


def _is_meeting_request(message):
    t = (message or "").strip().lower()
    return bool(re.search(
        r"\b(agendar|marcar|agenda|hor[aá]rios?|reuni[aã]o|meet|conversar com consultor)\b", t
    )) and (len(t) < 300)


def _chosen_index(message):
    match = re.fullmatch(r"\s*(?:op[cç][aã]o\s*)?([1-4])\s*[.!]?\s*", message or "", re.I)
    return int(match.group(1)) - 1 if match else None


def _book(lead, slot):
    if lead.stage in ("Reunião Agendada", "1ª Reunião Realizada",
                      "2ª Reunião Agendada", "2ª Reunião Realizada",
                      "Contrato Enviado", "Fechado", "Perdido"):
        return False
    existing = crm.Task.query.filter(
        crm.Task.lead_id == lead.id,
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
    ).first()
    if existing is not None or not _available(slot):
        return False
    # PostgreSQL: todas as reservas criadas por este modulo compartilham
    # um lock transacional, impedindo duas confirmacoes simultaneas.
    dialect = crm.db.session.get_bind().dialect.name
    if dialect == "postgresql":
        crm.db.session.execute(sql_text("SELECT pg_advisory_xact_lock(20261107)"))
    if not _available(slot):
        return False
    start = slot.astimezone(UTC).replace(tzinfo=None)
    crm.db.session.add(crm.Task(
        lead_id=lead.id,
        owner_id=lead.owner_id,
        title=f"1ª reunião com {lead.name}",
        task_type="Reunião",
        due_at=start,
        status="Pendente",
        notes=f"Agendada pelo atendimento IA WhatsApp para {_format(slot)}. Reserva de 1 hora na agenda.",
    ))
    lead.meeting_interest = "Sim"
    lead.next_followup = start
    lead.stage = "Reunião Agendada"
    sc._set_tag(lead, "AI_MTG_PENDING", "")
    sc._set_tag(lead, "Q_MEETING_SLOT", slot.isoformat())
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="1ª reunião agendada pela IA",
        detail=f"Confirmada: {_format(slot)}; duração bloqueada na agenda: 1 hora",
    ))
    return True


_previous_apply = p._apply_answer_to_lead
_previous_reply = p._reply_for_message


def _apply(lead, message):
    if not _enabled():
        return _previous_apply(lead, message)

    if sc._tag_value(lead, "AI_MTG_PENDING") == "choose":
        idx = _chosen_index(message)
        if idx is not None:
            options = _read_options(lead)
            if idx < len(options):
                if _book(lead, options[idx]):
                    sc._set_tag(lead, "AI_MTG_RESPONSE",
                                f"✅ Sua primeira reunião foi agendada para "
                                f"*{_format(options[idx])}*. Nossa equipe "
                                "confirmará as instruções de acesso. 🍻")
                else:
                    sc._set_tag(lead, "AI_MTG_RESPONSE", "refresh")
            else:
                sc._set_tag(lead, "AI_MTG_RESPONSE", "refresh")
            return
        if (message or "").strip().lower() in ("cancelar", "não", "nao", "depois"):
            sc._set_tag(lead, "AI_MTG_PENDING", "")
            sc._set_tag(lead, "AI_MTG_RESPONSE",
                        "Tudo bem! Quando quiser, podemos consultar novos horários.")
            return

    # O fluxo de qualificação por indice de mensagem nao serve para perguntas
    # abertas; apenas preparar horario quando a pessoa expressar interesse.
    if _is_meeting_request(message) and lead.stage not in (
        "Reunião Agendada", "1ª Reunião Realizada", "2ª Reunião Agendada",
        "2ª Reunião Realizada", "Contrato Enviado", "Fechado", "Perdido"
    ):
        sc._set_tag(lead, "AI_MTG_RESPONSE", "offer")
        return
    return _previous_apply(lead, message)


def _reply(lead, message):
    if not _enabled():
        return _previous_reply(lead, message)
    # Respeitar a transferencia humana / cancelamento antes de oferecer agenda.
    if "[AI_HANDOFF]=1" in (lead.notes or ""):
        return _previous_reply(lead, message)
    queued = sc._tag_value(lead, "AI_MTG_RESPONSE")
    if queued:
        sc._set_tag(lead, "AI_MTG_RESPONSE", "")
        if queued in ("offer", "refresh"):
            return _offer(lead)
        return queued
    return _previous_reply(lead, message)


p._apply_answer_to_lead = _apply
p._reply_for_message = _reply
