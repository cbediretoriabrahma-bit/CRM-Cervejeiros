"""Hotfix do Direct/WhatsApp: horários do Instagram e faixas de investimento.

1) Reconhece o texto visível enviado pelo Instagram nas opções de horário,
   por exemplo "Manhã • 10:00" e "Tarde • 13:00".
2) Evita que as faixas de investimento pareçam números de telefone clicáveis,
   usando "mil" nos títulos em vez de sequências numéricas com hífen.
"""
import re

import flow_media_patch as fm
import meeting_day_selection_patch as mds
import patched_app as p

crm = p.crm


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _find_time_hotfix(lead, text):
    """Aceita ID, horário puro e o rótulo exibido pelo Instagram."""
    day = mds._selected_day(lead)
    if not day:
        return None

    slots = mds._store_time_options(lead, day)
    raw = _norm(text)

    if re.fullmatch(r"[1-4]", raw):
        idx = int(raw) - 1
        return slots[idx] if idx < len(slots) else None

    time_match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", raw)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        for slot in slots:
            if slot.hour == hour and slot.minute == minute:
                return slot

    for slot in slots:
        labels = {
            _norm(slot.strftime("%H:%M")),
            _norm(slot.strftime("%Hh")),
            _norm(slot.strftime("%H")),
            _norm(mds.sc._format_slot(slot)),
            _norm(mds.sc._format_slot(slot)[:20]),
            _norm(mds.sc._format_slot(slot).replace(":00", "")),
            _norm(f"Manhã • {slot.strftime('%H:%M')}") if slot.hour < 12 else "",
            _norm(f"Tarde • {slot.strftime('%H:%M')}") if slot.hour >= 12 else "",
        }
        if raw in labels:
            return slot
    return None


mds._find_time = _find_time_hotfix


_prev_instagram = p._reply_for_instagram
_prev_whatsapp = p._reply_for_message
_prev_qualification = fm._qualification_reply


def _investment_prompt():
    return fm._buttons_marker(
        "*Qual faixa de investimento inicial você pretende realizar?*",
        [
            {"id": "1", "title": "R$18,9mil a R$29,9mil"},
            {"id": "2", "title": "R$30mil a R$44,9mil"},
            {"id": "3", "title": "R$45mil a R$55mil"},
        ],
    )


def _count(lead, channel):
    return crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()


def _reply_instagram(lead):
    if _count(lead, "Instagram") == 4:
        return _investment_prompt()
    return _prev_instagram(lead)


def _reply_whatsapp(lead, text):
    if _count(lead, "WhatsApp") == 4:
        return _investment_prompt()
    return _prev_whatsapp(lead, text)


def _qualification(lead, channel):
    if _count(lead, channel) == 4:
        return _investment_prompt()
    return _prev_qualification(lead, channel)


p._reply_for_instagram = _reply_instagram
p._reply_for_message = _reply_whatsapp
fm._qualification_reply = _qualification

# Carrega por último o fluxo de cadastro inicial e apresentação comercial.
import onboarding_contact_patch  # noqa: F401,E402

# Substitui o convite final por uma única ação: agendar reunião com o consultor.
import single_consultant_cta_patch  # noqa: F401,E402
