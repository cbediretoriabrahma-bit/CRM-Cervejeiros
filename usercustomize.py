"""Complemento de inicialização: reforça a apresentação comercial antes da reunião."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import flash, redirect, request, url_for

try:
    import patched_app as p
except Exception:
    p = None

if p is not None:
    crm = p.crm
    _reply_anterior = p._qualification_reply

    def _qualification_reply_com_prova_social(lead, channel):
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel=channel, direction="in"
        ).count()
        first = (lead.name or "Olá").split()[0]

        if inbound_count == 9:
            return (
                f"{first}, antes de avançarmos, quero te mostrar rapidamente por que o modelo Cervejeiros vem crescendo tanto. 🍻\n\n"
                "Hoje já contamos com mais de 158 geladeiras instaladas em condomínios e clubes, operadas tanto pela própria Cervejeiros quanto por nossos licenciados.\n\n"
                "Já temos operações e licenciados em São Paulo, interior de São Paulo, Rio de Janeiro, Minas Gerais, Amazonas e Goiás, mostrando que o modelo pode ser replicado em diferentes regiões e perfis de mercado.\n\n"
                "A operação foi desenvolvida para ser simples, tecnológica e escalável:\n\n"
                "✅ Sem necessidade de funcionário no ponto\n"
                "✅ Operação 24 horas\n"
                "✅ Gestão de vendas e acompanhamento pelo sistema\n"
                "✅ Suporte para implantação e operação\n"
                "✅ Baixo custo operacional\n"
                "✅ Possibilidade de expansão para novas geladeiras e novos pontos\n"
                "✅ Modelo já validado em condomínios e clubes\n\n"
                "Em operações com bom desempenho, o payback pode ocorrer a partir de aproximadamente 4 meses, variando conforme localização, volume de vendas e execução da operação.\n\n"
                "É um modelo indicado para quem busca uma operação prática, escalável e com potencial de boa rentabilidade, sem a complexidade de um negócio tradicional com funcionários no local.\n\n"
                "Gostaria de falar com um de nossos consultores para conhecer os planos, valores e entender qual formato faz mais sentido para você?"
            )

        return _reply_anterior(lead, channel)

    p._qualification_reply = _qualification_reply_com_prova_social
    p._reply_for_message = lambda lead, text: _qualification_reply_com_prova_social(lead, "WhatsApp")
    p._reply_for_instagram = lambda lead: _qualification_reply_com_prova_social(lead, "Instagram")

    def _delete_cold_lead_permanent(lead_id):
        lead = crm.db.session.get(crm.Lead, lead_id)
        if not lead:
            flash("Lead não encontrado.", "danger")
            return redirect(request.referrer or url_for("pipeline"))

        user = crm.current_user()
        if user and user.role == "seller" and lead.owner_id != user.id:
            flash("Você não tem permissão para excluir este lead.", "danger")
            return redirect(request.referrer or url_for("pipeline"))

        if (lead.temperature or "").strip().lower() != "frio":
            flash("A exclusão definitiva está disponível somente para leads frios.", "danger")
            return redirect(request.referrer or url_for("pipeline"))

        name = lead.name
        try:
            crm.Task.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
            crm.AutomationLog.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
            crm.Interaction.query.filter_by(lead_id=lead.id).delete(synchronize_session=False)
            crm.db.session.delete(lead)
            crm.db.session.commit()
            flash(f"Lead {name} excluído definitivamente.", "success")
        except Exception as exc:
            crm.db.session.rollback()
            crm.app.logger.warning("Falha ao excluir definitivamente lead %s: %s", lead_id, exc)
            flash("Não foi possível excluir o lead. Tente novamente.", "danger")

        return redirect(url_for("pipeline"))

    if "lead_delete_permanent" not in crm.app.view_functions:
        crm.app.add_url_rule(
            "/lead/<int:lead_id>/delete-permanent",
            endpoint="lead_delete_permanent",
            view_func=crm.login_required(_delete_cold_lead_permanent),
            methods=["POST"],
        )

    TZ = ZoneInfo("America/Sao_Paulo")
    UTC = ZoneInfo("UTC")
    QUICK_MEETING_STAGES = {"Novo Lead", "Em Qualificação", "Qualificado", "Lead Quente"}

    def _quick_meeting_conflict(local_dt):
        new_start = local_dt.astimezone(UTC).replace(tzinfo=None)
        new_end = new_start + timedelta(hours=1)
        return crm.Task.query.filter(
            crm.Task.task_type == "Reunião",
            crm.Task.status == "Pendente",
            crm.Task.due_at > new_start - timedelta(hours=1),
            crm.Task.due_at < new_end,
        ).order_by(crm.Task.due_at).first()

    def _schedule_first_meeting_from_pipeline(lead_id):
        lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()

        if lead.stage not in QUICK_MEETING_STAGES:
            flash("Esse lead já avançou no Pipeline. Use os comandos da etapa atual.", "warning")
            return redirect(request.referrer or url_for("pipeline"))

        raw = (request.form.get("meeting_at") or "").strip()
        try:
            local_dt = datetime.fromisoformat(raw)
        except Exception:
            flash("Informe uma data e horário válidos para a reunião.", "danger")
            return redirect(request.referrer or url_for("pipeline"))

        if local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=TZ)
        else:
            local_dt = local_dt.astimezone(TZ)

        if local_dt <= datetime.now(TZ):
            flash("A reunião precisa ser marcada para um horário futuro.", "warning")
            return redirect(request.referrer or url_for("pipeline"))

        if local_dt.weekday() >= 5:
            flash("A 1ª reunião deve ser agendada de segunda a sexta-feira.", "warning")
            return redirect(request.referrer or url_for("pipeline"))

        if not (9 <= local_dt.hour <= 20):
            flash("A 1ª reunião deve ser agendada entre 09:00 e 20:00.", "warning")
            return redirect(request.referrer or url_for("pipeline"))

        conflict = _quick_meeting_conflict(local_dt)
        if conflict:
            conflict_local = conflict.due_at.replace(tzinfo=UTC).astimezone(TZ)
            flash(
                f"Esse horário está ocupado por outra reunião em {conflict_local.strftime('%d/%m/%Y às %H:%M')}. Escolha outro horário.",
                "warning",
            )
            return redirect(request.referrer or url_for("pipeline"))

        utc_naive = local_dt.astimezone(UTC).replace(tzinfo=None)
        label = local_dt.strftime("%d/%m/%Y às %H:%M")

        crm.db.session.add(crm.Task(
            lead_id=lead.id,
            owner_id=lead.owner_id,
            title=f"1ª reunião com {lead.name}",
            task_type="Reunião",
            due_at=utc_naive,
            status="Pendente",
            notes=f"1ª reunião comercial de 1 hora agendada manualmente pelo Pipeline para {label}.",
        ))
        lead.next_followup = utc_naive
        lead.stage = "Reunião Agendada"
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action="1ª reunião agendada manualmente",
            detail=f"Agendada pelo Pipeline para {label}. Lead movido automaticamente para Reunião Agendada.",
        ))
        crm.db.session.commit()
        flash(f"Reunião agendada para {label}. O lead foi movido para Reunião Agendada.", "success")
        return redirect(url_for("pipeline"))

    if "lead_schedule_first_meeting" not in crm.app.view_functions:
        crm.app.add_url_rule(
            "/lead/<int:lead_id>/schedule-first-meeting",
            endpoint="lead_schedule_first_meeting",
            view_func=crm.login_required(_schedule_first_meeting_from_pipeline),
            methods=["POST"],
        )
