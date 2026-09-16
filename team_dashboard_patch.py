"""Relatório de leads por responsável no Dashboard do CRM Cervejeiros.

Inclui todos os usuários ativos que possuem leads atribuídos, inclusive admin,
para que o painel mostre os leads atendidos por toda a equipe, com 1ª e 2ª
reuniões separadas entre agendadas e realizadas.
"""
import patched_app as p

crm = p.crm


def _is_second_meeting(task):
    title = (task.title or "").lower()
    notes = (task.notes or "").lower()
    return "2ª" in title or "2a" in title or "segunda" in title or "2ª" in notes or "2a" in notes or "segunda" in notes


def _is_done(task):
    return (task.status or "").strip().lower().startswith("conclu")


def _team_lead_report():
    users = crm.User.query.filter(crm.User.active == True).order_by(crm.User.name).all()
    rows = []
    for user in users:
        leads = crm.Lead.query.filter_by(owner_id=user.id).all()
        if not leads:
            continue

        lead_ids = [l.id for l in leads]
        meetings = crm.Task.query.filter(
            crm.Task.lead_id.in_(lead_ids),
            crm.Task.task_type == "Reunião",
        ).all() if lead_ids else []

        first_meetings = [t for t in meetings if not _is_second_meeting(t)]
        second_meetings = [t for t in meetings if _is_second_meeting(t)]

        active = [l for l in leads if l.stage not in ["Fechado", "Perdido"]]
        hot = [l for l in active if l.temperature == "Quente" or (l.score or 0) >= 60]
        contracts = [l for l in active if l.stage == "Contrato Enviado"]
        closed = [l for l in leads if l.stage == "Fechado"]
        conversion = round(len(closed) / len(leads) * 100, 1) if leads else 0

        rows.append({
            "id": user.id,
            "name": user.name,
            "role": user.role,
            "leads": len(leads),
            "active": len(active),
            "hot": len(hot),
            "first_scheduled": sum((t.status or "") == "Pendente" for t in first_meetings),
            "first_done": sum(_is_done(t) for t in first_meetings),
            "second_scheduled": sum((t.status or "") == "Pendente" for t in second_meetings),
            "second_done": sum(_is_done(t) for t in second_meetings),
            "contracts": len(contracts),
            "closed": len(closed),
            "conv": conversion,
        })
    return rows


@crm.app.context_processor
def _team_dashboard_context():
    return {"team_lead_report": _team_lead_report}
