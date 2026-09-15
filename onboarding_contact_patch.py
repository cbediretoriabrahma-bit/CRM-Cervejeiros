"""Coleta inicial de Nome, WhatsApp, Cidade e Estado no CRM Cervejeiros.

Este patch roda por último e desloca as perguntas comerciais em +2 mensagens,
sem alterar score, temperatura, pipeline ou regras comerciais existentes.
"""
import re

import flow_media_patch as fm
import meeting_day_selection_patch as mds
import patched_app as p
import sitecustomize as sc

crm = p.crm


def _count(lead, channel):
    return crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()


def _clean_phone(text):
    digits = re.sub(r"\D", "", text or "")
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits[:40]


def _objective(text):
    t = (text or "").strip().lower()
    if t.startswith("1") or "investidor" in t:
        return "investidor"
    if t.startswith("2") or "nova fonte" in t or "renda" in t:
        return "renda_complementar"
    if t.startswith("3") or "expandir" in t:
        return "expandir"
    try:
        return p._parse_objective(text)
    except Exception:
        return ""


def _reply(lead, channel):
    n = _count(lead, channel)
    first = (lead.name or "Olá").split()[0]

    if n <= 1:
        return (
            "*Bem-vindo ao CERVEJEIROS by WOC Group!* 🍻\n\n"
            "Conheça nosso *sistema de geladeiras de autoatendimento de chopp* para condomínios, clubes e locais de grande circulação.\n\n"
            "Uma operação *prática, tecnológica e escalável*.\n\n"
            "👤 *Qual é o seu NOME?*"
        )

    if n == 2:
        return "📱 *Qual é o seu WHATSAPP com DDD?*"

    if n == 3:
        return "📍 *Em qual CIDADE você pretende operar?*"

    if n == 4:
        return "🗺️ *Qual é o ESTADO?*"

    if n == 5:
        return fm._buttons_marker(
            "*Agora vamos entender um pouco melhor o seu perfil.*\n\n"
            "*Você já possui contato ou acesso a condomínios, clubes ou locais de grande circulação?*",
            [
                {"id": "1", "title": "Locais em vista"},
                {"id": "2", "title": "Alguns contatos"},
                {"id": "3", "title": "Vou prospectar"},
            ],
        )

    if n == 6:
        return fm._buttons_marker(
            "*Qual faixa de investimento inicial você pretende realizar?*",
            [
                {"id": "1", "title": "R$18,9mil a R$29,9mil"},
                {"id": "2", "title": "R$30mil a R$44,9mil"},
                {"id": "3", "title": "R$45mil a R$55mil"},
            ],
        )

    if n == 7:
        return fm._list_marker(
            "*Em quanto tempo você pretende iniciar sua operação?*",
            "Escolher prazo",
            [
                {"id": "1", "title": "Imediatamente"},
                {"id": "2", "title": "Em até 30 dias"},
                {"id": "3", "title": "Em até 60 dias"},
                {"id": "4", "title": "Acima de 60 dias"},
            ],
        )

    if n == 8:
        return fm._buttons_marker(
            "*Qual é o seu principal objetivo ao entrar para o modelo Cervejeiros?*\n\n"
            "1️⃣ *Investidor*\n"
            "2️⃣ *Nova fonte de renda*\n"
            "3️⃣ *Expandir o modelo de negócio em minha cidade*",
            [
                {"id": "1", "title": "Investidor"},
                {"id": "2", "title": "Nova fonte de renda"},
                {"id": "3", "title": "Expandir na cidade"},
            ],
        )

    if n == 9:
        return fm._buttons_marker(
            f"*Perfeito, {first}!* 🍻 Agora que conhecemos um pouco melhor o seu perfil, queremos apresentar a *CERVEJEIROS by WOC Group*.\n\n"
            "A Cervejeiros atua com *geladeiras de autoatendimento de chopp para condomínios, clubes e locais de grande circulação*, em um modelo pensado para ser *prático, tecnológico e escalável*.\n\n"
            "*Hoje já possuímos licenciados em vários estados do Brasil:*\n"
            "📍 São Paulo\n📍 Minas Gerais\n📍 Goiás\n📍 Rio de Janeiro\n📍 Amazonas\n\n"
            "O licenciado conta com *sistema de autoatendimento 24 horas, tecnologia de pagamento, dashboard para acompanhamento das vendas*, controle da operação, suporte de implantação, treinamento, materiais comerciais e possibilidade de expansão para novos pontos.\n\n"
            "O modelo *não exige funcionário no ponto* e foi estruturado para permitir crescimento gradual em condomínios, clubes e outros locais de grande circulação.\n\n"
            "*Gostaria de conversar com um de nossos consultores para conhecer o projeto completo, os planos, valores e as oportunidades disponíveis para sua região?*",
            [
                {"id": "1", "title": "Quero agendar"},
                {"id": "2", "title": "Entender melhor"},
                {"id": "3", "title": "Só informações"},
            ],
        )

    if lead.meeting_interest == "Sim":
        selected = mds._confirmation(lead)
        if selected:
            return selected
        if n >= 10 and not mds._selected_day(lead):
            return mds._day_prompt(lead)
        if n >= 11 and mds._selected_day(lead):
            return mds._time_prompt(lead)

    if n == 10:
        if lead.meeting_interest == "Talvez":
            return (
                "Sem problema. 🍻 Vamos manter seu perfil em acompanhamento e podemos continuar enviando informações "
                "para você entender melhor o modelo antes de avançar para uma reunião."
            )
        if lead.meeting_interest != "Sim":
            return "Tudo certo. 🍻 Seu contato continuará cadastrado e estaremos à disposição quando quiser avançar."

    return None


