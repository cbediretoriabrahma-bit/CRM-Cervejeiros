"""Correção robusta do agendamento automático do CRM Cervejeiros.

Objetivos:
- Oferecer reuniões de hora em hora, das 09:00 às 20:00.
- Nunca oferecer horário que já esteja ocupado por outra reunião pendente.
- Invalidar opções antigas armazenadas se algum horário for ocupado depois.
- Aceitar no Instagram/WhatsApp tanto o número da opção quanto o texto visível
  do horário (ex.: 'segunda, 14/09 às 15:00').
- Se o usuário escolher um horário que acabou de ser ocupado, gerar novas opções
  e continuar o fluxo, sem travar por causa da contagem de mensagens.
"""
import re
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import final_qualification_patch as fq
import flow_media_patch as fm
import patched_app as p
import sitecustomize as sc

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")


def _meeting_hours_fixed():
    # 09:00, 10:00, ... 20:00 (inclusive).
    return [time(hour, 0) for hour in range(9, 21)]


def _slot_is_free_fixed(local_dt, owner_id=None):
    """Bloqueia globalmente qualquer horário que já tenha uma reunião pendente."""
    utc_naive = local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end = utc_naive + timedelta(hours=1)
    return crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at >= utc_naive,
        crm.Task.due_at < end,
    ).first() is None


def _clear_stored_slots(lead):
    # Mantém as tags, mas as sobrescreve quando novas opções forem geradas.
    for i in range(1, 4):
        sc._set_tag(lead, f"Q_SLOT_{i}", "")


def _meeting_options_fixed(lead, refresh=False):
    # Só reaproveita opções guardadas se TODAS ainda estiverem livres e futuras.
    now = datetime.now(TZ)
    if not refresh:
        stored = []
        for i in range(1, 4):
            raw = sc._tag_value(lead, f"Q_SLOT_{i}")
            if not raw:
                stored = []
                break
            try:
                slot = datetime.fromisoformat(raw)
                if slot.tzinfo is None:
                    slot = slot.replace(tzinfo=TZ)
                else:
                    slot = slot.astimezone(TZ)
            except Exception:
                stored = []
                break
            if slot <= now or not _slot_is_free_fixed(slot):
                stored = []
                break
            stored.append(slot)
        if len(stored) == 3:
            return stored

    options = []
    for add_day in range(0, 15):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() >= 5:  # segunda a sexta
            continue
        for hr in _meeting_hours_fixed():
            slot = datetime.combine(day, hr, tzinfo=TZ)
            if slot <= now + timedelta(hours=2):
                continue
            if _slot_is_free_fixed(slot):
                options.append(slot)
            if len(options) == 3:
                break
        if len(options) == 3:
            break

    for i in range(1, 4):
        value = options[i - 1].isoformat() if i <= len(options) else ""
        sc._set_tag(lead, f"Q_SLOT_{i}", value)
    return options


