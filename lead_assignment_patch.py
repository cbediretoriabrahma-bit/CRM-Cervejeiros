"""Distribuição comercial dos leads do CRM Cervejeiros.

- Novos leads são alternados entre Beto Carvalho e Anderson Holanda.
- Beto permanece com perfil admin.
- Admin/manager pode trocar manualmente o responsável por qualquer lead.
"""
from flask import flash, redirect, request, url_for

import patched_app as p

crm = p.crm


def _commercial_assignees():
    """Retorna somente Beto Carvalho e Anderson Holanda, se ativos."""
    users = crm.User.query.filter(crm.User.active == True).order_by(crm.User.id).all()
    allowed = {"beto carvalho", "anderson holanda"}
    return [u for u in users if (u.name or "").strip().lower() in allowed]


def _assign_round_robin_beto_anderson(lead):
    if lead.owner_id or crm.get_setting("auto_assign", "1") != "1":
        return

    assignees = _commercial_assignees()
    if not assignees:
        return

    last = int(crm.get_setting("last_assigned_user_id", "0") or 0)
    idx = 0
    for i, user in enumerate(assignees):
        if user.id == last:
            idx = (i + 1) % len(assignees)
            break

    selected = assignees[idx]
    lead.owner_id = selected.id
    crm.set_setting("last_assigned_user_id", selected.id)
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="Distribuição automática",
        detail=f"Lead atribuído a {selected.name}",
    ))


crm.assign_round_robin = _assign_round_robin_beto_anderson
p.assign_round_robin = _assign_round_robin_beto_anderson


@crm.app.route("/lead/<int:lead_id>/owner", methods=["POST"])
@crm.login_required
def lead_owner_change(lead_id):
    user = crm.current_user()
    if not user or user.role not in ["admin", "manager"]:
        flash("Apenas administrador ou gerente pode alterar o responsável.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()
    raw_owner_id = (request.form.get("owner_id") or "").strip()

    if not raw_owner_id:
        flash("Selecione um responsável.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    try:
        owner_id = int(raw_owner_id)
    except ValueError:
        flash("Responsável inválido.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    allowed = {u.id: u for u in _commercial_assignees()}
    selected = allowed.get(owner_id)
    if not selected:
        flash("Escolha Beto Carvalho ou Anderson Holanda.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    previous = lead.owner.name if lead.owner else "Sem responsável"
    lead.owner_id = selected.id

    # Atualiza também atividades pendentes para acompanhar o novo responsável.
    crm.Task.query.filter_by(lead_id=lead.id, status="Pendente").update(
        {crm.Task.owner_id: selected.id}, synchronize_session=False
    )

    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="Responsável alterado manualmente",
        detail=f"{previous} → {selected.name} por {user.name}",
    ))
    crm.db.session.commit()
    flash(f"Responsável alterado para {selected.name}.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


# Disponibiliza os dois responsáveis para a tela de detalhe.
_original_lead_detail = crm.app.view_functions.get("lead_detail")
if _original_lead_detail:
    def _lead_detail_with_assignees(*args, **kwargs):
        # A função original renderiza diretamente; o template consulta esta função
        # global através do context processor abaixo.
        return _original_lead_detail(*args, **kwargs)
    crm.app.view_functions["lead_detail"] = _lead_detail_with_assignees


@crm.app.context_processor
def _commercial_assignee_context():
    return {"commercial_assignees": _commercial_assignees()}
