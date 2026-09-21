"""Reagendamento de reuniões no CRM Cervejeiros.

Garante que o comando "Reagendar a reunião" apareça em todos os cards da
coluna Reunião Agendada, inclusive quando o horário já venceu ou quando um lead
antigo ficou na coluna sem uma Task de reunião associada.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import flash, redirect, request, url_for

import patched_app as p

crm = p.crm
TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

# IDs virtuais são usados apenas na interface quando o lead está em
# "Reunião Agendada" mas, por dados antigos/migração, não possui uma Task.
VIRTUAL_TASK_OFFSET = 2_000_000_000


def _is_second_meeting(task):
    text = f"{getattr(task, 'title', '') or ''} {getattr(task, 'notes', '') or ''}".lower()
    return "2ª" in text or "2a" in text or "segunda" in text


def _local_dt(value):
    if not value:
        return None
    return value.replace(tzinfo=UTC).astimezone(TZ)


def _fmt(value):
    return value.strftime("%d/%m/%Y às %H:%M") if value else "-"


def _conflict(local_dt, current_task_id=None):
    new_start = local_dt.astimezone(UTC).replace(tzinfo=None)
    new_end = new_start + timedelta(hours=1)
    query = crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at > new_start - timedelta(hours=1),
        crm.Task.due_at < new_end,
    )
    if current_task_id is not None:
        query = query.filter(crm.Task.id != current_task_id)

    nearby = query.all()
    for other in nearby:
        other_start = other.due_at
        other_end = other_start + timedelta(hours=1)
        if new_start < other_end and other_start < new_end:
            return other
    return None


def _conflict_message(conflict_task, requested_local):
    conflict_local = _local_dt(conflict_task.due_at)
    conflict_lead = crm.db.session.get(crm.Lead, conflict_task.lead_id) if conflict_task.lead_id else None
    conflict_name = conflict_lead.name if conflict_lead else "outro lead"
    requested_label = _fmt(requested_local)
    occupied_label = _fmt(conflict_local)
    return (
        f"Reagendamento não realizado. O horário solicitado ({requested_label}) está indisponível. "
        f"Já existe uma reunião com {conflict_name} marcada para {occupied_label}. "
        "Escolha outro horário disponível."
    )


def _return_after(lead):
    referrer = request.referrer or ""
    if "/pipeline" in referrer:
        return redirect(url_for("pipeline"))
    return redirect(url_for("lead_detail", lead_id=lead.id))


def _parse_new_local(lead):
    raw = (request.form.get("new_due_at") or "").strip()
    try:
        new_local = datetime.fromisoformat(raw)
    except Exception:
        flash("Informe uma nova data e horário válidos.", "danger")
        return None

    if new_local.tzinfo is None:
        new_local = new_local.replace(tzinfo=TZ)
    else:
        new_local = new_local.astimezone(TZ)

    if new_local <= datetime.now(TZ):
        flash("O novo horário precisa estar no futuro.", "warning")
        return None

    if new_local.weekday() >= 5:
        flash("Escolha um dia útil, de segunda a sexta-feira.", "warning")
        return None

    # Regra atual do CRM: horários de 1 em 1 hora, das 11h às 17h.
    if not (11 <= new_local.hour <= 17) or new_local.minute != 0:
        flash("Escolha um horário disponível de 11:00 a 17:00, de 1 em 1 hora.", "warning")
        return None

    return new_local


def _real_first_meetings(lead_id):
    tasks = (
        crm.Task.query.filter_by(lead_id=lead_id, task_type="Reunião")
        .order_by(crm.Task.due_at.desc(), crm.Task.id.desc())
        .all()
    )
    return [task for task in tasks if not _is_second_meeting(task)]


def _lead_first_meetings_with_reschedule(lead_id):
    """Garante uma opção de reagendamento para todo lead em Reunião Agendada.

    Reuniões pendentes — inclusive atrasadas — ficam primeiro na lista. Se só
    existirem reuniões antigas/concluídas, uma entrada virtual é colocada antes
    delas para que o botão crie um novo agendamento sem apagar o histórico.
    """
    meetings = _real_first_meetings(lead_id)
    lead = crm.db.session.get(crm.Lead, lead_id)

    if not lead or lead.stage != "Reunião Agendada":
        return meetings

    pending = [
        task for task in meetings
        if (task.status or "").strip().lower() == "pendente"
    ]
    if pending:
        historical = [task for task in meetings if task not in pending]
        return pending + historical

    virtual = SimpleNamespace(
        id=VIRTUAL_TASK_OFFSET + lead.id,
        lead_id=lead.id,
        owner_id=lead.owner_id,
        title=f"1ª reunião com {lead.name}",
        task_type="Reunião",
        due_at=None,
        status="Pendente",
        notes="",
        lead=lead,
    )
    return [virtual] + meetings


@crm.app.context_processor
def _reschedule_pipeline_context():
    # meeting_report_patch registra lead_first_meetings antes deste arquivo.
    # Como este patch é carregado depois, esta versão substitui a função no
    # contexto do Jinja e garante o botão em todos os cards da etapa.
    return {"lead_first_meetings": _lead_first_meetings_with_reschedule}


def _create_missing_first_meeting(lead, new_local):
    conflict_task = _conflict(new_local)
    if conflict_task:
        flash(_conflict_message(conflict_task, new_local), "warning")
        return None

    new_label = _fmt(new_local)
    new_utc = new_local.astimezone(UTC).replace(tzinfo=None)
    task = crm.Task(
        lead_id=lead.id,
        owner_id=lead.owner_id,
        title=f"1ª reunião com {lead.name}",
        task_type="Reunião",
        due_at=new_utc,
        status="Pendente",
        notes=(
            f"1ª reunião registrada pelo comando Reagendar a reunião para {new_label}. "
            "O lead estava em Reunião Agendada sem uma tarefa de reunião associada."
        ),
    )
    crm.db.session.add(task)
    lead.next_followup = new_utc
    lead.stage = "Reunião Agendada"
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="1ª reunião reagendada",
        detail=(
            f"Novo agendamento criado para {new_label}, pois o lead estava em Reunião Agendada "
            "sem uma tarefa de reunião associada."
        ),
    ))
    crm.db.session.commit()
    flash(f"1ª reunião reagendada com sucesso para {new_label}.", "success")
    return task


@crm.app.route("/meeting/<int:task_id>/reschedule", methods=["POST"])
@crm.login_required
def meeting_reschedule(task_id):
    # Card de um lead antigo/migrado sem Task real: o ID virtual carrega o lead_id.
    if task_id >= VIRTUAL_TASK_OFFSET:
        lead_id = task_id - VIRTUAL_TASK_OFFSET
        lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()

        if lead.stage != "Reunião Agendada":
            flash("O lead não está mais na etapa Reunião Agendada.", "warning")
            return _return_after(lead)

        # Se outra requisição já criou uma reunião real, usa essa reunião em vez
        # de criar duplicada.
        pending_real = [
            task for task in _real_first_meetings(lead.id)
            if (task.status or "").strip().lower() == "pendente"
        ]
        if pending_real:
            task = pending_real[0]
        else:
            new_local = _parse_new_local(lead)
            if new_local is None:
                return _return_after(lead)
            created = _create_missing_first_meeting(lead, new_local)
            return _return_after(lead) if created else _return_after(lead)
    else:
        user = crm.current_user()
        q = crm.Task.query.filter_by(id=task_id, task_type="Reunião")
        if user and user.role == "seller":
            q = q.filter(crm.Task.owner_id == user.id)
        task = q.first_or_404()
        lead = crm.visible_leads_query().filter_by(id=task.lead_id).first_or_404()

    new_local = _parse_new_local(lead)
    if new_local is None:
        return _return_after(lead)

    conflict_task = _conflict(new_local, task.id)
    if conflict_task:
        flash(_conflict_message(conflict_task, new_local), "warning")
        return _return_after(lead)

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
    return _return_after(lead)
