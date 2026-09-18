"""Agendamento em duas etapas para WhatsApp e Instagram.

Fluxo:
1. Lead aceita a reunião.
2. CRM oferece os próximos 7 dias úteis (segunda a sexta) que tenham pelo
   menos um horário livre entre 11:00 e 15:00.
3. Lead escolhe o dia.
4. CRM oferece somente os horários realmente livres, de 1 em 1 hora:
   11:00, 12:00, 13:00, 14:00 e 15:00.
5. Antes de confirmar, a disponibilidade é conferida novamente.

Horários ocupados nunca são oferecidos. Se um horário for ocupado entre a
exibição e a escolha, o CRM atualiza as opções sem travar a conversa. Dias
sem nenhum horário livre também não aparecem para o lead.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import flow_media_patch as fm
import patched_app as p
import sitecustomize as sc

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _format_day(day):
    return f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d/%m')}"


def _free_slots_for_day(lead, day):
    """Retorna apenas horários livres entre 11:00 e 15:00, de hora em hora."""
    now = datetime.now(TZ)
    slots = []
    for hour in range(11, 16):  # 11:00, 12:00, 13:00, 14:00 e 15:00
        slot = datetime.combine(day, datetime.min.time(), tzinfo=TZ).replace(hour=hour)
        if slot <= now + timedelta(hours=2):
            continue
        if sc._slot_is_free(slot, lead.owner_id):
            slots.append(slot)
    return slots


def _available_days(lead, refresh=False):
    """Retorna até 7 dias úteis que tenham pelo menos 1 horário livre."""
    if not refresh:
        stored = []
        for i in range(1, 8):
            raw = sc._tag_value(lead, f"Q_DAY_{i}")
            if not raw:
                break
            try:
                day = datetime.fromisoformat(raw).date()
            except Exception:
                stored = []
                break
            if len(_free_slots_for_day(lead, day)) < 1:
                stored = []
                break
            stored.append(day)
        if stored:
            return stored

    now = datetime.now(TZ)
    days = []
    for add_day in range(0, 45):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() >= 5:
            continue
        if _free_slots_for_day(lead, day):
            days.append(day)
        if len(days) == 7:
            break

    for i in range(1, 8):
        value = days[i - 1].isoformat() if i <= len(days) else ""
        sc._set_tag(lead, f"Q_DAY_{i}", value)
    return days


def _select_day(lead, text):
    days = _available_days(lead, refresh=True)
    if not days:
        return None
    raw = _norm(text)

    m = re.fullmatch(r"[1-7]", raw)
    if m:
        idx = int(raw) - 1
        if idx < len(days):
            return days[idx]

    for day in days:
        labels = {
            _norm(_format_day(day)),
            _norm(day.strftime("%d/%m")),
            _norm(WEEKDAYS[day.weekday()]),
            _norm(f"{WEEKDAYS[day.weekday()]} {day.strftime('%d/%m')}"),
        }
        if raw in labels:
            return day
    return None


def _store_time_options(lead, day):
    slots = _free_slots_for_day(lead, day)
    for i in range(1, 6):
        value = slots[i - 1].isoformat() if i <= len(slots) else ""
        sc._set_tag(lead, f"Q_SLOT_{i}", value)
    return slots


def _selected_day(lead):
    raw = sc._tag_value(lead, "Q_MEETING_DAY")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except Exception:
        return None


def _find_time(lead, text):
    day = _selected_day(lead)
    if not day:
        return None

    slots = _store_time_options(lead, day)
    raw = _norm(text)

    m = re.fullmatch(r"[1-5]", raw)
    if m:
        idx = int(raw) - 1
        return slots[idx] if idx < len(slots) else None

    for slot in slots:
        labels = {
            _norm(slot.strftime("%H:%M")),
            _norm(slot.strftime("%Hh")),
            _norm(slot.strftime("%H")),
            _norm(sc._format_slot(slot)),
            _norm(sc._format_slot(slot)[:20]),
            _norm(sc._format_slot(slot).replace(":00", "")),
        }
        if raw in labels:
            return slot
    return None


def _schedule_selected_time(lead, text):
    slot = _find_time(lead, text)
    if slot is None:
        return False

    # Revalida no instante da confirmação para impedir agendamento duplicado.
    if not sc._slot_is_free(slot, lead.owner_id):
        day = _selected_day(lead)
        if day:
            _store_time_options(lead, day)
        return False

    utc_naive = slot.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    crm.db.session.add(crm.Task(
        lead_id=lead.id,
        owner_id=lead.owner_id,
        title=f"Reunião com {lead.name}",
        task_type="Reunião",
        due_at=utc_naive,
        status="Pendente",
        notes=f"Reunião comercial de 1 hora agendada automaticamente para {sc._format_slot(slot)}.",
    ))
    lead.next_followup = utc_naive
    lead.stage = "Reunião Agendada"
    sc._set_tag(lead, "Q_MEETING_SLOT", slot.isoformat())
    current = (lead.notes or "").strip()
    line = f"Reunião agendada: {sc._format_slot(slot)} | duração: 1 hora"
    lead.notes = current + ("\n" if current else "") + line
    return True


def _day_prompt(lead):
    days = _available_days(lead, refresh=True)
    if not days:
        return (
            "No momento não encontrei dias úteis com horários livres entre 11:00 e 15:00. "
            "Nosso consultor entrará em contato para combinar a reunião."
        )

    options = [
        {"id": str(i + 1), "title": _format_day(day)[:24]}
        for i, day in enumerate(days)
    ]
    return fm._list_marker(
        "📅 *Qual dia fica melhor para sua reunião?*\n\n"
        "Escolha entre os *próximos 7 dias úteis disponíveis* "
        "(segunda a sexta-feira):",
        "Escolher dia",
        options,
    )


def _time_prompt(lead, refresh=True):
    day = _selected_day(lead)
    if not day:
        return _day_prompt(lead)

    slots = _store_time_options(lead, day)
    if not slots:
        sc._set_tag(lead, "Q_MEETING_DAY", "")
        return (
            "⚠️ *Esse dia não possui mais horários livres entre 11:00 e 15:00.*\n\n" +
            _day_prompt(lead)
        )

    options = [
        {"id": str(i + 1), "title": slot.strftime("%H:%M")}
        for i, slot in enumerate(slots)
    ]
    return fm._list_marker(
        f"⏰ *Perfeito! Para {_format_day(day)}, escolha um horário disponível:*\n\n"
        "As reuniões duram *1 hora*. O CRM mostra somente os horários livres "
        "entre *11:00 e 15:00*.",
        "Escolher horário",
        options,
    )


def _confirmation(lead):
    raw = sc._tag_value(lead, "Q_MEETING_SLOT")
    if not raw:
        return None
    try:
        slot = datetime.fromisoformat(raw)
        return (
            f"✅ *Reunião confirmada para {sc._format_slot(slot)}.*\n"
            "Duração: *1 hora*. Nosso consultor falará com você no horário agendado. 🍻"
        )
    except Exception:
        return None


_previous_apply = p._apply_answer_by_count


def _apply_day_time(lead, text, inbound_count, channel):
    if lead.meeting_interest != "Sim":
        return _previous_apply(lead, text, inbound_count, channel)

    if sc._tag_value(lead, "Q_MEETING_SLOT"):
        return _previous_apply(lead, text, inbound_count, channel)

    if inbound_count >= 9 and not _selected_day(lead):
        day = _select_day(lead, text)
        if day:
            sc._set_tag(lead, "Q_MEETING_DAY", day.isoformat())
            _store_time_options(lead, day)
        crm.requalify(lead, preserve=False)
        lead.stage = "Prioridade / Reunião"
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action=f"Dia da reunião selecionado pelo {channel}",
            detail=f"dia={day.isoformat() if day else 'invalido'}",
        ))
        return

    if inbound_count >= 10 and _selected_day(lead):
        ok = _schedule_selected_time(lead, text)
        crm.requalify(lead, preserve=False)
        if ok:
            lead.stage = "Reunião Agendada"
        else:
            lead.stage = "Prioridade / Reunião"
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action=f"Horário da reunião selecionado pelo {channel}",
            detail=f"confirmado={ok}",
        ))
        return

    return _previous_apply(lead, text, inbound_count, channel)


p._apply_answer_by_count = _apply_day_time


_prev_instagram = p._reply_for_instagram
_prev_whatsapp = p._reply_for_message
_prev_qualification = fm._qualification_reply


def _state_reply(lead, channel):
    if lead.meeting_interest != "Sim":
        return None

    selected = _confirmation(lead)
    if selected:
        return selected

    count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()

    if count >= 8 and not _selected_day(lead):
        return _day_prompt(lead)

    if count >= 9 and _selected_day(lead):
        return _time_prompt(lead)

    return None


def _reply_instagram(lead):
    state = _state_reply(lead, "Instagram")
    return state if state else _prev_instagram(lead)


def _reply_whatsapp(lead, text):
    state = _state_reply(lead, "WhatsApp")
    return state if state else _prev_whatsapp(lead, text)


def _qualification(lead, channel):
    state = _state_reply(lead, channel)
    return state if state else _prev_qualification(lead, channel)


p._reply_for_instagram = _reply_instagram
p._reply_for_message = _reply_whatsapp
fm._qualification_reply = _qualification
