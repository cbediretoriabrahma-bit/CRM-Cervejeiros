"""Ajustes finais de continuidade e apresentação do fluxo Cervejeiros.

- Evita a interrupção do Instagram após a resposta de objetivo, usando uma
  apresentação curta o suficiente para a API do Direct.
- Converte trechos marcados com *asteriscos* em caracteres Unicode destacados
  no Instagram, evitando que os asteriscos apareçam literalmente.
- Destaca CIDADE e ESTADO em maiúsculas.
- Evita repetir a pergunta de CIDADE quando o cliente já respondeu ao prompt
  anterior no Direct.
- Mantém a lógica, score, pipeline e respostas do WhatsApp já existentes.
"""
import json
import re

import final_qualification_patch as fq
import flow_media_patch as fm
import patched_app as p

crm = p.crm


def _unicode_bold(text):
    """Converte ASCII alfanumérico para Mathematical Sans-Serif Bold."""
    out = []
    for ch in str(text):
        code = ord(ch)
        if 65 <= code <= 90:  # A-Z
            out.append(chr(0x1D5D4 + (code - 65)))
        elif 97 <= code <= 122:  # a-z
            out.append(chr(0x1D5EE + (code - 97)))
        elif 48 <= code <= 57:  # 0-9
            out.append(chr(0x1D7EC + (code - 48)))
        else:
            out.append(ch)
    return "".join(out)


def _render_instagram_markup(text):
    """Troca *trechos importantes* por destaque visual real no Direct."""
    if not isinstance(text, str):
        return text

    def repl(match):
        return _unicode_bold(match.group(1))

    return re.sub(r"\*([^*]+)\*", repl, text)


def _instagramize(message):
    """Aplica o destaque também ao corpo de botões/listas do Instagram."""
    kind, data = fm._parse_marker(message)
    if kind:
        data = dict(data or {})
        data["body"] = _render_instagram_markup(data.get("body", ""))
        if kind == "buttons":
            return "[[BUTTONS]]" + json.dumps(data, ensure_ascii=False)
        return "[[LIST]]" + json.dumps(data, ensure_ascii=False)
    return _render_instagram_markup(message)


def _instagram_city_already_asked(lead):
    """Detecta se o CRM já perguntou a cidade antes da resposta atual."""
    previous = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel="Instagram", direction="out"
    ).order_by(crm.Interaction.created_at.desc()).first()
    text = (previous.message or "") if previous else ""
    upper = text.upper()
    return "CIDADE" in upper and ("QUAL" in upper or "PRETENDE OPERAR" in upper)


def _latest_instagram_inbound(lead):
    row = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel="Instagram", direction="in"
    ).order_by(crm.Interaction.created_at.desc()).first()
    return (row.message or "").strip() if row else ""


def _styled_reply(lead, channel):
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()
    first = (lead.name or "Olá").split()[0]

    # Instagram: se a pergunta de cidade já foi enviada e o cliente acabou de
    # responder (ex.: "Mogi"), registra essa resposta como cidade e segue para
    # ESTADO em vez de repetir a mesma pergunta.
    if channel == "Instagram" and inbound_count <= 1 and _instagram_city_already_asked(lead):
        city = _latest_instagram_inbound(lead)
        if city:
            lead.city = city[:120]
            crm.db.session.commit()
        reply = "Perfeito! 📍 *Em qual ESTADO fica essa CIDADE?*"
        return _instagramize(reply)

    # Abertura com CIDADE em destaque.
    if inbound_count <= 1:
        reply = (
            "*Bem-vindo ao CERVEJEIROS by WOC Group!* 🍻\n\n"
            "Conheça nosso *sistema de geladeiras de autoatendimento de chopp* para condomínios, clubes e locais de grande circulação.\n\n"
            "Uma operação *prática, tecnológica e escalável*.\n\n"
            "📍 *Em qual CIDADE você pretende operar?*"
        )
        return _instagramize(reply) if channel == "Instagram" else reply

    # Estado em caixa alta e destaque.
    if inbound_count == 2:
        reply = "Perfeito! 📍 *Em qual ESTADO fica essa CIDADE?*"
        return _instagramize(reply) if channel == "Instagram" else reply

    # Pergunta de objetivo com apresentação visual mais forte.
    if inbound_count == 6:
        reply = fm._buttons_marker(
            (
                "🎯 *Qual é o seu principal objetivo ao entrar para o modelo Cervejeiros?*\n\n"
                "1️⃣ *Investidor*\n"
                "2️⃣ *Nova fonte de renda*\n"
                "3️⃣ *Expandir o modelo de negócio em minha cidade*"
            ),
            [
                {"id": "1", "title": "Investidor"},
                {"id": "2", "title": "Nova fonte de renda"},
                {"id": "3", "title": "Expandir na cidade"},
            ],
        )
        return _instagramize(reply) if channel == "Instagram" else reply

    # Esta era a resposta que podia exceder o limite prático do Direct e parar
    # o fluxo logo após "Investidor". Mantemos a informação, mas de forma curta.
    if inbound_count == 7:
        reply = fm._buttons_marker(
            (
                f"🍻 *Perfeito, {first}!*\n\n"
                "Seu perfil combina com o modelo *CERVEJEIROS by WOC Group*.\n\n"
                "✅ Autoatendimento 24 horas\n"
                "✅ Sem funcionário no ponto\n"
                "✅ Pagamentos e vendas pelo sistema\n"
                "✅ Dashboard em tempo real\n"
                "✅ Suporte de implantação e treinamento\n"
                "✅ Possibilidade de expansão\n\n"
                "📍 Já temos licenciados em *SP, MG, GO, RJ e AM*.\n\n"
                "🤝 *Quer conversar com um de nossos consultores para conhecer os planos, valores e oportunidades disponíveis para sua região?*"
            ),
            [
                {"id": "1", "title": "Quero agendar"},
                {"id": "2", "title": "Entender melhor"},
                {"id": "3", "title": "Só informações"},
            ],
        )
        return _instagramize(reply) if channel == "Instagram" else reply

    reply = fq._qualification_reply_final_v2(lead, channel)
    return _instagramize(reply) if channel == "Instagram" and reply else reply


# Garante que tanto os webhooks quanto o envio rico usem esta versão.
p._qualification_reply = _styled_reply
p._reply_for_message = lambda lead, text: _styled_reply(lead, "WhatsApp")
p._reply_for_instagram = lambda lead: _styled_reply(lead, "Instagram")
fm._qualification_reply = _styled_reply
