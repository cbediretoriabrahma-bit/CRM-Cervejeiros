"""Fluxo comercial com video apos cidade/UF e escolhas interativas.

Carregado por crm_entry.py depois dos patches anteriores. Mantem a qualificacao,
pontuacao e pipeline existentes, alterando apenas a apresentacao e o envio das
mensagens no WhatsApp/Instagram.
"""
import json
import os
import urllib.request
from datetime import datetime
from flask import request

import patched_app as p
import sitecustomize as sc

crm = p.crm

VIDEO_URL = os.getenv("QUALIFICATION_VIDEO_URL", "").strip()


def _buttons_marker(body, options):
    return "[[BUTTONS]]" + json.dumps({"body": body, "options": options}, ensure_ascii=False)


def _list_marker(body, button_text, options):
    return "[[LIST]]" + json.dumps({"body": body, "button": button_text, "options": options}, ensure_ascii=False)


def _parse_marker(message):
    if not isinstance(message, str):
        return None, None
    if message.startswith("[[BUTTONS]]"):
        try:
            return "buttons", json.loads(message[len("[[BUTTONS]]"):])
        except Exception:
            return None, None
    if message.startswith("[[LIST]]"):
        try:
            return "list", json.loads(message[len("[[LIST]]"):])
        except Exception:
            return None, None
    return None, None


def _qualification_reply(lead, channel):
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()
    first = (lead.name or "Olá").split()[0]

    if inbound_count <= 1:
        return (
            "Bem-vindo ao CERVEJEIROS by WOC Group! 🍻\n\n"
            "Você está iniciando seu atendimento para conhecer nosso sistema de geladeiras de autoatendimento de chopp "
            "para condomínios, clubes e locais de grande circulação.\n\n"
            "Nosso modelo foi desenvolvido para oferecer uma operação prática, tecnológica e escalável, com gestão pelo sistema "
            "e possibilidade de expansão para novos pontos.\n\n"
            "Para começarmos, em qual cidade você pretende operar?"
        )
    if inbound_count == 2:
        return f"Perfeito, {first}! E em qual estado fica essa cidade?"
    if inbound_count == 3:
        return _buttons_marker(
            "Agora vamos entender um pouco melhor o seu perfil.\n\nVocê já possui contato ou acesso a condomínios, clubes ou locais de grande circulação?",
            [
                {"id": "1", "title": "Locais em vista"},
                {"id": "2", "title": "Alguns contatos"},
                {"id": "3", "title": "Vou prospectar"},
            ],
        )
    if inbound_count == 4:
        return _buttons_marker(
            "Quantos condomínios ou clubes você acredita conseguir prospectar?",
            [
                {"id": "1", "title": "1 a 4"},
                {"id": "2", "title": "5 a 9"},
                {"id": "3", "title": "10 ou mais"},
            ],
        )
    if inbound_count == 5:
        return _buttons_marker(
            "Com qual modelo você pretende iniciar?",
            [
                {"id": "1", "title": "Standard - 1"},
                {"id": "2", "title": "Pro - 2"},
                {"id": "3", "title": "Premium - 3"},
            ],
        )
    if inbound_count == 6:
        return _buttons_marker(
            "Qual faixa de investimento você tem disponível para iniciar?",
            [
                {"id": "1", "title": "R$18.900-29.999"},
                {"id": "2", "title": "R$30.000-44.999"},
                {"id": "3", "title": "R$45.000-55.000"},
            ],
        )
    if inbound_count == 7:
        return _list_marker(
            "Em quanto tempo você pretende começar a prospectar condomínios e clubes?",
            "Escolher prazo",
            [
                {"id": "1", "title": "Imediatamente"},
                {"id": "2", "title": "Em até 30 dias"},
                {"id": "3", "title": "Em até 60 dias"},
                {"id": "4", "title": "Acima de 60 dias"},
            ],
        )
    if inbound_count == 8:
        return _buttons_marker(
            "Qual é o seu principal objetivo com o negócio?",
            [
                {"id": "1", "title": "Expandir"},
                {"id": "2", "title": "Começar e avaliar"},
                {"id": "3", "title": "Renda complementar"},
            ],
        )
    if inbound_count == 9:
        return _buttons_marker(
            (
                "Seu perfil já nos deu uma boa visão do projeto. 🍻\n\n"
                "O CERVEJEIROS by WOC Group trabalha com uma operação enxuta, tecnológica e escalável: sem funcionário no ponto, "
                "funcionamento 24 horas, gestão de vendas pelo sistema, suporte de implantação e possibilidade de expansão para novos pontos.\n\n"
                "Gostaria de falar com um de nossos consultores para conhecer os planos, valores e o formato mais adequado para sua região?"
            ),
            [
                {"id": "1", "title": "Sim"},
                {"id": "2", "title": "Talvez depois"},
                {"id": "3", "title": "Agora não"},
            ],
        )
    if inbound_count == 10:
        if lead.meeting_interest == "Sim":
            options = sc._meeting_options(lead, refresh=True)
            if len(options) >= 3:
                crm.db.session.commit()
                return _buttons_marker(
                    "Perfeito! Escolha um horário disponível. Cada reunião dura 1 hora:",
                    [
                        {"id": "1", "title": sc._format_slot(options[0])[:20]},
                        {"id": "2", "title": sc._format_slot(options[1])[:20]},
                        {"id": "3", "title": sc._format_slot(options[2])[:20]},
                    ],
                )
            return "Perfeito! Nosso consultor vai entrar em contato para combinar o melhor horário."
        if lead.meeting_interest == "Talvez":
            return "Sem problema. Vamos manter seu perfil em acompanhamento e você pode avançar quando desejar. 🍻"
        return "Tudo certo. Seu contato continuará cadastrado e estaremos à disposição quando quiser avançar. 🍻"
    if inbound_count == 11 and lead.meeting_interest == "Sim":
        selected = sc._tag_value(lead, "Q_MEETING_SLOT")
        if selected:
            try:
                slot = datetime.fromisoformat(selected)
                return f"✅ Reunião confirmada para {sc._format_slot(slot)}. Duração: 1 hora. Nosso consultor falará com você no horário agendado. 🍻"
            except Exception:
                pass
        options = sc._meeting_options(lead, refresh=True)
        crm.db.session.commit()
        if len(options) >= 3:
            return _buttons_marker(
                "Esse horário não está mais disponível. Escolha uma destas novas opções:",
                [
                    {"id": "1", "title": sc._format_slot(options[0])[:20]},
                    {"id": "2", "title": sc._format_slot(options[1])[:20]},
                    {"id": "3", "title": sc._format_slot(options[2])[:20]},
                ],
            )
    return None


