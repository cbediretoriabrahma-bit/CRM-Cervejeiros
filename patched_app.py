import os
import re
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
    """Salva cada resposta no cadastro e requalifica o lead/pipeline automaticamente."""
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel="WhatsApp", direction="in"
    ).count()

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

    # Recalcula score, temperatura e etapa a cada resposta.
    crm.requalify(lead, preserve=False)

    # Ao informar dia + horário e aceitar reunião, move para Reunião Agendada.
    if inbound_count >= 9 and lead.meeting_interest == "Sim":
        lead.stage = "Reunião Agendada"

    crm.db.session.add(
        crm.AutomationLog(
            lead_id=lead.id,
            action="Pipeline atualizado pelo WhatsApp",
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


crm.app.view_functions["whatsapp_webhook"] = whatsapp_webhook
app = crm.app
