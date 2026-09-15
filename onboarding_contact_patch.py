"""Coleta inicial e apresentação comercial do CRM Cervejeiros.

Fluxo: Nome -> WhatsApp -> Cidade -> Estado -> convite para apresentação ->
apresentação Cervejeiros -> confirmação de interesse -> qualificação comercial.
Mantém score, temperatura, pipeline e agendamento existentes.
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


def _is_yes(text):
    t = (text or "").strip().lower()
    return (
        t.startswith("1")
        or t.startswith("sim")
        or "quero" in t
        or "continuar" in t
        or "conhecer" in t
    )


def _presentation_text():
    return (
        "🍺 *CERVEJEIROS AUTOATENDIMENTO*\n\n"
        "*UMA OPERAÇÃO MODERNA, LUCRATIVA E SEM FUNCIONÁRIOS NO PONTO DE VENDA*\n\n"
        "As *geladeiras de autoatendimento Cervejeiros* foram desenvolvidas para transformar locais de grande circulação e consumo recorrente em *pontos de venda automatizados, rentáveis e extremamente práticos*.\n\n"
        "Nosso modelo é especialmente indicado para:\n\n"
        "🏢 *Condomínios residenciais*\n"
        "🏊 *Clubes e áreas de lazer*\n"
        "🎉 *Espaços de eventos e convivência*\n"
        "🏘️ *Empreendimentos com público recorrente*\n\n"
        "O grande diferencial está em unir *tecnologia, baixo custo operacional e alta recorrência de consumo*.\n\n"
        "━━━━━━━━━━━━━━\n"
        "💰 *ALTO POTENCIAL DE RENTABILIDADE*\n\n"
        "A operação Cervejeiros possui uma estrutura enxuta.\n\n"
        "Não é necessário manter um funcionário exclusivamente no ponto de venda.\n\n"
        "Isso significa redução significativa de despesas com:\n\n"
        "✔ *Salários*\n"
        "✔ *Encargos trabalhistas*\n"
        "✔ *Treinamento de equipe*\n"
        "✔ *Escalas de funcionários*\n"
        "✔ *Supervisão constante*\n"
        "✔ *Estrutura tradicional de atendimento*\n\n"
        "O resultado é uma operação com *baixo custo fixo e excelente potencial de margem operacional*.\n\n"
        "━━━━━━━━━━━━━━\n"
        "🔄 *RECORRÊNCIA QUE GERA VENDAS*\n\n"
        "Um dos maiores diferenciais do modelo Cervejeiros é trabalhar dentro de ambientes com *clientes recorrentes*.\n\n"
        "Em um condomínio, por exemplo, os moradores estão presentes todos os dias. Em um clube, os associados retornam constantemente.\n\n"
        "Isso significa que a operação não depende apenas de conquistar novos consumidores diariamente.\n\n"
        "O mesmo cliente pode comprar *durante a semana, finais de semana, churrascos, festas, encontros, jogos e momentos de lazer*.\n\n"
        "Essa frequência cria uma característica extremamente importante para qualquer negócio:\n\n"
        "*RECEITA RECORRENTE*\n\n"
        "Quanto maior o número de consumidores ativos e pontos instalados, maior o potencial de crescimento do faturamento.\n\n"
        "━━━━━━━━━━━━━━\n"
        "🏢 *VALORIZAÇÃO PARA O CONDOMÍNIO*\n\n"
        "A instalação de uma geladeira Cervejeiros também agrega valor ao empreendimento.\n\n"
        "O morador passa a contar com a comodidade de ter *chopp disponível dentro do próprio condomínio*, sem precisar:\n\n"
        "❌ sair de casa\n"
        "❌ esperar entrega\n"
        "❌ depender de horário de funcionamento de estabelecimentos\n\n"
        "A experiência se torna ainda mais valorizada em locais próximos a:\n\n"
        "*Piscinas • Churrasqueiras • Salões de festas • Espaços gourmet • Áreas de convivência*\n\n"
        "Para o condomínio, isso representa um *diferencial de conveniência e modernidade para os moradores*.\n\n"
        "━━━━━━━━━━━━━━\n"
        "🏊 *EXCELENTE SOLUÇÃO PARA CLUBES*\n\n"
        "Nos clubes, o modelo oferece uma nova opção de consumo para associados e visitantes sem a necessidade de criar toda uma nova estrutura de atendimento.\n\n"
        "A geladeira proporciona:\n\n"
        "✔ *Mais comodidade ao associado*\n"
        "✔ *Disponibilidade de produto no local*\n"
        "✔ *Operação simplificada*\n"
        "✔ *Menor dependência de mão de obra*\n"
        "✔ *Possibilidade de instalação em diferentes áreas do clube*\n\n"
        "━━━━━━━━━━━━━━\n"
        "🚀 *UM MODELO ESCALÁVEL*\n\n"
        "Uma das maiores vantagens do Cervejeiros Autoatendimento é a possibilidade de crescer através da instalação de novos equipamentos.\n\n"
        "O operador pode iniciar com uma unidade e, conforme desenvolve seu território, expandir para:\n\n"
        "*2 • 5 • 10 • 20 ou mais pontos de venda.*\n\n"
        "Cada novo condomínio ou clube conquistado representa uma nova fonte potencial de faturamento.\n\n"
        "Isso transforma a operação em um modelo de negócio com grande capacidade de *ESCALA*.\n\n"
        "━━━━━━━━━━━━━━\n"
        "📊 *OS 5 PILARES DO CERVEJEIROS AUTOATENDIMENTO*\n\n"
        "*1. BAIXO CUSTO OPERACIONAL*\n"
        "Operação automatizada e redução da necessidade de funcionários.\n\n"
        "*2. ALTA RECORRÊNCIA*\n"
        "Clientes consumindo repetidamente dentro dos mesmos locais.\n\n"
        "*3. BOA MARGEM OPERACIONAL*\n"
        "Estrutura enxuta favorecendo maior potencial de rentabilidade.\n\n"
        "*4. ESCALABILIDADE*\n"
        "Possibilidade de aumentar o faturamento instalando novas geladeiras.\n\n"
        "*5. VALORIZAÇÃO DO LOCAL*\n"
        "Mais comodidade e serviços para condomínios, clubes e seus usuários.\n\n"
        "━━━━━━━━━━━━━━\n"
        "🍺 *CERVEJEIROS AUTOATENDIMENTO*\n\n"
        "*MAIS QUE UMA GELADEIRA. UMA NOVA FORMA DE VENDER CHOPP.*\n\n"
        "*Sem funcionário no ponto de venda.*\n"
        "*Sem estrutura pesada de operação.*\n"
        "*Com clientes recorrentes.*\n"
        "*Com tecnologia.*\n"
        "*Com possibilidade de expansão.*\n"
        "*Com foco em rentabilidade.*\n\n"
        "*CERVEJEIROS — TECNOLOGIA, CONVENIÊNCIA, RECORRÊNCIA E LUCRO.* 🚀\n\n"
        "━━━━━━━━━━━━━━\n"
        "🤝 *Agora queremos saber a sua opinião.*\n\n"
        "Depois de conhecer um pouco melhor a nossa operação, *faz sentido para você fazer parte da CERVEJEIROS como nosso licenciado?*\n\n"
        "Se a resposta for *SIM*, podemos continuar com algumas perguntas rápidas para entender melhor o seu perfil e apresentar a oportunidade mais adequada para você.\n\n"
        "👉 *Deseja continuar?*"
    )


def _reply(lead, channel):
    n = _count(lead, channel)

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
            "🙏 *Obrigado pelas informações!*\n\n"
            "Agora queremos apresentar, de forma breve e objetiva, *como funciona a operação CERVEJEIROS* 🍻 e mostrar os principais motivos para você fazer parte do nosso modelo como *Licenciado Cervejeiros by WOC Group*.\n\n"
            "Você vai conhecer uma operação:\n\n"
            "✨ *Moderna e tecnológica*\n"
            "💰 *Com alto potencial de rentabilidade*\n"
            "🔄 *Com vendas recorrentes*\n"
            "👥 *Sem necessidade de funcionários no ponto de venda*\n"
            "📈 *Escalável, com possibilidade de expansão para vários pontos*\n"
            "🏢 *Ideal para condomínios, clubes e locais de grande circulação*\n\n"
            "👉 *Podemos iniciar a apresentação da operação Cervejeiros?*",
            [
                {"id": "1", "title": "SIM, QUERO CONHECER"},
                {"id": "2", "title": "NÃO, OBRIGADO"},
            ],
        )

    if n == 6:
        if sc._tag_value(lead, "Q_PRESENTATION_START") != "sim":
            return (
                "Tudo certo! 🍻 Agradecemos pelo seu interesse na *CERVEJEIROS by WOC Group*. "
                "Seu contato permanecerá cadastrado e estaremos à disposição caso queira conhecer a operação futuramente."
            )
        return fm._buttons_marker(
            _presentation_text(),
            [
                {"id": "1", "title": "SIM, QUERO CONTINUAR"},
                {"id": "2", "title": "NÃO, OBRIGADO"},
            ],
        )

    if n == 7:
        if sc._tag_value(lead, "Q_CONTINUE_QUALIFICATION") != "sim":
            return (
                "Sem problema! 🍻 Obrigado por conhecer a *CERVEJEIROS by WOC Group*. "
                "Seu contato continuará cadastrado e estaremos à disposição quando quiser avançar."
            )
        return fm._buttons_marker(
            "*Perfeito! Vamos continuar.* 🍻\n\n"
            "*Você já possui contato ou acesso a condomínios, clubes ou locais de grande circulação?*",
            [
                {"id": "1", "title": "Locais em vista"},
                {"id": "2", "title": "Alguns contatos"},
                {"id": "3", "title": "Vou prospectar"},
            ],
        )

    if n == 8:
        return fm._buttons_marker(
            "*Qual faixa de investimento inicial você pretende realizar?*",
            [
                {"id": "1", "title": "R$18,9mil a R$29,9mil"},
                {"id": "2", "title": "R$30mil a R$44,9mil"},
                {"id": "3", "title": "R$45mil a R$55mil"},
            ],
        )

    if n == 9:
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

    if n == 10:
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

    if n == 11:
        return fm._buttons_marker(
            "🍻 *Obrigado pelas respostas!*\n\n"
            "Agora já conseguimos entender melhor o seu perfil. *Gostaria de conversar com um de nossos consultores* para conhecer os planos, valores e as oportunidades disponíveis para sua região?",
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
        if n >= 12 and not mds._selected_day(lead):
            return mds._day_prompt(lead)
        if n >= 13 and mds._selected_day(lead):
            return mds._time_prompt(lead)

    if n == 12:
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
        sc._set_tag(lead, "Q_PRESENTATION_START", "sim" if _is_yes(text) else "nao")

    elif inbound_count == 7:
        sc._set_tag(lead, "Q_CONTINUE_QUALIFICATION", "sim" if _is_yes(text) else "nao")

    elif inbound_count == 8:
        sc._set_tag(lead, "Q_ACCESS", p._parse_access(text))

    elif inbound_count == 9:
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

    elif inbound_count == 10:
        lead.timeframe = sc._parse_timeframe_final(text)

    elif inbound_count == 11:
        sc._set_tag(lead, "Q_OBJECTIVE", _objective(text))

    elif inbound_count == 12:
        lead.meeting_interest = p._yes_no(text)

    elif inbound_count >= 13 and lead.meeting_interest == "Sim":
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
        detail=f"Fluxo com apresentação pré-qualificação; resposta {inbound_count}; score {lead.score}; etapa {lead.stage}",
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