p._qualification_reply = _qualification_reply
p._reply_for_message = lambda lead, text: _qualification_reply(lead, "WhatsApp")
p._reply_for_instagram = lambda lead: _qualification_reply(lead, "Instagram")


def _wa_post(phone, payload):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_id:
        return False, "WhatsApp Cloud API não configurada."
    payload = dict(payload)
    payload.update({"messaging_product": "whatsapp", "to": crm.normalize_phone(phone)})
    req = urllib.request.Request(
        f"https://graph.facebook.com/v23.0/{phone_id}/messages",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return True, response.read().decode()
    except Exception as exc:
        return False, str(exc)


def _send_whatsapp_rich(phone, message):
    kind, data = _parse_marker(message)
    if kind == "buttons":
        buttons = [
            {"type": "reply", "reply": {"id": str(opt["id"]), "title": opt["title"][:20]}}
            for opt in data.get("options", [])[:3]
        ]
        return _wa_post(phone, {
            "type": "interactive",
            "interactive": {"type": "button", "body": {"text": data.get("body", "")}, "action": {"buttons": buttons}},
        })
    if kind == "list":
        rows = [
            {"id": str(opt["id"]), "title": opt["title"][:24]}
            for opt in data.get("options", [])[:10]
        ]
        return _wa_post(phone, {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": data.get("body", "")},
                "action": {"button": data.get("button", "Escolher")[:20], "sections": [{"title": "Opções", "rows": rows}]},
            },
        })
    return _wa_post(phone, {"type": "text", "text": {"body": message}})


crm.send_whatsapp_cloud = _send_whatsapp_rich


def _send_whatsapp_video(phone):
    if not VIDEO_URL:
        return False, "QUALIFICATION_VIDEO_URL não configurada"
    return _wa_post(phone, {
        "type": "video",
        "video": {
            "link": VIDEO_URL,
            "caption": "Veja rapidamente como funciona o sistema de geladeiras de autoatendimento CERVEJEIROS by WOC Group na prática. 👇🍻",
        },
    })


def _extract_whatsapp_text(message):
    mtype = message.get("type")
    if mtype == "text":
        return ((message.get("text") or {}).get("body") or "").strip()
    if mtype == "interactive":
        interactive = message.get("interactive") or {}
        if interactive.get("type") == "button_reply":
            reply = interactive.get("button_reply") or {}
            return str(reply.get("id") or reply.get("title") or "").strip()
        if interactive.get("type") == "list_reply":
            reply = interactive.get("list_reply") or {}
            return str(reply.get("id") or reply.get("title") or "").strip()
    if mtype == "button":
        button = message.get("button") or {}
        return str(button.get("payload") or button.get("text") or "").strip()
    return ""


