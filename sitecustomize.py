"""Patch de inicialização para suportar duas contas/páginas no Direct do CRM.

É carregado automaticamente pelo Python no boot. Importa o app já existente e
substitui somente o handler do Instagram, preservando o WhatsApp e o restante do CRM.
"""
import os
import json
import urllib.request
from datetime import datetime
from flask import request

try:
    import patched_app as p
except Exception:
    p = None

if p is not None:
    crm = p.crm

    DEFAULT_GELADEIRA_PAGE_ID = "864918166704951"
    DEFAULT_CERVEJEIROS_PAGE_ID = "305196089351151"

    def _account_config(page_id):
        page_id = str(page_id or "")
        geladeira_id = os.getenv("INSTAGRAM_PAGE_ID_GELADEIRA", DEFAULT_GELADEIRA_PAGE_ID)
        cervejeiros_id = os.getenv("INSTAGRAM_PAGE_ID_CERVEJEIROS", DEFAULT_CERVEJEIROS_PAGE_ID)

        if page_id == geladeira_id:
            return {
                "label": "Geladeira Autosserviço Cervejeiros",
                "page_id": geladeira_id,
                "token": os.getenv("INSTAGRAM_ACCESS_TOKEN_GELADEIRA") or os.getenv("INSTAGRAM_ACCESS_TOKEN"),
            }
        if page_id == cervejeiros_id:
            return {
                "label": "Cervejeiros",
                "page_id": cervejeiros_id,
                "token": os.getenv("INSTAGRAM_ACCESS_TOKEN_CERVEJEIROS") or os.getenv("INSTAGRAM_ACCESS_TOKEN"),
            }

        # Fallback para instalações antigas com uma única conta.
        return {
            "label": "Instagram",
            "page_id": page_id,
            "token": os.getenv("INSTAGRAM_ACCESS_TOKEN"),
        }

    def _lead_key(page_id, sender_id):
        return f"IG-{page_id}-{sender_id}"

    def _find_lead(page_id, sender_id):
        key = _lead_key(page_id, sender_id)
        lead = crm.Lead.query.filter_by(phone=key, source="Instagram").order_by(crm.Lead.id.desc()).first()
        if lead:
            return lead
        # Compatibilidade com lead criado antes do suporte a duas contas.
        old_key = f"IG-{sender_id}"
        return crm.Lead.query.filter_by(phone=old_key, source="Instagram").order_by(crm.Lead.id.desc()).first()

    def _profile_name(sender_id, token):
        if not token:
            return ""
        try:
            url = f"https://graph.facebook.com/v23.0/{sender_id}?fields=name,username&access_token={token}"
            with urllib.request.urlopen(url, timeout=12) as response:
                data = json.loads(response.read().decode())
            return (data.get("name") or data.get("username") or "").strip()
        except Exception:
            return ""

    def _send_instagram(recipient_id, message, token):
        if not token:
            return False, "Token da conta do Instagram não configurado."
        url = "https://graph.facebook.com/v23.0/me/messages"
        payload = json.dumps({
            "recipient": {"id": str(recipient_id)},
            "messaging_type": "RESPONSE",
            "message": {"text": message},
        }).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return True, response.read().decode()
        except Exception as exc:
            return False, str(exc)

    def instagram_webhook_multi():
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
                    recipient_id = str((event.get("recipient") or {}).get("id") or "")
                    page_id = entry_id or recipient_id
                    account = _account_config(page_id)
                    sender_id = str((event.get("sender") or {}).get("id") or "")
                    message = event.get("message") or {}
                    message_id = str(message.get("mid") or "")
                    text = str(message.get("text") or "").strip()

                    if not sender_id or not text or message.get("is_echo"):
                        continue
                    if p._instagram_already_processed(message_id):
                        crm.app.logger.warning("Instagram duplicado ignorado: %s", message_id)
                        continue

                    lead = _find_lead(page_id, sender_id)
                    if lead and p._instagram_recent_duplicate(lead, text):
                        crm.app.logger.warning("Instagram repetido ignorado para lead=%s", lead.id)
                        continue

                    created = False
                    if not lead:
                        created = True
                        profile_name = _profile_name(sender_id, account["token"])
                        lead = crm.Lead(
                            name=profile_name or f"Instagram {sender_id[-4:]}",
                            phone=_lead_key(page_id, sender_id),
                            source="Instagram",
                            timeframe="Sem prazo",
                            stage="Novo Lead",
                            notes=f"Conta de origem: {account['label']} | Page ID: {page_id}",
                        )
                        crm.db.session.add(lead)
                        crm.db.session.flush()
                        crm.assign_round_robin(lead)
                        crm.requalify(lead, preserve=False)
                        crm.db.session.add(crm.AutomationLog(
                            lead_id=lead.id,
                            action="Lead criado pelo Instagram",
                            detail=f"Nova mensagem recebida em {account['label']} ({page_id}).",
                        ))

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
                    crm.app.logger.warning(
                        "Instagram salvo: lead_id=%s criado=%s conta=%s pagina=%s sender=%s etapa=%s score=%s",
                        lead.id, created, account["label"], page_id, sender_id, lead.stage, lead.score,
                    )

                    if os.getenv("AUTO_REPLY_INSTAGRAM", "0") == "1":
                        reply = p._reply_for_instagram(lead)
                        if not reply:
                            continue
                        ok, detail = _send_instagram(sender_id, reply, account["token"])
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
                                "Falha ao responder Instagram lead=%s conta=%s: %s",
                                lead.id, account["label"], detail,
                            )
                            crm.db.session.rollback()
        except Exception as exc:
            crm.app.logger.warning("Webhook Instagram multi-conta: %s", exc)
            crm.db.session.rollback()

        return "ok", 200

    # patched_app já registra a URL; trocamos apenas a função ligada ao endpoint.
    if "instagram_webhook" in crm.app.view_functions:
        crm.app.view_functions["instagram_webhook"] = instagram_webhook_multi