"""Fluxo final de qualificação do CRM Cervejeiros.

Remove as perguntas de potencial de prospecção e quantidade/modelo de geladeiras,
mantém o vídeo após cidade/estado, atualiza a apresentação comercial e ajusta
pontuação/pipeline para o novo questionário.
"""
from datetime import datetime

import flow_media_patch as fm
import patched_app as p
import sitecustomize as sc

crm = p.crm


def _score_final_v2(lead):
    """Score de 0 a 100 usando apenas as perguntas que permanecem no fluxo."""
    score = 0

    if lead.city and lead.state:
        score += 5

    access = sc._tag_value(lead, "Q_ACCESS")
    score += {
        "locais_em_vista": 25,
        "alguns_contatos": 15,
        "vai_prospectar": 5,
    }.get(access, 0)

    investment = lead.investment or 0
    if investment >= 45000:
        score += 30
    elif investment >= 30000:
        score += 22
    elif investment >= 18900:
        score += 15

    if lead.timeframe == "Imediatamente":
        score += 20
    elif lead.timeframe == "Em até 30 dias":
        score += 14
    elif lead.timeframe == "Em até 60 dias":
        score += 7

    objective = sc._tag_value(lead, "Q_OBJECTIVE")
    score += {
        "expandir": 10,
        "avaliar": 6,
        "renda_complementar": 3,
    }.get(objective, 0)

    if lead.meeting_interest == "Sim":
        score += 10

    return min(score, 100)


def _temperature_final_v2(score):
    if score >= 70:
        return "Quente"
    if score >= 35:
        return "Morno"
    return "Frio"


