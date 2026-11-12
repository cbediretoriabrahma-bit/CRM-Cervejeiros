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


def _slot_free_30min(slot):
    """Checa sobreposicao com reunioes de 30 ou 60 minutos, de todos os consultores."""
    start = slot.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end = start + timedelta(minutes=30)
    existing = crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at > start - timedelta(hours=1),
        crm.Task.due_at < end,
    ).all()
    for task in existing:
        note = (task.notes or "").lower()
        duration = timedelta(minutes=30 if ("30 minutos" in note or "meia hora" in note) else 60)
        if task.due_at < end and task.due_at + duration > start:
            return False
    return True


def _free_slots_for_day(lead, day):
    """11:00 a 18:00, de 30 em 30 minutos; ultimo inicio as 17:30."""
    now = datetime.now(TZ)
    slots = []
    for minutes in range(11 * 60, 18 * 60, 30):
        slot = datetime.combine(day, datetime.min.time(), tzinfo=TZ) + timedelta(minutes=minutes)
        if slot <= now + timedelta(hours=2):
            continue
        if _slot_free_30min(slot):
            slots.append(slot)
    return slots

def _available_days(lead, refresh=False):
    """Dias de segunda a sexta no periodo dos proximos 15 dias corridos."""
    now = datetime.now(TZ)
    days = []
    for add_day in range(15):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() < 5 and _free_slots_for_day(lead, day):
            days.append(day)
    return days


def _page(lead, key, total, size=8):
    try:
        page = max(0, int(sc._tag_value(lead, key) or 0))
    except (ValueError, TypeError):
        page = 0
    return min(page, max(0, (total - 1) // size))

def _select_day(lead, text):
    days = _available_days(lead, refresh=True)
    raw = _norm(text)
    page = _page(lead, "Q_DAY_PAGE", len(days))
    if raw in {"next_days", "proximos dias", "próximos dias"}:
        sc._set_tag(lead, "Q_DAY_PAGE", min(page + 1, max(0, (len(days) - 1) // 8)))
        return None
    if raw in {"prev_days", "dias anteriores"}:
        sc._set_tag(lead, "Q_DAY_PAGE", max(0, page - 1))
        return None
    visible = days[page * 8:(page + 1) * 8]
    for day in visible:
        if raw in {_norm(day.isoformat()), _norm(_format_day(day)), _norm(day.strftime("%d/%m"))}:
            return day
    # Compatibilidade com respostas antigas por numero da opcao.
    if re.fullmatch(r"[1-8]", raw):
        idx = int(raw) - 1
        return visible[idx] if idx < len(visible) else None
    return None

def _store_time_options(lead, day):
    # Armazena identificadores sem sobrescrever o numero de telefone do lead.
    slots = _free_slots_for_day(lead, day)
    for i in range(1, 15):
        sc._set_tag(lead, f"Q_SLOT_{i}", slots[i - 1].isoformat() if i <= len(slots) else "")
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
    page = _page(lead, "Q_TIME_PAGE", len(slots))
    if raw in {"next_times", "mais horarios", "mais horários"}:
        sc._set_tag(lead, "Q_TIME_PAGE", min(page + 1, max(0, (len(slots) - 1) // 8)))
        return None
    if raw in {"prev_times", "horarios anteriores", "horários anteriores"}:
        sc._set_tag(lead, "Q_TIME_PAGE", max(0, page - 1))
        return None
    visible = slots[page * 8:(page + 1) * 8]
    for slot in visible:
        if raw in {_norm(slot.strftime("%H:%M")), _norm(slot.isoformat()),
                   _norm(f"{slot.hour}h{slot.minute:02d}"), _norm(sc._format_slot(slot))}:
            return slot
    if re.fullmatch(r"[1-8]", raw):
        idx = int(raw) - 1
        return visible[idx] if idx < len(visible) else None
    return None

def _schedule_selected_time(lead, text):
    slot = _find_time(lead, text)
    if slot is None:
        return False

    # Revalida no instante da confirmação para impedir agendamento duplicado.
    if not _slot_free_30min(slot):
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
        notes=f"Reunião comercial de 30 minutos agendada automaticamente para {sc._format_slot(slot)}.",
    ))
    lead.next_followup = utc_naive
    lead.stage = "Reunião Agendada"
    sc._set_tag(lead, "Q_MEETING_SLOT", slot.isoformat())
    current = (lead.notes or "").strip()
    line = f"Reunião agendada: {sc._format_slot(slot)} | duração: 30 minutos"
    lead.notes = current + ("\n" if current else "") + line
    return True


def _day_prompt(lead):
    days = _available_days(lead, refresh=True)
    if not days:
        return "No momento não encontrei horários livres nos próximos 15 dias. Nosso consultor entrará em contato."
    page = _page(lead, "Q_DAY_PAGE", len(days))
    visible = days[page * 8:(page + 1) * 8]
    options = [{"id": day.isoformat(), "title": _format_day(day)[:24]} for day in visible]
    if page > 0:
        options.append({"id": "PREV_DAYS", "title": "Dias anteriores"})
    if (page + 1) * 8 < len(days):
        options.append({"id": "NEXT_DAYS", "title": "Próximos dias"})
    return fm._list_marker(
        "📅 *Escolha o dia da reunião* nos próximos *15 dias*, de segunda a sexta-feira. "
        "Use Próximos dias para ver outras datas disponíveis.",
        "Escolher dia", options
    )

def _time_prompt(lead, refresh=True):
    day = _selected_day(lead)
    if not day:
        return _day_prompt(lead)
    slots = _store_time_options(lead, day)
    if not slots:
        sc._set_tag(lead, "Q_MEETING_DAY", "")
        sc._set_tag(lead, "Q_DAY_PAGE", "0")
        return "⚠️ Este dia ficou sem horários livres.\n\n" + _day_prompt(lead)
    page = _page(lead, "Q_TIME_PAGE", len(slots))
    visible = slots[page * 8:(page + 1) * 8]
    options = [{"id": slot.strftime("%H:%M"), "title": slot.strftime("%H:%M")} for slot in visible]
    if page > 0:
        options.append({"id": "PREV_TIMES", "title": "Horários anteriores"})
    if (page + 1) * 8 < len(slots):
        options.append({"id": "NEXT_TIMES", "title": "Mais horários"})
    return fm._list_marker(
        f"⏰ *Para {_format_day(day)}, escolha um horário livre.*\n\n"
        "Reuniões de *30 minutos*, das *11:00 às 18:00*, com início até 17:30. "
        "Use Mais horários para ver as outras opções.",
        "Escolher horário", options
    )

def _confirmation(lead):
    raw = sc._tag_value(lead, "Q_MEETING_SLOT")
    if not raw:
        return None
    try:
        slot = datetime.fromisoformat(raw)
        return (
            f"✅ *Reunião confirmada para {sc._format_slot(slot)}.*\n"
            "Duração: *30 minutos*. Nosso consultor falará com você no horário agendado. 🍻"
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
