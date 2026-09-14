import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from flask import flash, redirect, render_template, request, url_for

# Importa o módulo completo que já contém o webhook e a automação do WhatsApp.
# O novo pipeline comercial é aplicado por cima, sem perder as integrações existentes.
import patched_app as patched

# Garante que o patch final com as perguntas, pontuação e pipeline mais recentes
# seja aplicado também quando o CRM inicia pelo gunicorn crm_entry:app.
# Antes, o fluxo novo dependia do carregamento automático de sitecustomize e o
# WhatsApp podia continuar respondendo com as perguntas antigas de patched_app.py.
import sitecustomize  # noqa: F401

# Padroniza a apresentação das respostas: pergunta em bloco, opções em linhas
# separadas e espaçamento adequado para leitura no WhatsApp/Instagram.
import reply_format_patch  # noqa: F401

# Usa automaticamente o vídeo hospedado na pasta /static do próprio CRM.
# No Render, RENDER_EXTERNAL_URL é fornecida ao serviço web. A variável
# QUALIFICATION_VIDEO_URL continua podendo sobrescrever esta URL manualmente.
if not os.getenv("QUALIFICATION_VIDEO_URL"):
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        os.environ["QUALIFICATION_VIDEO_URL"] = (
            f"{render_url}/static/qualificacao_cervejeiros_web.mp4"
        )

# Aplica por último o fluxo com vídeo e escolhas interativas.
import flow_media_patch  # noqa: F401

# Faz o Instagram enviar o mesmo vídeo de qualificação antes da terceira pergunta.
import instagram_video_patch  # noqa: F401

crm = patched.crm
app = patched.app

# Pipeline comercial oficial após a qualificação automática.
COMMERCIAL_PIPELINE = [
    "Novo Lead",
    "Em Qualificação",
    "Qualificado",
    "Lead Quente",
    "Prioridade / Reunião",
    "Reunião Agendada",
    "1ª Reunião Realizada",
    "2ª Reunião Agendada",
    "2ª Reunião Realizada",
    "Proposta Enviada",
    "Negociação",
    "Fechado",
    "Perdido",
]
crm.PIPELINE[:] = COMMERCIAL_PIPELINE

# Mantém etapas comerciais manuais depois que o lead chega à reunião.
def _commercial_auto_stage(lead, preserve=True):
    manual_stages = {
        "Prioridade / Reunião",
        "Reunião Agendada",
        "1ª Reunião Realizada",
        "2ª Reunião Agendada",
        "2ª Reunião Realizada",
        "Proposta Enviada",
        "Negociação",
        "Fechado",
        "Perdido",
    }
    if preserve and lead.stage in manual_stages:
        return lead.stage
    if lead.meeting_interest == "Sim":
        return "Prioridade / Reunião"
    if lead.score >= 80:
        return "Prioridade / Reunião"
    if lead.score >= 60:
        return "Lead Quente"
    if lead.score >= 40:
        return "Qualificado"
    if lead.score >= 20:
        return "Em Qualificação"
    return "Novo Lead"

crm.auto_stage = _commercial_auto_stage

TZ = ZoneInfo("America/Sao_Paulo")


def _meeting_hours():
    return [time(hour, 0) for hour in range(9, 20)]


def _slot_is_free(local_dt, owner_id):
    utc_naive = local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    start = utc_naive
    end = utc_naive + timedelta(hours=1)
    query = crm.Task.query.filter(
        crm.Task.task_type == "Reunião",
        crm.Task.status == "Pendente",
        crm.Task.due_at >= start,
        crm.Task.due_at < end,
    )
    if owner_id is None:
        query = query.filter(crm.Task.owner_id.is_(None))
    else:
        query = query.filter(crm.Task.owner_id == owner_id)
    return query.first() is None


