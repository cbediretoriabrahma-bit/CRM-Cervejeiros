"""Reagendamento de reuniões no CRM Cervejeiros."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import flash, redirect, request, url_for

import patched_app as p

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")


def _is_second_meeting(task):
    text = f"{task.title or ''} {task.notes or ''}".lower()
    return "2ª" in text or "2a" in text or "segunda" in text


def _local_dt(value):
    if not value:
        return None
    return value.replace(tzinfo=UTC).astimezone(TZ)


def _fmt(value):
    return value.strftime("%d/%m/%Y às %H:%M") if value else "-"


def _conflict(local_dt, current_task_id):
    new_start = local_dt.astimezone(UTC).replace(tzinfo=None)
    new_end = new_start + timedelta(hours=1)
    nearby = crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.id != current_task_id,
        crm.Task.due_at > new_start - timedelta(hours=1),
        crm.Task.due_at < new_end,
    ).all()
    for other in nearby:
        other_start = other.due_at
        other_end = other_start + timedelta(hours=1)
        if new_start < other_end and other_start < new_end:
            return True
    return False


@crm.app.route("/meeting/<int:task_id>/reschedule", methods=["POST"])
@crm.login_required
def meeting_reschedule(task_id):
    user = crm.current_user()
    q = crm.Task.query.filter_by(id=task_id, task_type="Reunião")
    if user and user.role == "seller":
        q = q.filter(crm.Task.owner_id == user.id)
    task = q.first_or_404()
    lead = crm.visible_leads_query().filter_by(id=task.lead_id).first_or_404()

    raw = (request.form.get("new_due_at") or "").strip()
    try:
        new_local = datetime.fromisoformat(raw)
    except Exception:
        flash("Informe uma nova data e horário válidos.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    if new_local.tzinfo is None:
        new_local = new_local.replace(tzinfo=TZ)
    else:
        new_local = new_local.astimezone(TZ)

    if new_local <= datetime.now(TZ):
        flash("O novo horário precisa estar no futuro.", "warning")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    if new_local.weekday() >= 5:
        flash("Escolha um dia útil, de segunda a sexta-feira.", "warning")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    if _is_second_meeting(task):
        if not (13 <= new_local.hour <= 20):
            flash("A 2ª reunião deve ser reagendada entre 13:00 e 20:00.", "warning")
            return redirect(url_for("lead_detail", lead_id=lead.id))
    elif not (9 <= new_local.hour <= 20):
        flash("A 1ª reunião deve ser reagendada entre 09:00 e 20:00.", "warning")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    if _conflict(new_local, task.id):
        flash("Esse horário já está ocupado por outra reunião. Escolha outro horário.", "warning")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    old_local = _local_dt(task.due_at)
    old_label = _fmt(old_local)
    new_label = _fmt(new_local)
    number = 2 if _is_second_meeting(task) else 1
    new_utc = new_local.astimezone(UTC).replace(tzinfo=None)

    task.due_at = new_utc
    task.notes = ((task.notes or "").rstrip() + f"\nReagendada de {old_label} para {new_label}.").strip()
    lead.next_followup = new_utc

    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action=f"{number}ª reunião reagendada",
        detail=f"Reagendada de {old_label} para {new_label}. Histórico anterior preservado.",
    ))
    crm.db.session.commit()
    flash(f"{number}ª reunião reagendada com sucesso para {new_label}.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))
