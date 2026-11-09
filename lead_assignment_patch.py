"""Distribuição comercial dos leads do CRM Cervejeiros.

- Novos leads alternam entre Beto Carvalho e Anderson Holanda.
- Beto permanece com perfil admin.
- Admin/manager pode atribuir leads manualmente a Beto, Anderson ou Julia.
"""
from flask import flash, redirect, request, url_for

import patched_app as p

crm = p.crm


def _commercial_assignees():
    """Retorna somente Beto Carvalho e Anderson Holanda, se ativos."""
    users = crm.User.query.filter(crm.User.active == True).order_by(crm.User.id).all()
    allowed = {"beto carvalho", "anderson holanda", "julia moi carvalho"}
    return [u for u in users if (u.name or "").strip().lower() in allowed]


def _leave_new_lead_unassigned(lead):
    """Novos leads ficam na fila, sem responsável automático."""
    return None


crm.assign_round_robin = _leave_new_lead_unassigned
p.assign_round_robin = _leave_new_lead_unassigned


def _visible_leads_with_unassigned():
    user = crm.current_user()
    if user and user.role == "seller":
        return crm.Lead.query.filter(
            crm.db.or_(
                crm.Lead.owner_id == user.id,
                crm.Lead.owner_id.is_(None),
            )
        )
    return crm.Lead.query


crm.visible_leads_query = _visible_leads_with_unassigned
p.visible_leads_query = _visible_leads_with_unassigned


@crm.app.route("/lead/<int:lead_id>/claim", methods=["POST"])
@crm.login_required
def lead_claim(lead_id):
    user = crm.current_user()
    if not user or user.role != "seller":
        flash("Somente vendedores podem assumir leads disponíveis.", "danger")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    lead = crm.Lead.query.filter_by(id=lead_id).first_or_404()
    if lead.owner_id == user.id:
        flash("Este lead já está com você.", "info")
        return redirect(url_for("lead_detail", lead_id=lead.id))
    if lead.owner_id is not None:
        flash("Outro vendedor já assumiu este lead.", "warning")
        return redirect(url_for("leads"))

    claimed = crm.Lead.query.filter_by(id=lead.id, owner_id=None).update(
        {crm.Lead.owner_id: user.id},
        synchronize_session=False,
    )
    if not claimed:
        crm.db.session.rollback()
        flash("Outro vendedor acabou de assumir este lead.", "warning")
        return redirect(url_for("leads"))

    crm.Task.query.filter_by(
        lead_id=lead.id, owner_id=None, status="Pendente"
    ).update({crm.Task.owner_id: user.id}, synchronize_session=False)
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="Lead assumido pelo vendedor",
        detail=f"Lead assumido por {user.name}.",
    ))
    crm.db.session.commit()
    flash(f"Lead assumido por {user.name}.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


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
        flash("Escolha Beto Carvalho, Anderson Holanda ou Julia Moi Carvalho.", "danger")
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


# Disponibiliza os responsáveis comerciais ativos para a tela de detalhe.
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