def _apply(lead, text, inbound_count, channel):
    if inbound_count == 2:
        name = (text or "").strip()
        if name:
            lead.name = name[:160]

    elif inbound_count == 3:
        phone = _clean_phone(text)
        if phone:
            lead.phone = phone

    elif inbound_count == 4:
        lead.city = (text or "").strip()[:120]

    elif inbound_count == 5:
        lead.state = (text or "").strip().upper()[:40]

    elif inbound_count == 6:
        sc._set_tag(lead, "Q_ACCESS", p._parse_access(text))

    elif inbound_count == 7:
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

    elif inbound_count == 8:
        lead.timeframe = sc._parse_timeframe_final(text)

    elif inbound_count == 9:
        sc._set_tag(lead, "Q_OBJECTIVE", _objective(text))

    elif inbound_count == 10:
        lead.meeting_interest = p._yes_no(text)

    elif inbound_count >= 11 and lead.meeting_interest == "Sim":
        if sc._tag_value(lead, "Q_MEETING_SLOT"):
            pass
        elif not mds._selected_day(lead):
            day = mds._select_day(lead, text)
            if day:
                sc._set_tag(lead, "Q_MEETING_DAY", day.isoformat())
                mds._store_time_options(lead, day)
        else:
            mds._schedule_selected_time(lead, text)

    crm.requalify(lead, preserve=False)

    if lead.meeting_interest == "Sim" and lead.stage != "Reunião Agendada":
        lead.stage = "Prioridade / Reunião"
    if sc._tag_value(lead, "Q_MEETING_SLOT"):
        lead.stage = "Reunião Agendada"

    crm.db.session.add(crm.AutomationLog(
        lead_id=lead.id,
        action=f"Pipeline atualizado pelo {channel}",
        detail=f"Fluxo com contato inicial; resposta {inbound_count}; score {lead.score}; etapa {lead.stage}",
    ))


def _reply_whatsapp(lead, text):
    return _reply(lead, "WhatsApp")


def _reply_instagram(lead):
    return _reply(lead, "Instagram")


def _qualification(lead, channel):
    return _reply(lead, channel)


p._apply_answer_by_count = _apply
p._reply_for_message = _reply_whatsapp
p._reply_for_instagram = _reply_instagram
p._qualification_reply = _qualification
fm._qualification_reply = _qualification
