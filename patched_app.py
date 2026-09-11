import os
from datetime import datetime
from flask import request

import app as crm


def _find_lead_by_phone(phone):
    target = crm.normalize_phone(phone)
    if not target:
        return None
    # Evita casar números diferentes só por um trecho do telefone.
    for lead in crm.Lead.query.order_by(crm.Lead.id.desc()).all():
        if crm.normalize_phone(lead.phone) == target:
            return lead
    return None


def _reply_for_message(lead, text):
    objective = (
        "responder à mensagem recebida no WhatsApp e avançar a qualificação. "
        f"Mensagem atual do cliente: {text}. "
        "Não repita literalmente a última resposta enviada. Faça uma pergunta útil para avançar."
    )
    reply = crm.ai_reply(lead, objective)

    last_out = (
        crm.Interaction.query.filter_by(lead_id=lead.id, channel="WhatsApp", direction="out")
        .order_by(crm.Interaction.id.desc())
        .first()
    )
    if last_out and (last_out.message or "").strip() == (reply or "").strip():
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel="WhatsApp", direction="in"
        ).count()
        first = (lead.name or "Olá").split()[0]
        if inbound_count <= 1:
            reply = f"Perfeito, {first}! Para continuarmos, em qual cidade você pretende operar?"
        elif inbound_count == 2:
            reply = f"Ótimo, {first}. Qual faixa de investimento você pretende disponibilizar para iniciar a operação?"
        else:
            reply = f"Obrigado, {first}. Em quanto tempo você gostaria de iniciar a operação Cervejeiros?"
    return reply


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
            phone = m.get("from", "")
            text = (m.get("text") or {}).get("body", "")
            if not phone or not text:
                continue

            lead = _find_lead_by_phone(phone)
            created = False

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
            crm.db.session.flush()

            if os.getenv("AUTO_REPLY_WHATSAPP", "0") == "1":
                reply = _reply_for_message(lead, text)
                ok, detail = crm.send_whatsapp_cloud(lead.phone, reply)
                if ok:
                    crm.db.session.add(
                        crm.Interaction(
                            lead_id=lead.id,
                            channel="WhatsApp",
                            direction="out",
                            message=reply,
                            ai_generated=True,
                        )
                    )
                else:
                    crm.app.logger.warning("Falha ao responder WhatsApp lead=%s: %s", lead.id, detail)

            crm.db.session.commit()
            crm.app.logger.info(
                "WhatsApp recebido: lead_id=%s criado=%s telefone=%s",
                lead.id, created, crm.normalize_phone(phone)
            )
    except Exception as e:
        crm.app.logger.warning("Webhook WhatsApp: %s", e)
        crm.db.session.rollback()

    return "ok", 200


# Mantém a rota já registrada em app.py, mas troca a função executada por esta versão.
crm.app.view_functions["whatsapp_webhook"] = whatsapp_webhook
app = crm.app
