import os
import re
import json
import urllib.request
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


def _reply_for_instagram(lead):
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel="Instagram", direction="in"
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


def _parse_investment(text):
    cleaned = (text or "").lower().replace("r$", "").replace(" ", "")
    mult = 1
    if "mil" in cleaned or cleaned.endswith("k"):
        mult = 1000
    nums = re.findall(r"\d+[\d\.,]*", cleaned)
    if not nums:
        return 0
    raw = nums[0]
    if mult == 1000:
        raw = raw.replace(".", "").replace(",", ".")
        try:
            return float(raw) * 1000
        except Exception:
            return 0
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0


def _parse_timeframe(text):
    t = (text or "").lower()
    if any(x in t for x in ["imediato", "imediatamente", "agora", "já", "ja"]):
        return "Imediato"
    if "30" in t or "1 mês" in t or "1 mes" in t:
        return "Até 30 dias"
    if any(x in t for x in ["1 a 3", "2 meses", "3 meses"]):
        return "1 a 3 meses"
    if any(x in t for x in ["3 a 6", "4 meses", "5 meses", "6 meses"]):
        return "3 a 6 meses"
    if any(x in t for x in ["mais de 6", "7 meses", "8 meses", "9 meses", "10 meses", "11 meses", "1 ano"]):
        return "Mais de 6 meses"
    return "Sem prazo"


def _yes_no(text):
    t = (text or "").strip().lower()
    if any(x in t for x in ["sim", "sou", "tenho", "já", "ja", "quero", "tenho interesse", "claro"]):
        return "Sim"
    if any(x in t for x in ["não", "nao", "nunca", "primeiro negócio", "primeiro negocio", "não tenho", "nao tenho"]):
        return "Não"
    return "Talvez"


def _append_note(lead, line):
    current = (lead.notes or "").strip()
    lead.notes = (current + ("\n" if current else "") + line).strip()


def _apply_answer_to_lead(lead, text):
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel="WhatsApp", direction="in"
    ).count()
    _apply_answer_by_count(lead, text, inbound_count, "WhatsApp")


def _apply_answer_by_count(lead, text, inbound_count, channel):
    if inbound_count == 2:
        lead.city = text.strip()[:120]
    elif inbound_count == 3:
        lead.state = text.strip().upper()[:40]
    elif inbound_count == 4:
        value = _parse_investment(text)
        if value > 0:
            lead.investment = value
    elif inbound_count == 5:
        lead.timeframe = _parse_timeframe(text)
    elif inbound_count == 6:
        lead.entrepreneur = _yes_no(text)
    elif inbound_count == 7:
        lead.meeting_interest = _yes_no(text)
    elif inbound_count == 8:
        _append_note(lead, f"Dia sugerido para reunião: {text.strip()}")
    elif inbound_count == 9:
        _append_note(lead, f"Horário sugerido para reunião: {text.strip()}")

    crm.requalify(lead, preserve=False)
    if inbound_count >= 9 and lead.meeting_interest == "Sim":
        lead.stage = "Reunião Agendada"

    crm.db.session.add(
        crm.AutomationLog(
            lead_id=lead.id,
            action=f"Pipeline atualizado pelo {channel}",
            detail=f"Resposta {inbound_count}; score {lead.score}; etapa {lead.stage}",
        )
    )


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
            crm.db.session.flush()
            _apply_answer_to_lead(lead, text)

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
                "WhatsApp salvo: lead_id=%s criado=%s telefone=%s etapa=%s score=%s message_id=%s owner_id=%s",
                lead.id, created, crm.normalize_phone(phone), lead.stage, lead.score, message_id, lead.owner_id
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


# ---------------- Instagram Direct ----------------

def _instagram_lead_key(sender_id):
    return f"IG-{sender_id}"


def _find_instagram_lead(sender_id):
    return crm.Lead.query.filter_by(phone=_instagram_lead_key(sender_id), source="Instagram").order_by(crm.Lead.id.desc()).first()


def _instagram_interest_message(text):
    # Mantida apenas por compatibilidade. Toda mensagem nova do Direct agora é tratada como lead.
    return bool((text or "").strip())


def _instagram_already_processed(message_id):
    if not message_id:
        return False
    return crm.AutomationLog.query.filter_by(
        action="Instagram message processada", detail=message_id
    ).first() is not None


