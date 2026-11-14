"""Calendário e correções de agenda do CRM Cervejeiros.

Este patch mantém o Dashboard sincronizado com a etapa atual do Pipeline e
corrige o reagendamento da 2ª reunião. Uma reunião antiga/atrasada do mesmo lead
é atualizada, em vez de continuar pendente e aparecer como duplicada.
"""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from flask import flash, redirect, render_template, request, url_for

import patched_app as p
import meeting_report_patch as mr

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
WEEKDAYS_SHORT = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]


def _local_dt(value):
    if not value:
        return None
    return value.replace(tzinfo=UTC).astimezone(TZ)


def _format_day(day):
    return f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d/%m')}"


def _format_slot(slot):
    return f"{WEEKDAYS[slot.weekday()]}, {slot.strftime('%d/%m')} às {slot.strftime('%H:%M')}"


def _pending_second_meetings(lead_id):
    tasks = (
        crm.Task.query.filter_by(lead_id=lead_id, task_type="Reunião", status="Pendente")
        .order_by(crm.Task.due_at.desc(), crm.Task.id.desc())
        .all()
    )
    return [task for task in tasks if mr._is_second_meeting(task)]


def _meeting_duration(task):
    notes = (task.notes or "").lower()
    return timedelta(minutes=30 if "30 minutos" in notes or "meia hora" in notes else 60)


def _slot_conflict(local_dt, exclude_task_ids=None):
    """Retorna reunião pendente que se sobrepõe ao intervalo de 30 minutos."""
    exclude_task_ids = set(exclude_task_ids or [])
    start = local_dt.astimezone(UTC).replace(tzinfo=None)
    end = start + timedelta(minutes=30)

    query = crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at > start - timedelta(hours=1),
        crm.Task.due_at < end,
    )
    if exclude_task_ids:
        query = query.filter(~crm.Task.id.in_(exclude_task_ids))

    for task in query.order_by(crm.Task.due_at).all():
        if start < task.due_at + _meeting_duration(task) and task.due_at < end:
            return task
    return None


def _second_meeting_slots_for_day(day, lead_id=None):
    """Horários livres de 30 em 30 minutos, das 11h às 17h30."""
    now = datetime.now(TZ)
    current_ids = [t.id for t in _pending_second_meetings(lead_id)] if lead_id else []
    slots = []
    for minutes in range(11 * 60, 18 * 60, 30):
        slot = datetime.combine(day, time.min, tzinfo=TZ) + timedelta(minutes=minutes)
        if slot <= now + timedelta(hours=2):
            continue
        if _slot_conflict(slot, current_ids) is None:
            slots.append(slot)
    return slots


def _second_meeting_days(lead_id=None):
    """Dias úteis com horário livre nos próximos 30 dias corridos."""
    now = datetime.now(TZ)
    days = []
    for add_day in range(0, 31):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() < 5 and _second_meeting_slots_for_day(day, lead_id):
            days.append(day)
    return days


def _valid_pending_meetings():
    """Mostra somente a reunião que corresponde à etapa atual do lead.

    Isso evita que uma 2ª reunião antiga continue aparecendo como ATRASADA quando
    o lead ainda está em 1ª Reunião Realizada ou quando uma nova data já foi salva.
    Em caso de registros duplicados, conserva no Dashboard apenas o compromisso
    pendente mais recente de cada lead/tipo.
    """
    tasks = (
        mr._visible_meeting_query()
        .filter(crm.Task.status == "Pendente")
        .order_by(crm.Task.due_at.desc(), crm.Task.id.desc())
        .all()
    )

    chosen = {}
    for task in tasks:
        lead = task.lead
        if not lead:
            continue
        stage = (lead.stage or "").strip()
        if stage in {"Fechado", "Perdido"}:
            continue

        is_second = mr._is_second_meeting(task)
        if is_second and stage != "2ª Reunião Agendada":
            continue
        if not is_second and stage != "Reunião Agendada":
            continue

        key = (lead.id, 2 if is_second else 1)
        if key not in chosen:
            chosen[key] = task

    return sorted(chosen.values(), key=lambda task: task.due_at or datetime.max)


