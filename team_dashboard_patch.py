"""Relatório de leads por responsável no Dashboard do CRM Cervejeiros.

Inclui todos os usuários ativos que possuem leads atribuídos, inclusive admin,
para que o painel mostre os leads atendidos por Beto e Anderson no mesmo lugar.
"""
import patched_app as p

crm = p.crm


def _team_lead_report():
    users = crm.User.query.filter(crm.User.active == True).order_by(crm.User.name).all()
    rows = []
    for user in users:
        leads = crm.Lead.query.filter_by(owner_id=user.id).all()
        if not leads:
            continue
        active = [l for l in leads if l.stage not in ["Fechado", "Perdido"]]
        hot = [l for l in active if l.temperature == "Quente" or (l.score or 0) >= 60]
        meetings = [l for l in active if l.stage in ["Reunião Agendada", "2ª Reunião Agendada"]]
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
            "meetings": len(meetings),
            "contracts": len(contracts),
            "closed": len(closed),
            "conv": conversion,
        })
    return rows


@crm.app.context_processor
def _team_dashboard_context():
    return {"team_lead_report": _team_lead_report}