def whatsapp_webhook_rich():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("WHATSAPP_VERIFY_TOKEN"):
            return request.args.get("hub.challenge", ""), 200
        return "verification failed", 403

    data = request.get_json(silent=True) or {}
    try:
        value = data["entry"][0]["changes"][0]["value"]
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        contact_name = ""
        if contacts:
            contact_name = ((contacts[0].get("profile") or {}).get("name") or "").strip()

        for m in messages:
            message_id = m.get("id", "")
            if p._already_processed(message_id):
                continue
            phone = m.get("from", "")
            text = _extract_whatsapp_text(m)
            if not phone or not text:
                continue

            lead = p._find_lead_by_phone(phone)
            if lead and p._recent_duplicate(lead, text):
                continue
            if not lead:
                lead = crm.Lead(
                    name=contact_name or f"WhatsApp {phone[-4:]}",
                    phone=crm.normalize_phone(phone),
                    source="WhatsApp",
                    timeframe="Sem prazo",
                    stage="Novo Lead",
                )
                crm.db.session.add(lead)
                crm.db.session.flush()
                crm.assign_round_robin(lead)
                crm.requalify(lead, preserve=False)
                crm.db.session.add(crm.AutomationLog(
                    lead_id=lead.id,
                    action="Lead criado pelo WhatsApp",
                    detail="Novo contato recebido automaticamente pelo webhook do WhatsApp.",
                ))

            crm.db.session.add(crm.Interaction(lead_id=lead.id, channel="WhatsApp", direction="in", message=text))
            lead.last_contact = datetime.utcnow()
            crm.db.session.flush()
            inbound_count = crm.Interaction.query.filter_by(lead_id=lead.id, channel="WhatsApp", direction="in").count()
            p._apply_answer_by_count(lead, text, inbound_count, "WhatsApp")

            if message_id:
                crm.db.session.add(crm.AutomationLog(lead_id=lead.id, action="WhatsApp message processada", detail=message_id))
            crm.db.session.commit()

            if os.getenv("AUTO_REPLY_WHATSAPP", "0") == "1":
                # Depois da resposta de estado (3a entrada), envia o video antes da proxima pergunta.
                if inbound_count == 3:
                    ok_video, detail_video = _send_whatsapp_video(lead.phone)
                    if not ok_video:
                        crm.app.logger.warning("Video WhatsApp não enviado lead=%s: %s", lead.id, detail_video)
                reply = _qualification_reply(lead, "WhatsApp")
                if not reply:
                    continue
                ok, detail = _send_whatsapp_rich(lead.phone, reply)
                if ok:
                    log_message = reply
                    kind, parsed = _parse_marker(reply)
                    if kind:
                        log_message = parsed.get("body", reply)
                    crm.db.session.add(crm.Interaction(
                        lead_id=lead.id, channel="WhatsApp", direction="out", message=log_message, ai_generated=False
                    ))
                    crm.db.session.commit()
                else:
                    crm.app.logger.warning("Falha ao responder WhatsApp lead=%s: %s", lead.id, detail)
                    crm.db.session.rollback()
    except Exception as exc:
        crm.app.logger.warning("Webhook WhatsApp rico: %s", exc)
        crm.db.session.rollback()
    return "ok", 200


if "whatsapp_webhook" in crm.app.view_functions:
    crm.app.view_functions["whatsapp_webhook"] = whatsapp_webhook_rich


def _send_instagram_rich(recipient_id, message, token):
    if not token:
        return False, "Token da conta do Instagram não configurado."
    kind, data = _parse_marker(message)
    msg = {"text": message}
    if kind in {"buttons", "list"}:
        opts = data.get("options", [])
        msg = {
            "text": data.get("body", ""),
            "quick_replies": [
                {"content_type": "text", "title": opt["title"][:20], "payload": str(opt["id"])}
                for opt in opts[:13]
            ],
        }
    payload = json.dumps({
        "recipient": {"id": str(recipient_id)},
        "messaging_type": "RESPONSE",
        "message": msg,
    }).encode()
    req = urllib.request.Request(
        "https://graph.facebook.com/v23.0/me/messages",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return True, response.read().decode()
    except Exception as exc:
        return False, str(exc)


sc._send_instagram = _send_instagram_rich
