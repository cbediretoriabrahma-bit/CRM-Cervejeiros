"""Relatórios e histórico de reuniões do CRM Cervejeiros.

Adiciona:
- lista de reuniões agendadas no Dashboard;
- acesso rápido ao lead e sua qualificação;
- relatório pós-reunião persistente, com múltiplos registros por cliente;
- próxima ação e data de retorno;
- opção de concluir a reunião ao salvar o relatório.
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


# Exponibiliza o model para outros módulos, se necessário.
crm.MeetingReport = MeetingReport
p.MeetingReport = MeetingReport


def _visible_meeting_query():
    q = crm.Task.query.filter(crm.Task.task_type == "Reunião")
    user = crm.current_user()
    if user and user.role == "seller":
        q = q.filter(crm.Task.owner_id == user.id)
    return q


def _dashboard_meetings():
    return (
        _visible_meeting_query()
        .filter(crm.Task.status == "Pendente")
        .order_by(crm.Task.due_at.asc())
        .limit(20)
        .all()
    )


def _lead_meetings(lead_id):
    return (
        crm.Task.query.filter_by(lead_id=lead_id, task_type="Reunião")
        .order_by(crm.Task.due_at.desc())
        .all()
    )


def _lead_meeting_reports(lead_id):
    return (
        MeetingReport.query.filter_by(lead_id=lead_id)
        .order_by(MeetingReport.created_at.desc())
        .all()
    )


def _br_datetime(value, include_year=True):
    if not value:
        return "-"
    # As reuniões automáticas são gravadas como UTC sem timezone.
    aware = value.replace(tzinfo=UTC).astimezone(TZ)
    return aware.strftime("%d/%m/%Y %H:%M" if include_year else "%d/%m %H:%M")


@crm.app.context_processor
def _meeting_report_context():
    return {
        "dashboard_meetings": _dashboard_meetings,
        "lead_meetings": _lead_meetings,
        "lead_meeting_reports": _lead_meeting_reports,
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

    if next_action:
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="Relatório de reunião",
            detail=f"Relatório salvo. Próxima ação: {next_action}.",
        ))
    else:
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="Relatório de reunião",
            detail="Relatório pós-reunião salvo no histórico do cliente.",
        ))

    crm.db.session.commit()
    flash("Relatório da reunião salvo no histórico do cliente.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))
