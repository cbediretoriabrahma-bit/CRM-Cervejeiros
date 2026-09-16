import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from flask import flash, redirect, render_template, request, url_for

import patched_app as patched
import sitecustomize  # noqa: F401
import reply_format_patch  # noqa: F401

if not os.getenv("QUALIFICATION_VIDEO_URL"):
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        os.environ["QUALIFICATION_VIDEO_URL"] = (
            f"{render_url}/static/qualificacao_cervejeiros_web.mp4"
        )

import flow_media_patch  # noqa: F401
import instagram_video_patch  # noqa: F401

crm = patched.crm
app = patched.app

COMMERCIAL_PIPELINE = [
    "Novo Lead",
    "Em Qualificação",
    "Qualificado",
    "Lead Quente",
    "Reunião Agendada",
    "1ª Reunião Realizada",
    "2ª Reunião Agendada",
    "2ª Reunião Realizada",
    "Contrato Enviado",
    "Fechado",
    "Perdido",
]
crm.PIPELINE[:] = COMMERCIAL_PIPELINE


def _commercial_auto_stage(lead, preserve=True):
    manual_stages = {
        "Reunião Agendada",
        "1ª Reunião Realizada",
        "2ª Reunião Agendada",
        "2ª Reunião Realizada",
        "Contrato Enviado",
        "Fechado",
        "Perdido",
    }
    if preserve and lead.stage in manual_stages:
        return lead.stage
    if lead.meeting_interest == "Sim" or lead.score >= 60:
        return "Lead Quente"
    if lead.score >= 40:
        return "Qualificado"
    if lead.score >= 20:
        return "Em Qualificação"
    return "Novo Lead"


crm.auto_stage = _commercial_auto_stage

TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _meeting_hours():
    return [time(hour, 0) for hour in range(9, 21)]


def _slot_is_free(local_dt, owner_id=None):
    """Bloqueia o horário se existir QUALQUER reunião pendente no mesmo intervalo.

    Vale igualmente para 1ª e 2ª reunião e para qualquer responsável, evitando
    dois compromissos do CRM no mesmo horário.
    """
    utc_naive = local_dt.astimezone(UTC).replace(tzinfo=None)
    start = utc_naive
    end = utc_naive + timedelta(hours=1)
    conflict = crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at >= start,
        crm.Task.due_at < end,
    ).first()
    return conflict is None


def _format_day(day):
    return f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d/%m')}"


def _format_slot(slot):
    return f"{WEEKDAYS[slot.weekday()]}, {slot.strftime('%d/%m')} às {slot.strftime('%H:%M')}"


def _second_meeting_slots_for_day(day):
    """Para a 2ª reunião, oferece somente horários da tarde (13h às 20h)."""
    now = datetime.now(TZ)
    slots = []
    for hour in range(13, 21):
        slot = datetime.combine(day, time(hour, 0), tzinfo=TZ)
        if slot <= now + timedelta(hours=2):
            continue
        if _slot_is_free(slot):
            slots.append(slot)
    return slots


def _second_meeting_days():
    """Mostra dias úteis que tenham pelo menos 2 horários livres à tarde."""
    now = datetime.now(TZ)
    days = []
    for add_day in range(0, 30):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() >= 5:
            continue
        if len(_second_meeting_slots_for_day(day)) >= 2:
            days.append(day)
        if len(days) == 5:
            break
    return days


@app.route("/lead/<int:lead_id>/second-meeting", methods=["GET", "POST"])
@crm.login_required
def lead_second_meeting(lead_id):
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

            if selected_day.weekday() >= 5 or len(_second_meeting_slots_for_day(selected_day)) < 2:
                flash("Esse dia não possui mais duas opções de horário livres à tarde. Escolha outro dia.", "warning")
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

            if slot.date() != selected_day or slot.weekday() >= 5 or not (13 <= slot.hour <= 20):
                flash("Horário inválido para o dia selecionado. A 2ª reunião deve ser marcada em uma das opções da tarde.", "danger")
                return redirect(url_for("lead_second_meeting", lead_id=lead.id))

            if not _slot_is_free(slot):
                flash("Esse horário acabou de ser ocupado por outra reunião. Escolha outro horário disponível.", "warning")
                options = _second_meeting_slots_for_day(selected_day)[:2]
                return render_template(
                    "second_meeting.html",
                    lead=lead,
                    days=[],
                    selected_day=selected_day.isoformat(),
                    selected_day_label=_format_day(selected_day),
                    options=[(s.isoformat(), s.strftime("%H:%M")) for s in options],
                )

            utc_naive = slot.astimezone(UTC).replace(tzinfo=None)
            crm.db.session.add(crm.Task(
                lead_id=lead.id,
                owner_id=lead.owner_id,
                title=f"2ª reunião com {lead.name}",
                task_type="Reunião",
                due_at=utc_naive,
                status="Pendente",
                notes=f"2ª reunião comercial de 1 hora agendada para {_format_slot(slot)}.",
            ))
            lead.next_followup = utc_naive
            lead.stage = "2ª Reunião Agendada"
            crm.db.session.add(crm.AutomationLog(
                lead_id=lead.id,
                action="2ª reunião agendada",
                detail=f"Agendada para {_format_slot(slot)}. Horário validado contra 1ª e 2ª reuniões existentes.",
            ))
            crm.db.session.commit()
            flash("2ª reunião agendada com sucesso.", "success")
            return redirect(url_for("lead_detail", lead_id=lead.id))

    if selected_day:
        options = _second_meeting_slots_for_day(selected_day)[:2]
        return render_template(
            "second_meeting.html",
            lead=lead,
            days=[],
            selected_day=selected_day.isoformat(),
            selected_day_label=_format_day(selected_day),
            options=[(slot.isoformat(), slot.strftime("%H:%M")) for slot in options],
        )

    days = _second_meeting_days()
    return render_template(
        "second_meeting.html",
        lead=lead,
        days=[(day.isoformat(), _format_day(day)) for day in days],
        selected_day=None,
        selected_day_label=None,
        options=[],
    )


import final_qualification_patch  # noqa: F401,E402
import flow_resilience_patch  # noqa: F401,E402
import lead_management_patch  # noqa: F401,E402
import lead_assignment_patch  # noqa: F401,E402
import import_reactivation_patch  # noqa: F401,E402
import instagram_flow_fix_patch  # noqa: F401,E402
import meeting_scheduler_fix_patch  # noqa: F401,E402
import meeting_day_selection_patch  # noqa: F401,E402
import instagram_schedule_hotfix  # noqa: F401,E402
import meeting_report_patch  # noqa: F401,E402
import pipeline_stage_migration_patch  # noqa: F401,E402
import team_dashboard_patch  # noqa: F401,E402
import source_report_patch  # noqa: F401,E402
import dashboard_meeting_summary_patch  # noqa: F401,E402

# Garante que o agendamento automático da 1ª reunião use a mesma regra global:
# um horário ocupado por qualquer reunião (1ª ou 2ª) não pode ser oferecido.
try:
    import sitecustomize as _sc
    _sc._slot_is_free = _slot_is_free
except Exception:
    pass
