import os
from datetime import datetime
from flask import request

import app as crm


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

            local = phone[-11:]
            lead = crm.Lead.query.filter(crm.Lead.phone.like(f"%{local}%")).order_by(crm.Lead.id.desc()).first()

            if not lead:
                lead = crm.Lead(
                    name=contact_name or f"WhatsApp {phone[-4:]}",
                    phone=phone,
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

            if os.getenv("AUTO_REPLY_WHATSAPP", "0") == "1":
                reply = crm.ai_reply(lead, "responder a mensagem recebida e avançar o lead")
                ok, _ = crm.send_whatsapp_cloud(lead.phone, reply)
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

            crm.db.session.commit()
    except Exception as e:
        crm.app.logger.warning("Webhook WhatsApp: %s", e)
        crm.db.session.rollback()

    return "ok", 200


# Mantém a rota já registrada em app.py, mas troca a função executada por esta versão.
crm.app.view_functions["whatsapp_webhook"] = whatsapp_webhook
app = crm.app