def _second_meeting_options(lead):
    now = datetime.now(TZ)
    options = []
    for add_day in range(0, 15):
        day = (now + timedelta(days=add_day)).date()
        if day.weekday() >= 5:
            continue
        for hr in _meeting_hours():
            slot = datetime.combine(day, hr, tzinfo=TZ)
            if slot <= now + timedelta(hours=2):
                continue
            if _slot_is_free(slot, lead.owner_id):
                options.append(slot)
            if len(options) == 3:
                return options
    return options


def _format_slot(slot):
    weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    return f"{weekdays[slot.weekday()]}, {slot.strftime('%d/%m')} às {slot.strftime('%H:%M')}"


@app.route("/lead/<int:lead_id>/second-meeting", methods=["GET", "POST"])
@crm.login_required
def lead_second_meeting(lead_id):
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()

    if request.method == "POST":
        raw = (request.form.get("slot") or "").strip()
        try:
            slot = datetime.fromisoformat(raw)
        except Exception:
            flash("Horário inválido. Escolha uma das opções disponíveis.", "danger")
            return redirect(url_for("lead_second_meeting", lead_id=lead.id))

        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=TZ)
        else:
            slot = slot.astimezone(TZ)

        if not _slot_is_free(slot, lead.owner_id):
            flash("Esse horário acabou de ser ocupado. Escolha uma nova opção.", "danger")
            return redirect(url_for("lead_second_meeting", lead_id=lead.id))

        utc_naive = slot.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        crm.db.session.add(crm.Task(
            lead_id=lead.id,
            owner_id=lead.owner_id,
            title=f"2ª reunião com {lead.name}",
            task_type="Reunião",
            due_at=utc_naive,
            status="Pendente",
            notes=f"2ª reunião comercial de 1 hora agendada para {_format_slot(slot)}.",
        ))
        lead.next_followup = utc_naive
        lead.stage = "2ª Reunião Agendada"
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="2ª reunião agendada",
            detail=f"Agendada para {_format_slot(slot)} com o responsável do lead.",
        ))
        crm.db.session.commit()
        flash("2ª reunião agendada com sucesso.", "success")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    options = _second_meeting_options(lead)
    return render_template(
        "second_meeting.html",
        lead=lead,
        options=[(slot.isoformat(), _format_slot(slot)) for slot in options],
    )

# Carrega por último a versão final do fluxo de qualificação, apresentação e reunião.
import final_qualification_patch  # noqa: F401,E402

# Correções finais de robustez: aceita respostas repetidas válidas e interpreta
# corretamente os textos do convite de reunião.
import flow_resilience_patch  # noqa: F401,E402

# Gestão de leads arquivados/excluídos fica isolada do fluxo de respostas automáticas.
import lead_management_patch  # noqa: F401,E402

# Distribuição comercial: alterna novos leads entre Beto Carvalho e Anderson Holanda
# e permite ao administrador trocar manualmente o responsável do atendimento.
import lead_assignment_patch  # noqa: F401,E402

# Importação de contatos antigos por Excel/CSV para reativação comercial.
import import_reactivation_patch  # noqa: F401,E402

# Ajuste final do Direct: mantém o fluxo após a resposta de objetivo, reduz a
# apresentação para o limite do Instagram e melhora o destaque visual das mensagens.
import instagram_flow_fix_patch  # noqa: F401,E402

# Corrige definitivamente o agendamento: horários de 09h às 20h, remove horários
# já ocupados e mantém o fluxo ativo após uma tentativa inválida ou concorrente.
import meeting_scheduler_fix_patch  # noqa: F401,E402

# Fluxo final de agendamento em duas etapas: primeiro o lead escolhe o dia útil
# e depois recebe 2 horários pela manhã e 2 à tarde, todos realmente livres.
import meeting_day_selection_patch  # noqa: F401,E402

# Hotfix final: reconhece rótulos de horário do Instagram (ex.: Manhã • 10:00)
# e evita que faixas de investimento sejam interpretadas como número de telefone.
import instagram_schedule_hotfix  # noqa: F401,E402
