"""Corrige o relatório de performance por vendedor.

Inclui todos os usuários ativos cadastrados na equipe (admin, manager e seller),
mesmo quando ainda não possuem leads atribuídos, para que a tela de Relatórios
não esconda vendedores cadastrados.
"""

from flask import render_template, session

import patched_app as patched

crm = patched.crm
app = patched.app


def reports_all_team():
    leads = crm.visible_leads_query().all()
    by_stage = {s: sum(l.stage == s for l in leads) for s in crm.PIPELINE}
    by_source = {
        s: sum((l.source or "N/I") == s for l in leads)
        for s in sorted(set((l.source or "N/I") for l in leads))
    }
    state_counts = {}
    city_counts = {}
    for lead in leads:
        state = (lead.state or "Não informado").strip().upper() or "Não informado"
        city = (lead.city or "Não informada").strip() or "Não informada"
        state_counts[state] = state_counts.get(state, 0) + 1
        city_key = (city, state)
        city_counts[city_key] = city_counts.get(city_key, 0) + 1

    by_state = dict(sorted(state_counts.items(), key=lambda item: (-item[1], item[0])))
    by_city = {
        f"{city} / {state}": count
        for (city, state), count in sorted(city_counts.items(), key=lambda item: (-item[1], item[0][0].lower(), item[0][1]))
    }
    total_leads = len(leads)
    state_data = [
        {"state": state, "count": count, "percent": round(count / total_leads * 100, 1) if total_leads else 0}
        for state, count in by_state.items()
    ]
    city_data = [
        {"city_state": city_state, "count": count, "percent": round(count / total_leads * 100, 1) if total_leads else 0}
        for city_state, count in by_city.items()
    ]
    temps = {t: sum(l.temperature == t for l in leads) for t in ["Quente", "Morno", "Frio"]}

    seller_data = []
    if session.get("role") in ["admin", "manager"]:
        # Mostra toda a equipe ativa cadastrada. Isso evita esconder um vendedor
        # apenas porque seu perfil foi salvo como admin/manager ou ainda tem 0 leads.
        users = crm.User.query.filter(crm.User.active == True).order_by(crm.User.name).all()
        for u in users:
            ls = crm.Lead.query.filter_by(owner_id=u.id).all()
            closed = sum(x.stage == "Fechado" for x in ls)
            seller_data.append({
                "name": u.name,
                "leads": len(ls),
                "hot": sum(x.temperature == "Quente" for x in ls),
                "closed": closed,
                "value": sum(x.closed_value or 0 for x in ls),
                "conversion": round(closed / len(ls) * 100, 1) if ls else 0,
            })

    return render_template(
        "reports.html",
        leads=leads,
        by_stage=by_stage,
        by_source=by_source,
        by_state=by_state,
        by_city=by_city,
        state_data=state_data,
        city_data=city_data,
        total_leads=total_leads,
        temps=temps,
        seller_data=seller_data,
    )


if "reports" in app.view_functions:
    # Mantém os decorators de login da rota original e troca apenas a função final.
    original = app.view_functions["reports"]
    while hasattr(original, "__wrapped__"):
        original = original.__wrapped__
    app.view_functions["reports"] = crm.login_required(reports_all_team)
