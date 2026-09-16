"""Relatórios e histórico de reuniões do CRM Cervejeiros.

Adiciona:
- listas separadas de 1ª e 2ª reunião no Dashboard;
- prioridade/aviso conforme proximidade da reunião;
- acesso rápido ao lead e sua qualificação;
- relatórios separados para 1ª e 2ª reunião;
- próxima ação e data de retorno;
- opção de concluir a reunião ao salvar o relatório;
- atualização automática da etapa quando a reunião é concluída pelo relatório.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import flash, redirect, request, url_for

import patched_app as p

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")


class MeetingReport(crm.db.Model):
    __tablename__ = "meeting_report"

    id = crm.db.Column(crm.db.Integer, primary_key=True)
    lead_id = crm.db.Column(crm.db.Integer, crm.db.ForeignKey("lead.id"), nullable=False, index=True)
    task_id = crm.db.Column(crm.db.Integer, crm.db.ForeignKey("task.id"), nullable=True, index=True)
    user_id = crm.db.Column(crm.db.Integer, crm.db.ForeignKey("user.id"), nullable=True)
    report_text = crm.db.Column(crm.db.Text, nullable=False)
    next_action = crm.db.Column(crm.db.String(120))
    next_followup_at = crm.db.Column(crm.db.DateTime)
    created_at = crm.db.Column(crm.db.DateTime, default=datetime.utcnow, nullable=False)

    lead = crm.db.relationship("Lead")
    task = crm.db.relationship("Task")
    user = crm.db.relationship("User")


crm.MeetingReport = MeetingReport
p.MeetingReport = MeetingReport


def _visible_meeting_query():
    q = crm.Task.query.filter(crm.Task.task_type == "Reunião")
    user = crm.current_user()
    if user and user.role == "seller":
        q = q.filter(crm.Task.owner_id == user.id)
    return q


def _is_second_meeting(task):
    if not task:
        return False
    title = (task.title or "").lower()
    notes = (task.notes or "").lower()
    return "2ª" in title or "2a" in title or "segunda" in title or "2ª" in notes or "2a" in notes or "segunda" in notes


def _meeting_number(task):
    return 2 if _is_second_meeting(task) else 1


def _dashboard_meetings():
    return (
        _visible_meeting_query()
        .filter(crm.Task.status == "Pendente")
        .order_by(crm.Task.due_at.asc())
        .limit(30)
        .all()
    )


def _dashboard_first_meetings():
    return [t for t in _dashboard_meetings() if not _is_second_meeting(t)]


def _dashboard_second_meetings():
    return [t for t in _dashboard_meetings() if _is_second_meeting(t)]


def _local_dt(value):
    if not value:
        return None
    return value.replace(tzinfo=UTC).astimezone(TZ)


def _meeting_alert(task):
    local = _local_dt(task.due_at)
    if not local:
        return {"label": "SEM DATA", "level": "normal"}

    now = datetime.now(TZ)
    seconds = (local - now).total_seconds()
    today = now.date()

    if seconds < 0:
        return {"label": "⚠️ ATRASADA", "level": "urgent"}
    if local.date() == today:
        if seconds <= 2 * 3600:
            return {"label": "🚨 EM BREVE", "level": "urgent"}
        return {"label": "🔴 HOJE", "level": "high"}
    if (local.date() - today).days == 1:
        return {"label": "🟠 AMANHÃ", "level": "medium"}
    if seconds <= 72 * 3600:
        return {"label": "🟡 PRÓXIMA", "level": "medium"}
    return {"label": "🟢 AGENDADA", "level": "normal"}


def _lead_meetings(lead_id):
    return (
        crm.Task.query.filter_by(lead_id=lead_id, task_type="Reunião")
        .order_by(crm.Task.due_at.desc())
        .all()
    )


def _lead_first_meetings(lead_id):
    return [t for t in _lead_meetings(lead_id) if not _is_second_meeting(t)]


def _lead_second_meetings(lead_id):
    return [t for t in _lead_meetings(lead_id) if _is_second_meeting(t)]


def _lead_meeting_reports(lead_id):
    return (
        MeetingReport.query.filter_by(lead_id=lead_id)
        .order_by(MeetingReport.created_at.desc())
        .all()
    )


def _lead_first_meeting_reports(lead_id):
    reports = _lead_meeting_reports(lead_id)
    return [r for r in reports if not r.task or not _is_second_meeting(r.task)]


def _lead_second_meeting_reports(lead_id):
    reports = _lead_meeting_reports(lead_id)
    return [r for r in reports if r.task and _is_second_meeting(r.task)]


def _meeting_status(task):
    if not task:
        return "Sem reunião"
    status = (task.status or "").strip().lower()
    if status.startswith("conclu"):
        return "✅ Realizada"
    if status == "pendente":
        return "📅 Agendada"
    return task.status or "-"


def _br_datetime(value, include_year=True):
    if not value:
        return "-"
    aware = _local_dt(value)
    return aware.strftime("%d/%m/%Y %H:%M" if include_year else "%d/%m %H:%M")


@crm.app.context_processor
def _meeting_report_context():
    return {
        "dashboard_meetings": _dashboard_meetings,
        "dashboard_first_meetings": _dashboard_first_meetings,
        "dashboard_second_meetings": _dashboard_second_meetings,
        "meeting_alert": _meeting_alert,
        "meeting_number": _meeting_number,
        "meeting_status": _meeting_status,
        "lead_meetings": _lead_meetings,
        "lead_first_meetings": _lead_first_meetings,
        "lead_second_meetings": _lead_second_meetings,
        "lead_meeting_reports": _lead_meeting_reports,
        "lead_first_meeting_reports": _lead_first_meeting_reports,
        "lead_second_meeting_reports": _lead_second_meeting_reports,
        "br_datetime": _br_datetime,
    }


@crm.app.route("/lead/<int:lead_id>/meeting-report", methods=["POST"])
@crm.login_required
def lead_meeting_report(lead_id):
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()
    report_text = (request.form.get("report_text") or "").strip()
    next_action = (request.form.get("next_action") or "").strip()
    task_id_raw = (request.form.get("task_id") or "").strip()
    next_followup_raw = (request.form.get("next_followup_at") or "").strip()

    if not report_text:
        flash("Descreva o que foi conversado na reunião antes de salvar.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    task = None
    task_id = None
    if task_id_raw:
        try:
            task_id = int(task_id_raw)
            task = crm.Task.query.filter_by(id=task_id, lead_id=lead.id, task_type="Reunião").first()
            if not task:
                task_id = None
        except ValueError:
            task_id = None

    next_followup_at = None
    if next_followup_raw:
        try:
            local_dt = datetime.fromisoformat(next_followup_raw)
            if local_dt.tzinfo is None:
                local_dt = local_dt.replace(tzinfo=TZ)
            next_followup_at = local_dt.astimezone(UTC).replace(tzinfo=None)
            lead.next_followup = next_followup_at
        except Exception:
            flash("A data do próximo contato não foi reconhecida; o relatório foi salvo sem essa data.", "warning")

    report = MeetingReport(
        lead_id=lead.id,
        task_id=task_id,
        user_id=crm.current_user().id if crm.current_user() else None,
        report_text=report_text,
        next_action=next_action,
        next_followup_at=next_followup_at,
    )
    crm.db.session.add(report)

    if task and request.form.get("mark_done") == "1":
        task.status = "Concluída"
        if _is_second_meeting(task):
            if lead.stage == "2ª Reunião Agendada":
                lead.stage = "2ª Reunião Realizada"
        else:
            if lead.stage == "Reunião Agendada":
                lead.stage = "1ª Reunião Realizada"

    number = _meeting_number(task) if task else 1
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action=f"Relatório da {number}ª reunião",
        detail=(f"Relatório salvo. Próxima ação: {next_action}." if next_action else f"Resumo da {number}ª reunião salvo no histórico do cliente."),
    ))

    crm.db.session.commit()
    flash(f"Resumo da {number}ª reunião salvo no histórico do cliente.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))
