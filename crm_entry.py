import os
import re
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

CONTACT_STAGES = {"Novo Lead", "Em Qualificação", "Qualificado", "Lead Quente"}
CONTACT_TAG = "PIPELINE_CONTACTED"


def _lead_contacted(lead):
    notes = lead.notes or ""
    match = re.search(rf"^\[{CONTACT_TAG}\]=(.*)$", notes, flags=re.MULTILINE)
    return bool(match and match.group(1).strip() == "1")


def _set_lead_contacted(lead, contacted):
    notes = lead.notes or ""
    pattern = rf"^\[{CONTACT_TAG}\]=.*$"
    line = f"[{CONTACT_TAG}]={'1' if contacted else '0'}"
    if re.search(pattern, notes, flags=re.MULTILINE):
        notes = re.sub(pattern, line, notes, flags=re.MULTILINE)
    else:
        notes = (notes.rstrip() + ("\n" if notes.rstrip() else "") + line).strip()
    lead.notes = notes


@app.context_processor
def _pipeline_contact_context():
    return {"lead_contacted": _lead_contacted}


@app.route("/lead/<int:lead_id>/toggle-contacted", methods=["POST"])
@crm.login_required
def lead_toggle_contacted(lead_id):
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()
    if lead.stage not in CONTACT_STAGES:
        flash("O marcador de contato está disponível somente nas quatro primeiras etapas do Pipeline.", "warning")
        return redirect(request.referrer or url_for("pipeline"))

    new_value = not _lead_contacted(lead)
    _set_lead_contacted(lead, new_value)
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="Marcador de contato atualizado",
        detail="Lead marcado como contatado." if new_value else "Marcação de contato removida.",
    ))
    crm.db.session.commit()
    return redirect(request.referrer or url_for("pipeline"))


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
    """Para a 2ª reunião, oferece horários de 1 em 1 hora, das 11h às 17h."""
    now = datetime.now(TZ)
    slots = []
    for hour in range(11, 18):
        slot = datetime.combine(day, time(hour, 0), tzinfo=TZ)
        if slot <= now + timedelta(hours=2):
            continue
        if _slot_is_free(slot):
            slots.append(slot)
    return slots


def _second_meeting_days():
    """Mostra 15 dias úteis com pelo menos 1 horário livre entre 11h e 17h."""
    now = datetime.now(TZ)
    days = []
    for add_day in range(0, 90):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() >= 5:
            continue
        if len(_second_meeting_slots_for_day(day)) >= 1:
            days.append(day)
        if len(days) == 15:
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

            if selected_day.weekday() >= 5 or len(_second_meeting_slots_for_day(selected_day)) < 1:
                flash("Esse dia não possui mais horários livres entre 11:00 e 17:00. Escolha outro dia.", "warning")
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

            if slot.date() != selected_day or slot.weekday() >= 5 or not (11 <= slot.hour <= 17) or slot.minute != 0:
                flash("Horário inválido para o dia selecionado. A 2ª reunião deve ser marcada em um horário disponível entre 11:00 e 17:00.", "danger")
                return redirect(url_for("lead_second_meeting", lead_id=lead.id))

            if not _slot_is_free(slot):
                flash("Esse horário acabou de ser ocupado por outra reunião. Escolha outro horário disponível.", "warning")
                options = _second_meeting_slots_for_day(selected_day)
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
        options = _second_meeting_slots_for_day(selected_day)
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


@app.route("/lead/<int:lead_id>/delete-permanent", methods=["POST"])
@crm.login_required
def lead_delete_permanent(lead_id):
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()

    if (lead.temperature or "").strip().lower() != "frio":
        flash("A exclusão definitiva está disponível somente para leads frios.", "danger")
        return redirect(request.referrer or url_for("pipeline"))

    lead_name = lead.name
    try:
        crm.Task.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
        crm.AutomationLog.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
        crm.Interaction.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
        crm.db.session.delete(lead)
        crm.db.session.commit()
        flash(f"Lead {lead_name} excluído definitivamente.", "success")
    except Exception as exc:
        crm.db.session.rollback()
        crm.app.logger.exception("Falha ao excluir definitivamente lead %s: %s", lead_id, exc)
        flash("Não foi possível excluir o lead. Tente novamente.", "danger")

    return redirect(url_for("pipeline"))


