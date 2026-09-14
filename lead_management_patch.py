import re

from flask import flash, redirect, render_template, request, session, url_for

import patched_app as patched

crm = patched.crm
app = patched.app

ARCHIVE_TAG = "[ARCHIVED]=1"


def _is_archived(lead):
    return ARCHIVE_TAG in (lead.notes or "")


def _set_archived(lead, archived=True):
    notes = lead.notes or ""
    lines = [line for line in notes.splitlines() if not line.strip().startswith("[ARCHIVED]=")]
    if archived:
        lines.append(ARCHIVE_TAG)
    lead.notes = "\n".join(line for line in lines if line.strip()).strip()


def _all_visible_leads_query():
    user = crm.current_user()
    if user and user.role == "seller":
        return crm.Lead.query.filter_by(owner_id=user.id)
    return crm.Lead.query


def _active_visible_leads_query():
    # Exclui arquivados do dashboard, pipeline, relatórios e listas normais,
    # sem alterar nenhuma regra de qualificação ou resposta automática.
    return _all_visible_leads_query().filter(
        crm.db.or_(crm.Lead.notes.is_(None), ~crm.Lead.notes.contains(ARCHIVE_TAG))
    )


# A camada visual do CRM passa a enxergar somente leads ativos.
crm.visible_leads_query = _active_visible_leads_query
patched.crm.visible_leads_query = _active_visible_leads_query


def _find_active_lead_by_phone(phone):
    target = crm.normalize_phone(phone)
    if not target:
        return None
    for lead in crm.Lead.query.order_by(crm.Lead.id.desc()).all():
        if _is_archived(lead):
            continue
        if crm.normalize_phone(lead.phone) == target:
            return lead
    return None


# O webhook ignora um cadastro arquivado. Se a pessoa voltar a falar,
# ela entra novamente como atendimento ativo em vez de continuar um fluxo antigo.
patched._find_lead_by_phone = _find_active_lead_by_phone


@app.route("/lead/<int:lead_id>/archive", methods=["POST"])
@crm.login_required
def lead_archive(lead_id):
    lead = _all_visible_leads_query().filter_by(id=lead_id).first_or_404()
    if not _is_archived(lead):
        _set_archived(lead, True)
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="Lead arquivado",
            detail=f"Lead arquivado manualmente por {session.get('user_name', 'usuário do CRM')}.",
        ))
        crm.db.session.commit()
    flash("Lead arquivado. Ele saiu das listas e do pipeline, mas o histórico foi preservado.", "success")
    return redirect(url_for("leads"))


@app.route("/lead/<int:lead_id>/unarchive", methods=["POST"])
@crm.login_required
def lead_unarchive(lead_id):
    lead = _all_visible_leads_query().filter_by(id=lead_id).first_or_404()
    _set_archived(lead, False)
    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action="Lead restaurado",
        detail=f"Lead restaurado por {session.get('user_name', 'usuário do CRM')}.",
    ))
    crm.db.session.commit()
    flash("Lead restaurado para a base ativa.", "success")
    return redirect(url_for("lead_detail", lead_id=lead.id))


@app.route("/leads/archived")
@crm.login_required
def archived_leads():
    query = _all_visible_leads_query().filter(crm.Lead.notes.contains(ARCHIVE_TAG))
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(crm.db.or_(
            crm.Lead.name.ilike(like),
            crm.Lead.phone.ilike(like),
            crm.Lead.city.ilike(like),
            crm.Lead.email.ilike(like),
        ))
    return render_template(
        "archived_leads.html",
        leads=query.order_by(crm.Lead.updated_at.desc()).all(),
        q=q,
    )


@app.route("/lead/<int:lead_id>/delete", methods=["POST"])
@crm.login_required
@crm.admin_required
def lead_delete(lead_id):
    lead = _all_visible_leads_query().filter_by(id=lead_id).first_or_404()

    # Remove dependências explicitamente para evitar erro de chave estrangeira.
    crm.Interaction.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
    crm.Task.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
    crm.AutomationLog.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
    crm.db.session.delete(lead)
    crm.db.session.commit()

    flash("Lead excluído definitivamente.", "success")
    return redirect(url_for("archived_leads"))