def _dashboard_meetings_synced():
    return _valid_pending_meetings()


def _dashboard_first_meetings_synced():
    return [t for t in _dashboard_meetings_synced() if not mr._is_second_meeting(t)]


def _dashboard_second_meetings_synced():
    return [t for t in _dashboard_meetings_synced() if mr._is_second_meeting(t)]


def _meeting_availability_calendar(count=31):
    """Grade das vagas nos próximos 30 dias corridos, de segunda a sexta."""
    try:
        count = max(1, min(int(count), 31))
    except Exception:
        count = 31

    now = datetime.now(TZ)
    days = [
        (now + timedelta(days=offset)).date()
        for offset in range(count)
        if (now + timedelta(days=offset)).weekday() < 5
    ]
    meetings = _valid_pending_meetings()

    occupied = set()
    for task in meetings:
        local = _local_dt(task.due_at)
        if not local:
            continue
        meeting_end = local + _meeting_duration(task)
        for minutes in range(11 * 60, 18 * 60, 30):
            slot_start = datetime.combine(local.date(), time.min, tzinfo=TZ) + timedelta(minutes=minutes)
            if local < slot_start + timedelta(minutes=30) and slot_start < meeting_end:
                occupied.add((local.date(), slot_start.hour, slot_start.minute))

    hours = [f"{minutes // 60:02d}:{minutes % 60:02d}" for minutes in range(11 * 60, 18 * 60, 30)]
    day_items = []
    for day in days:
        slots = []
        for minutes in range(11 * 60, 18 * 60, 30):
            hour, minute = divmod(minutes, 60)
            slot_dt = datetime.combine(day, time.min, tzinfo=TZ) + timedelta(minutes=minutes)
            slots.append({
                "hour": f"{hour:02d}:{minute:02d}",
                "occupied": (day, hour, minute) in occupied,
                "past": slot_dt <= now,
            })
        day_items.append({
            "iso": day.isoformat(),
            "weekday": WEEKDAYS_SHORT[day.weekday()],
            "date": day.strftime("%d/%m"),
            "slots": slots,
        })

    return {
        "days": day_items,
        "hours": hours,
        "occupied_count": len(occupied),
    }



