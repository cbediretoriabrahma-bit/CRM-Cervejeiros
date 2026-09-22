"""Migra etapas antigas e garante que todos os leads ativos apareçam no Pipeline.

O Pipeline filtra os registros por igualdade exata de ``Lead.stage``. Por isso,
uma etapa vazia, antiga, com espaços ou fora da lista atual faz o lead continuar
na tela de Leads, mas desaparecer do kanban. Além da migração histórica, este
patch repara automaticamente essas inconsistências sempre que o Pipeline é aberto.
"""
import re

from flask import request

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

LEGACY_STAGE_MAP = {
    "Prioridade / Reunião": "Lead Quente",
    "Proposta Enviada": "Contrato Enviado",
    "Negociação": "Contrato Enviado",
    "2ª Reunião Realizada": new_stage,
}
ARCHIVE_TAG = "[ARCHIVED]=1"

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

    for old, new in LEGACY_STAGE_MAP.items():
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


def _is_archived(lead):
    return ARCHIVE_TAG in (lead.notes or "")


def _has_meeting_slot(lead):
    match = re.search(
        r"^\[Q_MEETING_SLOT\]=(.*)$",
        lead.notes or "",
        flags=re.MULTILINE,
    )
    return bool(match and match.group(1).strip())


def _pending_meeting_stage(lead):
    meetings = crm.Task.query.filter_by(
        lead_id=lead.id,
        task_type="Reunião",
        status="Pendente",
    ).order_by(crm.Task.due_at.desc()).all()

    if not meetings:
        return None

    # Se houver uma 2ª reunião pendente, preserva a etapa comercial mais avançada.
    for meeting in meetings:
        text = f"{meeting.title or ''} {meeting.notes or ''}".lower()
        if "2ª" in text or "2a" in text or "segunda" in text:
            if "2ª Reunião Agendada" in crm.PIPELINE:
                return "2ª Reunião Agendada"

    if "Reunião Agendada" in crm.PIPELINE:
        return "Reunião Agendada"
    return None


def _repair_lead_stage(lead):
    current = (lead.stage or "").strip()

    # Corrige espaços acidentais sem alterar a classificação.
    if current in crm.PIPELINE:
        if lead.stage != current:
            lead.stage = current
            return True, f"Etapa normalizada para '{current}'."
        return False, None

    mapped = LEGACY_STAGE_MAP.get(current)
    if mapped and mapped in crm.PIPELINE:
        old = lead.stage
        lead.stage = mapped
        return True, f"Etapa antiga '{old}' corrigida para '{mapped}'."

    # Uma reunião pendente sempre deve deixar o lead visível em uma coluna de reunião.
    meeting_stage = _pending_meeting_stage(lead)
    if meeting_stage:
        old = lead.stage
        lead.stage = meeting_stage
        return True, f"Etapa '{old}' corrigida para '{meeting_stage}' por reunião pendente."

    if _has_meeting_slot(lead) and "Reunião Agendada" in crm.PIPELINE:
        old = lead.stage
        lead.stage = "Reunião Agendada"
        return True, f"Etapa '{old}' corrigida para 'Reunião Agendada' por horário confirmado."

    # Para etapa vazia ou desconhecida, reaplica a regra atual de qualificação.
    old = lead.stage
    crm.requalify(lead, preserve=False)
    repaired = (lead.stage or "").strip()

    # Proteção final: nenhum lead ativo pode ficar sem uma coluna válida.
    if repaired not in crm.PIPELINE:
        fallback = "Novo Lead" if "Novo Lead" in crm.PIPELINE else crm.PIPELINE[0]
        lead.stage = fallback
        repaired = fallback

    return True, f"Etapa inválida '{old}' recalculada para '{repaired}'."


def _repair_pipeline_visibility():
    changed = 0

    # Consulta a tabela diretamente para encontrar inclusive registros com stage inválido.
    for lead in crm.Lead.query.order_by(crm.Lead.id).all():
        if _is_archived(lead):
            continue

        was_changed, detail = _repair_lead_stage(lead)
        if not was_changed:
            continue

        changed += 1
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="Correção automática de visibilidade no Pipeline",
            detail=detail,
        ))

    if changed:
        crm.db.session.commit()
        crm.app.logger.warning(
            "Pipeline: %s lead(s) com etapa ausente/inválida foram corrigidos.",
            changed,
        )

    return changed


@crm.app.before_request
def _ensure_pipeline_visibility_before_render():
    # Executa somente quando o Pipeline é aberto para não pesar as demais telas.
    if request.endpoint != "pipeline":
        return

    try:
        _repair_pipeline_visibility()
    except Exception as exc:
        crm.db.session.rollback()
        crm.app.logger.exception(
            "Falha ao reparar automaticamente a visibilidade do Pipeline: %s",
            exc,
        )
