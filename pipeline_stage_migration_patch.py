"""Migra etapas antigas do pipeline para a versão simplificada.

- Prioridade / Reunião -> Lead Quente
- Proposta Enviada -> Contrato Enviado
- Negociação -> Contrato Enviado
"""
import patched_app as p

crm = p.crm


@crm.app.before_request
def _migrate_old_pipeline_stages_once():
    if crm.get_setting("pipeline_stage_migration_v2", "0") == "1":
        return

    changed = 0
    mappings = {
        "Prioridade / Reunião": "Lead Quente",
        "Proposta Enviada": "Contrato Enviado",
        "Negociação": "Contrato Enviado",
    }

    for old_stage, new_stage in mappings.items():
        rows = crm.Lead.query.filter_by(stage=old_stage).all()
        for lead in rows:
            lead.stage = new_stage
            changed += 1
            crm.db.session.add(crm.AutomationLog(
                lead_id=lead.id,
                action="Pipeline atualizado",
                detail=f"Etapa antiga '{old_stage}' alterada para '{new_stage}'.",
            ))

    crm.set_setting("pipeline_stage_migration_v2", "1")
    crm.db.session.commit()