def _auto_stage_final_v2(lead, preserve=True):
    manual_stages = {
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
    if sc._tag_value(lead, "Q_MEETING_SLOT"):
        return "Reunião Agendada"
    if lead.meeting_interest == "Sim" or lead.score >= 80:
        return "Prioridade / Reunião"
    if lead.score >= 60:
        return "Lead Quente"
    if lead.score >= 35:
        return "Qualificado"
    if lead.score >= 15:
        return "Em Qualificação"
    return "Novo Lead"


crm.score_lead = _score_final_v2
crm.temperature = _temperature_final_v2
crm.auto_stage = _auto_stage_final_v2
p._score_lead = _score_final_v2
p._temperature = _temperature_final_v2
p._auto_stage = _auto_stage_final_v2


def _qualification_reply_final_v2(lead, channel):
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()
    first = (lead.name or "Olá").split()[0]

    if inbound_count <= 1:
        return (
            "Bem-vindo ao CERVEJEIROS by WOC Group! 🍻\n\n"
            "Você está iniciando seu atendimento para conhecer nosso sistema de geladeiras de autoatendimento de chopp "
            "para condomínios, clubes e locais de grande circulação.\n\n"
            "Nosso modelo foi desenvolvido para oferecer uma operação prática, tecnológica e escalável.\n\n"
            "Para começarmos, em qual cidade você pretende operar?"
        )

    if inbound_count == 2:
        return f"Perfeito, {first}! Em qual estado fica essa cidade?"

    if inbound_count == 3:
        # O webhook envia o vídeo imediatamente antes desta mensagem.
        # O início do texto também é usado pelo patch do Instagram para disparar o vídeo.
        return fm._buttons_marker(
            "Agora vamos entender um pouco melhor o seu perfil.\n\nVocê já possui contato ou acesso a condomínios, clubes ou locais de grande circulação?",
            [
                {"id": "1", "title": "Locais em vista"},
                {"id": "2", "title": "Alguns contatos"},
                {"id": "3", "title": "Vou prospectar"},
            ],
        )

    if inbound_count == 4:
        return fm._buttons_marker(
            "Qual faixa de investimento inicial você pretende realizar?",
            [
                {"id": "1", "title": "R$18.900-29.999"},
                {"id": "2", "title": "R$30.000-44.999"},
                {"id": "3", "title": "R$45.000-55.000"},
            ],
        )

    if inbound_count == 5:
        return fm._list_marker(
            "Em quanto tempo você pretende iniciar sua operação?",
            "Escolher prazo",
            [
                {"id": "1", "title": "Imediatamente"},
                {"id": "2", "title": "Em até 30 dias"},
                {"id": "3", "title": "Em até 60 dias"},
                {"id": "4", "title": "Acima de 60 dias"},
            ],
        )

    if inbound_count == 6:
        return fm._buttons_marker(
            "Qual é o seu principal objetivo ao entrar para o modelo Cervejeiros?",
            [
                {"id": "1", "title": "Construir e expandir"},
                {"id": "2", "title": "Começar e crescer"},
                {"id": "3", "title": "Nova fonte de renda"},
            ],
        )

    if inbound_count == 7:
        return fm._buttons_marker(
            (
                f"Perfeito, {first}! 🍻 Agora que conhecemos um pouco melhor o seu perfil, queremos apresentar a CERVEJEIROS by WOC Group.\n\n"
                "A Cervejeiros atua com geladeiras de autoatendimento de chopp para condomínios, clubes e locais de grande circulação, "
                "em um modelo pensado para ser prático, tecnológico e escalável.\n\n"
                "Hoje já possuímos licenciados em vários estados do Brasil:\n"
                "📍 São Paulo\n"
                "📍 Minas Gerais\n"
                "📍 Goiás\n"
                "📍 Rio de Janeiro\n"
                "📍 Amazonas\n\n"
                "O licenciado conta com sistema de autoatendimento 24 horas, tecnologia de pagamento, dashboard para acompanhamento das vendas, "
                "controle da operação, suporte de implantação, treinamento, materiais comerciais e possibilidade de expansão para novos pontos.\n\n"
                "O modelo não exige funcionário no ponto e foi estruturado para permitir crescimento gradual em condomínios, clubes e outros locais de grande circulação.\n\n"
                "Gostaria de conversar com um de nossos consultores para conhecer o projeto completo, os planos, valores e as oportunidades disponíveis para sua região?"
            ),
            [
                {"id": "1", "title": "Quero agendar"},
                {"id": "2", "title": "Entender melhor"},
                {"id": "3", "title": "Só informações"},
            ],
        )

    if inbound_count == 8:
        if lead.meeting_interest == "Sim":
            options = sc._meeting_options(lead, refresh=True)
            if len(options) >= 3:
                crm.db.session.commit()
                return fm._buttons_marker(
                    "Excelente! 🍻 Escolha um dos horários disponíveis para conversar com nosso consultor. Cada reunião dura 1 hora:",
                    [
                        {"id": "1", "title": sc._format_slot(options[0])[:20]},
                        {"id": "2", "title": sc._format_slot(options[1])[:20]},
                        {"id": "3", "title": sc._format_slot(options[2])[:20]},
                    ],
                )
            return "Excelente! 🍻 Nosso consultor vai entrar em contato para combinar o melhor horário para sua reunião."
        if lead.meeting_interest == "Talvez":
            return (
                "Sem problema. 🍻 Vamos manter seu perfil em acompanhamento e podemos continuar enviando informações "
                "para você entender melhor o modelo antes de avançar para uma reunião."
            )
        return "Tudo certo. 🍻 Seu contato continuará cadastrado e estaremos à disposição quando quiser avançar."

    if inbound_count == 9 and lead.meeting_interest == "Sim":
        selected = sc._tag_value(lead, "Q_MEETING_SLOT")
        if selected:
            try:
                slot = datetime.fromisoformat(selected)
                return (
                    f"✅ Reunião confirmada para {sc._format_slot(slot)}. Duração: 1 hora. "
                    "Nosso consultor falará com você no horário agendado. 🍻"
                )
            except Exception:
                pass

        options = sc._meeting_options(lead, refresh=True)
        crm.db.session.commit()
        if len(options) >= 3:
            return fm._buttons_marker(
                "Esse horário não está mais disponível. Escolha uma destas novas opções:",
                [
                    {"id": "1", "title": sc._format_slot(options[0])[:20]},
                    {"id": "2", "title": sc._format_slot(options[1])[:20]},
                    {"id": "3", "title": sc._format_slot(options[2])[:20]},
                ],
            )

    return None


def _apply_answer_final_v2(lead, text, inbound_count, channel):
    if inbound_count == 2:
        lead.city = text.strip()[:120]

    elif inbound_count == 3:
        lead.state = text.strip().upper()[:40]

    elif inbound_count == 4:
        sc._set_tag(lead, "Q_ACCESS", p._parse_access(text))

    elif inbound_count == 5:
        t = (text or "").strip().lower()
        if t.startswith("1"):
            lead.investment = 18900
        elif t.startswith("2"):
            lead.investment = 30000
        elif t.startswith("3"):
            lead.investment = 45000
        else:
            value = p._parse_investment(text)
            if value > 0:
                lead.investment = value

    elif inbound_count == 6:
        lead.timeframe = sc._parse_timeframe_final(text)

    elif inbound_count == 7:
        sc._set_tag(lead, "Q_OBJECTIVE", p._parse_objective(text))

    elif inbound_count == 8:
        lead.meeting_interest = p._yes_no(text)

    elif inbound_count == 9 and lead.meeting_interest == "Sim":
        sc._schedule_choice(lead, text)

    crm.requalify(lead, preserve=False)

    if lead.meeting_interest == "Sim" and lead.stage != "Reunião Agendada":
        lead.stage = "Prioridade / Reunião"
    if sc._tag_value(lead, "Q_MEETING_SLOT"):
        lead.stage = "Reunião Agendada"

    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action=f"Pipeline atualizado pelo {channel}",
        detail=f"Fluxo final; resposta {inbound_count}; score {lead.score}; etapa {lead.stage}",
    ))


# Sobrescreve tanto o módulo base quanto o módulo que mantém o webhook rico.
p._qualification_reply = _qualification_reply_final_v2
p._reply_for_message = lambda lead, text: _qualification_reply_final_v2(lead, "WhatsApp")
p._reply_for_instagram = lambda lead: _qualification_reply_final_v2(lead, "Instagram")
p._apply_answer_by_count = _apply_answer_final_v2

fm._qualification_reply = _qualification_reply_final_v2
