"""Hotfix de resposta automática do Instagram.

Garante que o webhook do Direct aceite texto e quick replies, grave a resposta,
aplique o mesmo fluxo de qualificação usado pelo CRM e envie a próxima pergunta.
"""
import os
from datetime import datetime
from flask import request

import patched_app as p
import sitecustomize as sc

crm = p.crm


def _extract_text(message):
    text = str((message or {}).get("text") or "").strip()
    if text:
        return text
    quick = (message or {}).get("quick_reply") or {}
    payload = str(quick.get("payload") or "").strip()
    if payload:
        return payload
    return ""


def instagram_webhook_hotfix():
    if request.method == "GET":
        verify_token = os.getenv("INSTAGRAM_VERIFY_TOKEN") or os.getenv("WHATSAPP_VERIFY_TOKEN")
        if request.args.get("hub.verify_token") == verify_token:
            return request.args.get("hub.challenge", ""), 200
        return "verification failed", 403

    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get("entry", []):
            entry_id = str(entry.get("id") or "")
            for event in entry.get("messaging", []):
                message = event.get("message") or {}
                if message.get("is_echo"):
                    continue

                sender_id = str((event.get("sender") or {}).get("id") or "")
                recipient_id = str((event.get("recipient") or {}).get("id") or "")
                page_id = entry_id or recipient_id
                message_id = str(message.get("mid") or "")
                text = _extract_text(message)
                if not sender_id or not text:
                    continue

                if message_id and p._instagram_already_processed(message_id):
                    continue

                account = sc._account_config(page_id)
                lead = sc._find_lead(page_id, sender_id)
                if not lead:
                    profile_name = sc._profile_name(sender_id, account["token"])
                    lead = crm.Lead(
                        name=profile_name or f"Instagram {sender_id[-4:]}",
                        phone=sc._lead_key(page_id, sender_id),
                        source="Instagram",
                        timeframe="Sem prazo",
                        stage="Novo Lead",
                        notes=f"Conta de origem: {account['label']} | Page ID: {page_id}",
                    )
                    crm.db.session.add(lead)
                    crm.db.session.flush()
                    crm.assign_round_robin(lead)
                    crm.requalify(lead, preserve=False)

                crm.db.session.add(crm.Interaction(
                    lead_id=lead.id,
                    channel="Instagram",
                    direction="in",
                    message=text,
                ))
                lead.last_contact = datetime.utcnow()
                crm.db.session.flush()

                inbound_count = crm.Interaction.query.filter_by(
                    lead_id=lead.id, channel="Instagram", direction="in"
                ).count()
                p._apply_answer_by_count(lead, text, inbound_count, "Instagram")

                if message_id:
                    crm.db.session.add(crm.AutomationLog(
                        lead_id=lead.id,
                        action="Instagram message processada",
                        detail=message_id,
                    ))
                crm.db.session.commit()

                if os.getenv("AUTO_REPLY_INSTAGRAM", "0") == "1":
                    reply = p._reply_for_instagram(lead)
                    if reply:
                        ok, detail = sc._send_instagram(sender_id, reply, account["token"])
                        if ok:
                            crm.db.session.add(crm.Interaction(
                                lead_id=lead.id,
                                channel="Instagram",
                                direction="out",
                                message=reply,
                                ai_generated=False,
                            ))
                            crm.db.session.commit()
                        else:
                            crm.app.logger.warning(
                                "Instagram resposta falhou lead=%s conta=%s: %s",
                                lead.id, account["label"], detail,
                            )
                            crm.db.session.rollback()
    except Exception as exc:
        crm.app.logger.exception("Instagram webhook hotfix: %s", exc)
        crm.db.session.rollback()

    return "ok", 200


if "instagram_webhook" in crm.app.view_functions:
    crm.app.view_functions["instagram_webhook"] = instagram_webhook_hotfix