def _normalized(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _find_selected_slot(lead, text):
    options = _meeting_options_fixed(lead, refresh=False)
    if not options:
        return None

    raw = _normalized(text)

    # Número/payload 1, 2 ou 3.
    m = re.fullmatch(r"[123]", raw)
    if m:
        idx = int(raw) - 1
        return options[idx] if idx < len(options) else None

    # Texto do quick reply do Instagram/WhatsApp.
    for slot in options:
        labels = {
            _normalized(sc._format_slot(slot)),
            _normalized(sc._format_slot(slot)[:20]),
            _normalized(slot.strftime("%d/%m às %H:%M")),
            _normalized(slot.strftime("%d/%m as %H:%M")),
        }
        # Também tolera o título truncado sem :00 no fim.
        labels.add(_normalized(sc._format_slot(slot).replace(":00", "")))
        labels.add(_normalized(sc._format_slot(slot)[:20].replace(":00", "")))
        if raw in labels:
            return slot

    return None


def _schedule_choice_fixed(lead, text):
    slot = _find_selected_slot(lead, text)
    if slot is None:
        # Pode ter sido uma opção antiga; force a geração de opções novas.
        _meeting_options_fixed(lead, refresh=True)
        return False

    # Checagem transacional final imediatamente antes de gravar.
    if not _slot_is_free_fixed(slot):
        _meeting_options_fixed(lead, refresh=True)
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

    # Salva a posição apenas para auditoria quando ela existir.
    current_options = _meeting_options_fixed(lead, refresh=False)
    try:
        choice = current_options.index(slot) + 1
        sc._set_tag(lead, "Q_MEETING_CHOICE", choice)
    except ValueError:
        pass

    current = (lead.notes or "").strip()
    line = f"Reunião agendada: {sc._format_slot(slot)} | duração: 1 hora"
    lead.notes = current + ("\n" if current else "") + line
    return True


# Substitui os utilitários compartilhados usados pelo fluxo final.
sc._meeting_hours = _meeting_hours_fixed
sc._slot_is_free = _slot_is_free_fixed
sc._meeting_options = _meeting_options_fixed
sc._schedule_choice = _schedule_choice_fixed


_original_apply = p._apply_answer_by_count


def _apply_answer_scheduler_safe(lead, text, inbound_count, channel):
    # Depois que o lead aceitou a reunião, qualquer mensagem até a confirmação
    # é tratada como tentativa de escolha de horário, independentemente da
    # contagem de mensagens. Isso impede o fluxo de travar após uma opção inválida.
    if lead.meeting_interest == "Sim" and not sc._tag_value(lead, "Q_MEETING_SLOT") and inbound_count >= 9:
        _schedule_choice_fixed(lead, text)
        crm.requalify(lead, preserve=False)
        if sc._tag_value(lead, "Q_MEETING_SLOT"):
            lead.stage = "Reunião Agendada"
        else:
            lead.stage = "Prioridade / Reunião"
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action=f"Tentativa de agendamento pelo {channel}",
            detail=f"Mensagem {inbound_count}; horario_confirmado={bool(sc._tag_value(lead, 'Q_MEETING_SLOT'))}",
        ))
        return
    return _original_apply(lead, text, inbound_count, channel)


p._apply_answer_by_count = _apply_answer_scheduler_safe


def _schedule_reply(lead, channel):
    selected = sc._tag_value(lead, "Q_MEETING_SLOT")
    if selected:
        try:
            slot = datetime.fromisoformat(selected)
            return (
                f"✅ *Reunião confirmada para {sc._format_slot(slot)}.*\n"
                "Duração: *1 hora*. Nosso consultor falará com você no horário agendado. 🍻"
            )
        except Exception:
            pass

    options = _meeting_options_fixed(lead, refresh=True)
    if len(options) >= 3:
        return fm._buttons_marker(
            "⚠️ *Esse horário não está mais disponível.*\n\n"
            "Escolha uma destas *novas opções disponíveis*:",
            [
                {"id": "1", "title": sc._format_slot(options[0])[:20]},
                {"id": "2", "title": sc._format_slot(options[1])[:20]},
                {"id": "3", "title": sc._format_slot(options[2])[:20]},
            ],
        )
    return (
        "No momento não encontrei três horários livres. "
        "Nosso consultor entrará em contato para combinar um horário disponível."
    )


_previous_reply_instagram = p._reply_for_instagram
_previous_reply_message = p._reply_for_message


def _reply_instagram_scheduler_safe(lead):
    # Se já aceitou a reunião, o estado da agenda manda mais que a contagem.
    if lead.meeting_interest == "Sim":
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel="Instagram", direction="in"
        ).count()
        if inbound_count >= 9:
            return _schedule_reply(lead, "Instagram")
    return _previous_reply_instagram(lead)


def _reply_whatsapp_scheduler_safe(lead, text):
    if lead.meeting_interest == "Sim":
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel="WhatsApp", direction="in"
        ).count()
        if inbound_count >= 9:
            return _schedule_reply(lead, "WhatsApp")
    return _previous_reply_message(lead, text)


p._reply_for_instagram = _reply_instagram_scheduler_safe
p._reply_for_message = _reply_whatsapp_scheduler_safe

# O webhook rico do WhatsApp consulta fm._qualification_reply diretamente.
_original_qualification = fm._qualification_reply


def _qualification_scheduler_safe(lead, channel):
    if lead.meeting_interest == "Sim":
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel=channel, direction="in"
        ).count()
        if inbound_count >= 9:
            return _schedule_reply(lead, channel)
    return _original_qualification(lead, channel)


fm._qualification_reply = _qualification_scheduler_safe