@crm.login_required
def _lead_second_meeting_fixed(lead_id):
    """Agenda ou REAGENDA a 2ª reunião sem deixar compromisso antigo pendente."""
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()
    selected_day = None

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "select_day":
            raw_day = (request.form.get("day") or "").strip()
            try:
                selected_day = datetime.fromisoformat(raw_day).date()
            except Exception:
                flash("Dia inválido. Escolha uma das opções disponíveis.", "danger")
                return redirect(url_for("lead_second_meeting", lead_id=lead.id))

            if (selected_day < datetime.now(TZ).date()
                    or selected_day > datetime.now(TZ).date() + timedelta(days=30)
                    or selected_day.weekday() >= 5
                    or not _second_meeting_slots_for_day(selected_day, lead.id)):
                flash("Escolha um dia útil dentro dos próximos 30 dias que tenha horário livre.", "warning")
                return redirect(url_for("lead_second_meeting", lead_id=lead.id))

        elif action == "confirm_slot":
            raw_slot = (request.form.get("slot") or "").strip()
            raw_day = (request.form.get("day") or "").strip()
            try:
                slot = datetime.fromisoformat(raw_slot)
                selected_day = datetime.fromisoformat(raw_day).date()
            except Exception:
                flash("Horário inválido. Escolha novamente.", "danger")
                return redirect(url_for("lead_second_meeting", lead_id=lead.id))

            if slot.tzinfo is None:
                slot = slot.replace(tzinfo=TZ)
            else:
                slot = slot.astimezone(TZ)

            if (
                slot.date() != selected_day
                or slot.weekday() >= 5
                or slot.date() < datetime.now(TZ).date()
                or slot.date() > datetime.now(TZ).date() + timedelta(days=30)
                or not (11 <= slot.hour <= 17)
                or slot.minute not in (0, 30)
                or (slot.hour == 17 and slot.minute > 30)
                or slot <= datetime.now(TZ)
            ):
                flash("Horário inválido. A 2ª reunião deve ser marcada nos próximos 30 dias, entre 11:00 e 17:30, a cada 30 minutos.", "danger")
                return redirect(url_for("lead_second_meeting", lead_id=lead.id))

            existing = _pending_second_meetings(lead.id)
            existing_ids = [task.id for task in existing]
            conflict = _slot_conflict(slot, existing_ids)
            if conflict:
                flash("Esse horário acabou de ser ocupado por outra reunião. Escolha outro horário disponível.", "warning")
                options = _second_meeting_slots_for_day(selected_day, lead.id)
                return render_template(
                    "second_meeting.html",
                    lead=lead,
                    days=[],
                    selected_day=selected_day.isoformat(),
                    selected_day_label=_format_day(selected_day),
                    options=[(s.isoformat(), s.strftime("%H:%M")) for s in options],
                )

            utc_naive = slot.astimezone(UTC).replace(tzinfo=None)
            new_label = _format_slot(slot)

            if existing:
                task = existing[0]
                old_local = _local_dt(task.due_at)
                old_label = _format_slot(old_local) if old_local else "sem data"
                task.due_at = utc_naive
                task.owner_id = lead.owner_id
                task.title = f"2ª reunião com {lead.name}"
                task.status = "Pendente"
                task.notes = (
                    (task.notes or "").rstrip()
                    + f"\n2ª reunião reagendada de {old_label} para {new_label}. Duração: 30 minutos."
                ).strip()

                # Se havia duplicidades antigas, elas deixam de bloquear a agenda.
                for duplicate in existing[1:]:
                    duplicate.status = "Substituída"
                    duplicate.notes = (
                        (duplicate.notes or "").rstrip()
                        + f"\nSubstituída pelo reagendamento da 2ª reunião para {new_label}."
                    ).strip()

                action_name = "2ª reunião reagendada"
                detail = f"Reagendada de {old_label} para {new_label}. Registros duplicados antigos foram desativados."
                success = f"2ª reunião reagendada com sucesso para {new_label}."
            else:
                task = crm.Task(
                    lead_id=lead.id,
                    owner_id=lead.owner_id,
                    title=f"2ª reunião com {lead.name}",
                    task_type="Reunião",
                    due_at=utc_naive,
                    status="Pendente",
                    notes=f"2ª reunião comercial de 30 minutos agendada para {new_label}.",
                )
                crm.db.session.add(task)
                action_name = "2ª reunião agendada"
                detail = f"Agendada para {new_label}. Horário validado contra as reuniões existentes."
                success = f"2ª reunião agendada com sucesso para {new_label}."

            lead.next_followup = utc_naive
            lead.stage = "2ª Reunião Agendada"
            crm.db.session.add(crm.AutomationLog(
                lead_id=lead.id,
                action=action_name,
                detail=detail,
            ))
            crm.db.session.commit()
            flash(success, "success")
            return redirect(url_for("pipeline"))

    if selected_day:
        options = _second_meeting_slots_for_day(selected_day, lead.id)
        return render_template(
            "second_meeting.html",
            lead=lead,
            days=[],
            selected_day=selected_day.isoformat(),
            selected_day_label=_format_day(selected_day),
            options=[(slot.isoformat(), slot.strftime("%H:%M")) for slot in options],
        )

    days = _second_meeting_days(lead.id)
    return render_template(
        "second_meeting.html",
        lead=lead,
        days=[(day.isoformat(), _format_day(day)) for day in days],
        selected_day=None,
        selected_day_label=None,
        options=[],
    )


# O endpoint já foi criado em crm_entry.py. Aqui trocamos somente o handler,
# mantendo a mesma URL e os botões existentes.
if "lead_second_meeting" in crm.app.view_functions:
    crm.app.view_functions["lead_second_meeting"] = _lead_second_meeting_fixed


@crm.app.context_processor
def _dashboard_calendar_context():
    return {
        "dashboard_meetings": _dashboard_meetings_synced,
        "dashboard_first_meetings": _dashboard_first_meetings_synced,
        "dashboard_second_meetings": _dashboard_second_meetings_synced,
        "meeting_availability_calendar": _meeting_availability_calendar,
    }