def _instagram_recent_duplicate(lead, text):
    if not lead or not text:
        return False
    cutoff = datetime.utcnow() - timedelta(seconds=20)
    return crm.Interaction.query.filter(
        crm.Interaction.lead_id == lead.id,
        crm.Interaction.channel == "Instagram",
        crm.Interaction.direction == "in",
        crm.Interaction.message == text,
        crm.Interaction.created_at >= cutoff,
    ).first() is not None


def _instagram_profile_name(sender_id):
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        return ""
    try:
        url = f"https://graph.instagram.com/v23.0/{sender_id}?fields=name,username&access_token={token}"
        with urllib.request.urlopen(url, timeout=12) as response:
            data = json.loads(response.read().decode())
        return (data.get("name") or data.get("username") or "").strip()
    except Exception:
        return ""


def send_instagram_message(recipient_id, message):
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.getenv("INSTAGRAM_USER_ID")
    if not token or not ig_user_id:
        return False, "Instagram API não configurada."

    url = f"https://graph.instagram.com/v23.0/{ig_user_id}/messages"
    payload = json.dumps({
        "recipient": {"id": str(recipient_id)},
        "message": {"text": message}
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


def instagram_webhook():
    if request.method == "GET":
        verify_token = os.getenv("INSTAGRAM_VERIFY_TOKEN") or os.getenv("WHATSAPP_VERIFY_TOKEN")
        if request.args.get("hub.verify_token") == verify_token:
            return request.args.get("hub.challenge", ""), 200
        return "verification failed", 403

    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = str((event.get("sender") or {}).get("id") or "")
                message = event.get("message") or {}
                message_id = str(message.get("mid") or "")
                text = str(message.get("text") or "").strip()

                if not sender_id or not text or message.get("is_echo"):
                    continue
                if _instagram_already_processed(message_id):
                    crm.app.logger.warning("Instagram duplicado ignorado: %s", message_id)
                    continue

                lead = _find_instagram_lead(sender_id)

                if lead and _instagram_recent_duplicate(lead, text):
                    crm.app.logger.warning("Instagram repetido ignorado para lead=%s", lead.id)
                    continue

                created = False
                if not lead:
                    created = True
                    profile_name = _instagram_profile_name(sender_id)
                    lead = crm.Lead(
                        name=profile_name or f"Instagram {sender_id[-4:]}",
                        phone=_instagram_lead_key(sender_id),
                        source="Instagram",
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
                            action="Lead criado pelo Instagram",
                            detail="Nova mensagem recebida automaticamente pelo Direct do Instagram.",
                        )
                    )

                crm.db.session.add(
                    crm.Interaction(
                        lead_id=lead.id,
                        channel="Instagram",
                        direction="in",
                        message=text,
                    )
                )
                lead.last_contact = datetime.utcnow()
                crm.db.session.flush()

                inbound_count = crm.Interaction.query.filter_by(
                    lead_id=lead.id, channel="Instagram", direction="in"
                ).count()
                _apply_answer_by_count(lead, text, inbound_count, "Instagram")

                if message_id:
                    crm.db.session.add(
                        crm.AutomationLog(
                            lead_id=lead.id,
                            action="Instagram message processada",
                            detail=message_id,
                        )
                    )

                crm.db.session.commit()
                crm.app.logger.warning(
                    "Instagram salvo: lead_id=%s criado=%s sender=%s etapa=%s score=%s",
                    lead.id, created, sender_id, lead.stage, lead.score
                )

                if os.getenv("AUTO_REPLY_INSTAGRAM", "0") == "1":
                    reply = _reply_for_instagram(lead)
                    if not reply:
                        crm.app.logger.warning("Fluxo Instagram encerrado para lead=%s", lead.id)
                        continue
                    ok, detail = send_instagram_message(sender_id, reply)
                    if ok:
                        crm.db.session.add(
                            crm.Interaction(
                                lead_id=lead.id,
                                channel="Instagram",
                                direction="out",
                                message=reply,
                                ai_generated=False,
                            )
                        )
                        crm.db.session.commit()
                    else:
                        crm.app.logger.warning("Falha ao responder Instagram lead=%s: %s", lead.id, detail)
                        crm.db.session.rollback()

    except Exception as exc:
        crm.app.logger.warning("Webhook Instagram: %s", exc)
        crm.db.session.rollback()

    return "ok", 200


crm.app.view_functions["whatsapp_webhook"] = whatsapp_webhook
crm.app.add_url_rule(
    "/webhooks/instagram",
    endpoint="instagram_webhook",
    view_func=instagram_webhook,
    methods=["GET", "POST"],
)
app = crm.app