"""Calendário visual de disponibilidade de reuniões no Dashboard.

Mostra somente dias, horários e ocupação. Não expõe nomes dos leads.
Também mantém os relatórios sincronizados com a etapa atual do Pipeline.
"""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import patched_app as p
import meeting_report_patch as mr

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

WEEKDAYS_SHORT = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]


def _valid_pending_meetings():
    """Retorna somente reuniões pendentes que ainda correspondem à etapa atual do lead."""
    tasks = (
        mr._visible_meeting_query()
        .filter(crm.Task.status == "Pendente")
        .order_by(crm.Task.due_at.asc())
        .all()
    )
    valid = []
    for task in tasks:
        lead = task.lead
        if not lead:
            continue
        if mr._is_second_meeting(task):
            if lead.stage != "2ª Reunião Agendada":
                continue
        else:
            if lead.stage != "Reunião Agendada":
                continue
        valid.append(task)
    return valid


def _dashboard_meetings_synced():
    return _valid_pending_meetings()[:30]


def _dashboard_first_meetings_synced():
    return [t for t in _dashboard_meetings_synced() if not mr._is_second_meeting(t)]


def _dashboard_second_meetings_synced():
    return [t for t in _dashboard_meetings_synced() if mr._is_second_meeting(t)]


def _local_dt(value):
    if not value:
        return None
    return value.replace(tzinfo=UTC).astimezone(TZ)


def _next_business_days(count=10):
    day = datetime.now(TZ).date()
    days = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _meeting_availability_calendar(count=10):
    """Monta a grade dos próximos dias úteis, das 09h às 20h.

    Vermelho no template significa ocupado; branco significa livre. Não retorna
    nome, telefone ou qualquer outra identificação do lead.
    """
    try:
        count = max(1, min(int(count), 15))
    except Exception:
        count = 10

    now = datetime.now(TZ)
    days = _next_business_days(count)
    meetings = _valid_pending_meetings()

    occupied = set()
    for task in meetings:
        local = _local_dt(task.due_at)
        if not local:
            continue
        occupied.add((local.date(), local.hour))

    hours = [f"{hour:02d}:00" for hour in range(9, 21)]
    day_items = []
    for day in days:
        slots = []
        for hour in range(9, 21):
            slot_dt = datetime.combine(day, time(hour, 0), tzinfo=TZ)
            slots.append({
                "occupied": (day, hour) in occupied,
                "past": slot_dt < now,
            })
        day_items.append({
            "weekday": WEEKDAYS_SHORT[day.weekday()],
            "date": day.strftime("%d/%m"),
            "slots": slots,
        })

    return {
        "days": day_items,
        "hours": hours,
        "occupied_count": len(occupied),
    }


@crm.app.context_processor
def _dashboard_calendar_context():
    # Estes nomes substituem os helpers antigos no template e impedem que
    # reuniões antigas de leads que voltaram no Pipeline continuem aparecendo.
    return {
        "dashboard_meetings": _dashboard_meetings_synced,
        "dashboard_first_meetings": _dashboard_first_meetings_synced,
        "dashboard_second_meetings": _dashboard_second_meetings_synced,
        "meeting_availability_calendar": _meeting_availability_calendar,
    }
