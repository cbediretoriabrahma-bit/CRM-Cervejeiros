import os
from datetime import datetime, timedelta
from flask import request

import app as crm


def _find_lead_by_phone(phone):
    target = crm.normalize_phone(phone)
    if not target:
        return None
    for lead in crm.Lead.query.order_by(crm.Lead.id.desc()).all():
        if crm.normalize_phone(lead.phone) == target:
            return lead
    return None


def _reply_for_message(lead, text):
    """Fluxo com uma única pergunta por mensagem.
    Depois que o interessado informa o horário, envia confirmação e encerra
    as perguntas automáticas para não repetir a última pergunta.
    """
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel="WhatsApp", direction="in"
    ).count()
    first = (lead.name or "Olá").split()[0]

    if inbound_count <= 1:
        return f"Olá, {first}! 🍻 Obrigado pelo interesse na Cervejeiros. Em qual cidade você pretende operar?"
    if inbound_count == 2:
        return f"Perfeito, {first}! Em qual estado fica essa cidade?"
    if inbound_count == 3:
        return f"Ótimo, {first}. Qual faixa de investimento você pretende disponibilizar para iniciar a operação?"
    if inbound_count == 4:
        return f"Obrigado, {first}. Em quanto tempo você gostaria de iniciar a operação Cervejeiros?"
    if inbound_count == 5:
        return f"Perfeito, {first}. Você já é empreendedor?"
    if inbound_count == 6:
        return f"Certo, {first}. Você tem interesse em conhecer o modelo em uma reunião rápida?"
    if inbound_count == 7:
        return f"Ótimo, {first}. Qual dia funciona melhor para você?"
    if inbound_count == 8:
        return f"Perfeito, {first}. Qual horário funciona melhor para você nesse dia?"
    if inbound_count == 9:
        return f"Perfeito, {first}! Recebi seu dia e horário. Nossa equipe vai confirmar a reunião com você por aqui. 🍻"
    return None


def _already_processed(message_id):
    if not message_id:
        return False
    return crm.AutomationLog.query.filter_by(
        action="WhatsApp message processada",
        detail=message_id,
    ).first() is not None


def _recent_duplicate(lead, text):
    if not lead or not text:
        return False
    cutoff = datetime.utcnow() - timedelta(seconds=20)
    return crm.Interaction.query.filter(
        crm.Interaction.lead_id == lead.id,
        crm.Interaction.channel == "WhatsApp",
        crm.Interaction.direction == "in",
        crm.Interaction.message == text,
        crm.Interaction.created_at >= cutoff,
    ).first() is not None


def whatsapp_webhook():
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
            if _already_processed(message_id):
                crm.app.logger.warning("Webhook duplicado ignorado: %s", message_id)
                continue

            phone = m.get("from", "")
            text = (m.get("text") or {}).get("body", "")
            if not phone or not text:
                continue

            lead = _find_lead_by_phone(phone)
            created = False

            if lead and _recent_duplicate(lead, text):
                crm.app.logger.warning("Mensagem repetida ignorada para lead=%s", lead.id)
                continue

            if not lead:
                created = True
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
                crm.db.session.add(
                    crm.AutomationLog(
                        lead_id=lead.id,
                        action="Lead criado pelo WhatsApp",
                        detail="Novo contato recebido automaticamente pelo webhook do WhatsApp.",
                    )
                )

            crm.db.session.add(
                crm.Interaction(
                    lead_id=lead.id,
                    channel="WhatsApp",
                    direction="in",
                    message=text,
                )
            )
            lead.last_contact = datetime.utcnow()

            if message_id:
                crm.db.session.add(
                    crm.AutomationLog(
                        lead_id=lead.id,
                        action="WhatsApp message processada",
                        detail=message_id,
                    )
                )

            crm.db.session.commit()
            crm.app.logger.warning(
                "WhatsApp salvo: lead_id=%s criado=%s telefone=%s message_id=%s owner_id=%s",
                lead.id, created, crm.normalize_phone(phone), message_id, lead.owner_id
            )

            if os.getenv("AUTO_REPLY_WHATSAPP", "0") == "1":
                reply = _reply_for_message(lead, text)
                if not reply:
                    crm.app.logger.warning("Fluxo automatico encerrado para lead=%s", lead.id)
                    continue
                ok, detail = crm.send_whatsapp_cloud(lead.phone, reply)
                if ok:
                    crm.db.session.add(
                        crm.Interaction(
                            lead_id=lead.id,
                            channel="WhatsApp",
                            direction="out",
                            message=reply,
                            ai_generated=False,
                        )
                    )
                    crm.db.session.commit()
                else:
                    crm.app.logger.warning("Falha ao responder WhatsApp lead=%s: %s", lead.id, detail)
                    crm.db.session.rollback()

    except Exception as e:
        crm.app.logger.warning("Webhook WhatsApp: %s", e)
        crm.db.session.rollback()

    return "ok", 200


crm.app.view_functions["whatsapp_webhook"] = whatsapp_webhook
app = crm.app