def _quick_meeting_conflict(local_dt):
    """Retorna uma reunião pendente que se sobreponha ao novo intervalo de 1 hora."""
    new_start = local_dt.astimezone(UTC).replace(tzinfo=None)
    new_end = new_start + timedelta(hours=1)
    return crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at > new_start - timedelta(hours=1),
        crm.Task.due_at < new_end,
    ).order_by(crm.Task.due_at).first()


def _schedule_first_meeting_from_pipeline(lead_id):
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()

    if lead.stage not in CONTACT_STAGES:
        flash("Esse lead já avançou no Pipeline. Use os comandos da etapa atual.", "warning")
        return redirect(request.referrer or url_for("pipeline"))

    raw = (request.form.get("meeting_at") or "").strip()
    try:
        local_dt = datetime.fromisoformat(raw)
    except Exception:
        flash("Informe uma data e horário válidos para a reunião.", "danger")
        return redirect(request.referrer or url_for("pipeline"))

    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=TZ)
    else:
        local_dt = local_dt.astimezone(TZ)

    if local_dt <= datetime.now(TZ):
        flash("A reunião precisa ser marcada para um horário futuro.", "warning")
        return redirect(request.referrer or url_for("pipeline"))

    if local_dt.weekday() >= 5:
        flash("A 1ª reunião deve ser agendada de segunda a sexta-feira.", "warning")
        return redirect(request.referrer or url_for("pipeline"))

    if not (9 <= local_dt.hour <= 20):
        flash("A 1ª reunião deve ser agendada entre 09:00 e 20:00.", "warning")
        return redirect(request.referrer or url_for("pipeline"))

    conflict = _quick_meeting_conflict(local_dt)
    if conflict:
        conflict_local = conflict.due_at.replace(tzinfo=UTC).astimezone(TZ)
        flash(
            f"Esse horário está ocupado por outra reunião em {conflict_local.strftime('%d/%m/%Y às %H:%M')}. Escolha outro horário.",
            "warning",
        )
        return redirect(request.referrer or url_for("pipeline"))

    utc_naive = local_dt.astimezone(UTC).replace(tzinfo=None)
    label = local_dt.strftime("%d/%m/%Y às %H:%M")

    try:
        crm.db.session.add(crm.Task(
            lead_id=lead.id,
            owner_id=lead.owner_id,
            title=f"1ª reunião com {lead.name}",
            task_type="Reunião",
            due_at=utc_naive,
            status="Pendente",
            notes=f"1ª reunião comercial de 1 hora agendada manualmente pelo Pipeline para {label}.",
        ))
        lead.next_followup = utc_naive
        lead.stage = "Reunião Agendada"
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="1ª reunião agendada manualmente",
            detail=f"Agendada pelo Pipeline para {label}. Lead movido automaticamente para Reunião Agendada.",
        ))
        crm.db.session.commit()
    except Exception as exc:
        crm.db.session.rollback()
        crm.app.logger.exception("Falha ao agendar 1ª reunião pelo Pipeline para lead %s: %s", lead_id, exc)
        flash("Não foi possível agendar a reunião. Tente novamente.", "danger")
        return redirect(request.referrer or url_for("pipeline"))

    flash(f"Reunião agendada para {label}. O lead foi movido para Reunião Agendada.", "success")
    return redirect(url_for("pipeline"))


# O endpoint precisa existir no módulo principal porque o template do Pipeline usa url_for.
# O guard evita conflito caso algum patch legado já tenha registrado a mesma rota.
if "lead_schedule_first_meeting" not in app.view_functions:
    app.add_url_rule(
        "/lead/<int:lead_id>/schedule-first-meeting",
        endpoint="lead_schedule_first_meeting",
        view_func=crm.login_required(_schedule_first_meeting_from_pipeline),
        methods=["POST"],
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
import meeting_reschedule_patch  # noqa: F401,E402
import pipeline_stage_migration_patch  # noqa: F401,E402
import team_dashboard_patch  # noqa: F401,E402
import source_report_patch  # noqa: F401,E402
import dashboard_meeting_summary_patch  # noqa: F401,E402
import reports_team_patch  # noqa: F401,E402
import contact_outreach_patch  # noqa: F401,E402
import meeting_fields_position_patch  # noqa: F401,E402

# Garante que o agendamento automático da 1ª reunião use a mesma regra global:
# um horário ocupado por qualquer reunião (1ª ou 2ª) não pode ser oferecido.
try:
    import sitecustomize as _sc
    _sc._slot_is_free = _slot_is_free
except Exception:
    pass
