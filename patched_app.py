import os
import re
import json
import urllib.request
from datetime import datetime, timedelta
from flask import request

import app as crm

# Fluxo oficial de qualificação Cervejeiros:
# 1 cidade, 2 estado, 3 acesso a condomínios/clubes, 4 quantidade a prospectar,
# 5 número de geladeiras, 6 investimento, 7 início da prospecção,
# 8 objetivo, 9 reunião, 10 dia, 11 horário.


def _find_lead_by_phone(phone):
    target = crm.normalize_phone(phone)
    if not target:
        return None
    for lead in crm.Lead.query.order_by(crm.Lead.id.desc()).all():
        if crm.normalize_phone(lead.phone) == target:
            return lead
    return None


def _tag_value(lead, key):
    notes = lead.notes or ""
    match = re.search(rf"^\[{re.escape(key)}\]=(.*)$", notes, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _set_tag(lead, key, value):
    value = str(value).strip()
    notes = lead.notes or ""
    pattern = rf"^\[{re.escape(key)}\]=.*$"
    line = f"[{key}]={value}"
    if re.search(pattern, notes, flags=re.MULTILINE):
        notes = re.sub(pattern, line, notes, flags=re.MULTILINE)
    else:
        notes = (notes.strip() + ("\n" if notes.strip() else "") + line).strip()
    lead.notes = notes


def _append_note(lead, line):
    current = (lead.notes or "").strip()
    lead.notes = (current + ("\n" if current else "") + line).strip()


def _parse_investment(text):
    cleaned = (text or "").lower().replace("r$", "").replace(" ", "")
    mult = 1000 if ("mil" in cleaned or cleaned.endswith("k")) else 1
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
    t = (text or "").strip().lower()
    if any(x in t for x in ["imediato", "imediatamente", "agora", "já", "ja", "hoje"]):
        return "Até 30 dias"
    if "30" in t or "1 mês" in t or "1 mes" in t:
        return "Até 30 dias"
    if any(x in t for x in ["31", "45", "60", "2 meses", "2 mes"]):
        return "31 a 60 dias"
    if any(x in t for x in ["61", "75", "90", "3 meses", "3 mes"]):
        return "61 a 90 dias"
    if any(x in t for x in ["mais de 90", "acima de 90", "4 meses", "5 meses", "6 meses", "sem prazo", "pesquisando"]):
        return "Mais de 90 dias"
    return "Sem prazo"


def _yes_no(text):
    t = (text or "").strip().lower()
    if any(x in t for x in ["sim", "quero", "tenho interesse", "claro", "pode", "vamos"]):
        return "Sim"
    if any(x in t for x in ["não", "nao", "agora não", "agora nao"]):
        return "Não"
    return "Talvez"


def _parse_access(text):
    t = (text or "").lower()
    if t.strip().startswith("1") or any(x in t for x in ["já tenho local", "ja tenho local", "locais em vista", "condomínio interessado", "condominio interessado", "clube interessado"]):
        return "locais_em_vista"
    if t.strip().startswith("2") or any(x in t for x in ["alguns contatos", "tenho contatos", "algum contato"]):
        return "alguns_contatos"
    return "vai_prospectar"


def _parse_prospects(text):
    nums = re.findall(r"\d+", text or "")
    if not nums:
        return 0
    n = max(int(x) for x in nums)
    return n


def _parse_fridges(text):
    nums = re.findall(r"\d+", text or "")
    if nums:
        return max(1, int(nums[0]))
    t = (text or "").lower()
    if "três" in t or "tres" in t:
        return 3
    if "duas" in t or "dois" in t:
        return 2
    return 1


def _parse_objective(text):
    t = (text or "").lower()
    if t.strip().startswith("1") or any(x in t for x in ["expandir", "várias", "varias", "crescer", "escala"]):
        return "expandir"
    if t.strip().startswith("2") or any(x in t for x in ["avaliar", "começar e depois", "comecar e depois"]):
        return "avaliar"
    return "renda_complementar"


def _score_lead(lead):
    score = 0

    if lead.city and lead.state:
        score += 5

    access = _tag_value(lead, "Q_ACCESS")
    score += {"locais_em_vista": 20, "alguns_contatos": 12, "vai_prospectar": 5}.get(access, 0)

    try:
        prospects = int(_tag_value(lead, "Q_PROSPECTS") or 0)
    except Exception:
        prospects = 0
    if prospects >= 10:
        score += 15
    elif prospects >= 5:
        score += 10
    elif prospects >= 1:
        score += 5

    try:
        fridges = int(_tag_value(lead, "Q_FRIDGES") or 0)
    except Exception:
        fridges = 0
    if fridges >= 3:
        score += 15
    elif fridges == 2:
        score += 10
    elif fridges == 1:
        score += 5

    investment = lead.investment or 0
    if investment >= 45000:
        score += 20
    elif investment >= 30000:
        score += 15
    elif investment >= 19500:
        score += 10

    if lead.timeframe == "Até 30 dias":
        score += 15
    elif lead.timeframe == "31 a 60 dias":
        score += 10
    elif lead.timeframe == "61 a 90 dias":
        score += 5

    objective = _tag_value(lead, "Q_OBJECTIVE")
    score += {"expandir": 5, "avaliar": 3, "renda_complementar": 1}.get(objective, 0)

    if lead.meeting_interest == "Sim":
        score += 5
    elif lead.meeting_interest == "Talvez":
        score += 2

    return min(score, 100)


def _is_priority(lead):
    return (
        _tag_value(lead, "Q_ACCESS") == "locais_em_vista"
        and (lead.investment or 0) >= 19500
        and lead.timeframe == "Até 30 dias"
    )


def _temperature(score):
    if score >= 50:
        return "Quente"
    if score >= 30:
        return "Morno"
    return "Frio"


def _auto_stage(lead, preserve=True):
    if preserve and lead.stage in {"Reunião Agendada", "Proposta Enviada", "Negociação", "Fechado", "Perdido"}:
        return lead.stage
    if _is_priority(lead) or lead.score >= 70:
        return "Qualificado"
    if lead.score >= 30:
        return "Em Qualificação"
    return "Novo Lead"


# Aplica as regras novas também quando o CRM requalifica o lead fora do webhook.
crm.score_lead = _score_lead
crm.temperature = _temperature
crm.auto_stage = _auto_stage
crm.TIMEFRAMES = ["Até 30 dias", "31 a 60 dias", "61 a 90 dias", "Mais de 90 dias", "Sem prazo"]


def _qualification_reply(lead, channel):
    inbound_count = crm.Interaction.query.filter_by(
        lead_id=lead.id, channel=channel, direction="in"
    ).count()
    first = (lead.name or "Olá").split()[0]

    if inbound_count <= 1:
        return f"Olá, {first}! 🍻 Obrigado pelo interesse na Cervejeiros. Em qual cidade você pretende operar com as geladeiras de autoatendimento de chopp?"
    if inbound_count == 2:
        return f"Perfeito, {first}! Em qual estado fica essa cidade?"
    if inbound_count == 3:
        return (f"Ótimo, {first}. Você já tem acesso ou contato com condomínios, clubes ou locais de grande circulação? "
                "Responda: 1) Já tenho locais em vista  2) Tenho alguns contatos  3) Ainda vou começar a prospectar")
    if inbound_count == 4:
        return (f"Certo, {first}. Quantos condomínios ou clubes você acredita que consegue prospectar nos próximos 30 dias? "
                "Pode responder com um número aproximado.")
    if inbound_count == 5:
        return f"Com quantas geladeiras de autoatendimento você pretende começar: 1, 2 ou 3 ou mais?"
    if inbound_count == 6:
        return ("Qual faixa de investimento você tem disponível para iniciar? "
                "O investimento mínimo considerado para o projeto é de R$ 19.500.")
    if inbound_count == 7:
        return ("Em quanto tempo você pretende começar a prospectar condomínios e clubes? "
                "1) Até 30 dias  2) 31 a 60 dias  3) 61 a 90 dias  4) Mais de 90 dias")
    if inbound_count == 8:
        return ("Qual é o seu principal objetivo com o negócio? "
                "1) Expandir para várias geladeiras  2) Começar e depois avaliar a expansão  3) Ter uma renda complementar")
    if inbound_count == 9:
        return "Se o modelo fizer sentido para você, tem disponibilidade para uma reunião rápida com nosso consultor?"
    if inbound_count == 10:
        if lead.meeting_interest == "Sim":
            return f"Excelente, {first}! Qual dia funciona melhor para você?"
        if lead.meeting_interest == "Talvez":
            return f"Sem problema, {first}. Posso deixar seu perfil em acompanhamento e nossa equipe fala com você no momento mais adequado. 🍻"
        return f"Tudo certo, {first}. Vamos manter seu contato cadastrado e você pode falar conosco quando quiser avançar. 🍻"
    if inbound_count == 11 and lead.meeting_interest == "Sim":
        return f"Perfeito, {first}. Qual horário funciona melhor para você nesse dia?"
    if inbound_count == 12 and lead.meeting_interest == "Sim":
        return f"Perfeito, {first}! Recebi seu dia e horário. Nossa equipe vai confirmar a reunião com você por aqui. 🍻"
    return None


def _reply_for_message(lead, text):
    return _qualification_reply(lead, "WhatsApp")


def _reply_for_instagram(lead):
    return _qualification_reply(lead, "Instagram")


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
        _set_tag(lead, "Q_ACCESS", _parse_access(text))
    elif inbound_count == 5:
        _set_tag(lead, "Q_PROSPECTS", _parse_prospects(text))
    elif inbound_count == 6:
        _set_tag(lead, "Q_FRIDGES", _parse_fridges(text))
    elif inbound_count == 7:
        value = _parse_investment(text)
        if value > 0:
            lead.investment = value
    elif inbound_count == 8:
        t = (text or "").strip().lower()
        if t.startswith("1"):
            lead.timeframe = "Até 30 dias"
        elif t.startswith("2"):
            lead.timeframe = "31 a 60 dias"
        elif t.startswith("3"):
            lead.timeframe = "61 a 90 dias"
        elif t.startswith("4"):
            lead.timeframe = "Mais de 90 dias"
        else:
            lead.timeframe = _parse_timeframe(text)
    elif inbound_count == 9:
        _set_tag(lead, "Q_OBJECTIVE", _parse_objective(text))
    elif inbound_count == 10:
        lead.meeting_interest = _yes_no(text)
    elif inbound_count == 11 and lead.meeting_interest == "Sim":
        _set_tag(lead, "Q_MEETING_DAY", text.strip())
        _append_note(lead, f"Dia sugerido para reunião: {text.strip()}")
    elif inbound_count == 12 and lead.meeting_interest == "Sim":
        _set_tag(lead, "Q_MEETING_TIME", text.strip())
        _append_note(lead, f"Horário sugerido para reunião: {text.strip()}")

    crm.requalify(lead, preserve=False)
    if _is_priority(lead):
        lead.stage = "Qualificado"
        _set_tag(lead, "Q_PRIORITY", "Lead Prioritário")
    if inbound_count >= 12 and lead.meeting_interest == "Sim":
        lead.stage = "Reunião Agendada"

    crm.db.session.add(
        crm.AutomationLog(
            lead_id=lead.id,
            action=f"Pipeline atualizado pelo {channel}",
            detail=f"Resposta {inbound_count}; score {lead.score}; etapa {lead.stage}; prioridade={_is_priority(lead)}",
        )
    )


def _already_processed(message_id):
    if not message_id:
        return False
    return crm.AutomationLog.query.filter_by(
        action="WhatsApp message processada", detail=message_id
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
                crm.db.session.add(crm.AutomationLog(
                    lead_id=lead.id,
                    action="Lead criado pelo WhatsApp",
                    detail="Novo contato recebido automaticamente pelo webhook do WhatsApp.",
                ))

            crm.db.session.add(crm.Interaction(
                lead_id=lead.id, channel="WhatsApp", direction="in", message=text
            ))
            lead.last_contact = datetime.utcnow()
            crm.db.session.flush()
            _apply_answer_to_lead(lead, text)

            if message_id:
                crm.db.session.add(crm.AutomationLog(
                    lead_id=lead.id,
                    action="WhatsApp message processada",
                    detail=message_id,
                ))

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
                    crm.db.session.add(crm.Interaction(
                        lead_id=lead.id, channel="WhatsApp", direction="out",
                        message=reply, ai_generated=False
                    ))
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
    return crm.Lead.query.filter_by(
        phone=_instagram_lead_key(sender_id), source="Instagram"
    ).order_by(crm.Lead.id.desc()).first()


def _instagram_interest_message(text):
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
        url, data=payload,
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
                    crm.db.session.add(crm.AutomationLog(
                        lead_id=lead.id,
                        action="Lead criado pelo Instagram",
                        detail="Nova mensagem recebida automaticamente pelo Direct do Instagram.",
                    ))

                crm.db.session.add(crm.Interaction(
                    lead_id=lead.id, channel="Instagram", direction="in", message=text
                ))
                lead.last_contact = datetime.utcnow()
                crm.db.session.flush()

                inbound_count = crm.Interaction.query.filter_by(
                    lead_id=lead.id, channel="Instagram", direction="in"
                ).count()
                _apply_answer_by_count(lead, text, inbound_count, "Instagram")

                if message_id:
                    crm.db.session.add(crm.AutomationLog(
                        lead_id=lead.id,
                        action="Instagram message processada",
                        detail=message_id,
                    ))

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
                        crm.db.session.add(crm.Interaction(
                            lead_id=lead.id, channel="Instagram", direction="out",
                            message=reply, ai_generated=False
                        ))
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
