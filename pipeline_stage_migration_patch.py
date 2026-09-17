"""Migra etapas antigas do pipeline para a versão simplificada.

Também substitui a etapa "2ª Reunião Realizada" por "Envio do Material de Apoio".
"""
import patched_app as p

crm = p.crm

# Ajusta a lista do pipeline depois que o crm_entry define as etapas.
old_stage = "2ª Reunião Realizada"
new_stage = "Envio do Material de Apoio"
if old_stage in crm.PIPELINE:
    crm.PIPELINE[:] = [new_stage if stage == old_stage else stage for stage in crm.PIPELINE]
elif new_stage not in crm.PIPELINE:
    try:
        idx = crm.PIPELINE.index("2ª Reunião Agendada") + 1
    except ValueError:
        idx = len(crm.PIPELINE)
    crm.PIPELINE.insert(idx, new_stage)

# Garante que a nova etapa seja preservada nas requalificações automáticas.
_previous_auto_stage = crm.auto_stage

def _auto_stage_with_material_support(lead, preserve=True):
    if preserve and lead.stage == new_stage:
        return new_stage
    return _previous_auto_stage(lead, preserve=preserve)

crm.auto_stage = _auto_stage_with_material_support


@crm.app.before_request
def _migrate_old_pipeline_stages_once():
    if crm.get_setting("pipeline_stage_migration_v3", "0") == "1":
        return

    mappings = {
        "Prioridade / Reunião": "Lead Quente",
        "Proposta Enviada": "Contrato Enviado",
        "Negociação": "Contrato Enviado",
        "2ª Reunião Realizada": new_stage,
    }

    for old, new in mappings.items():
        rows = crm.Lead.query.filter_by(stage=old).all()
        for lead in rows:
            lead.stage = new
            crm.db.session.add(crm.AutomationLog(
                lead_id=lead.id,
                action="Pipeline atualizado",
                detail=f"Etapa antiga '{old}' alterada para '{new}'.",
            ))

    crm.set_setting("pipeline_stage_migration_v3", "1")
    crm.db.session.commit()
