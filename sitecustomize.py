"""Patch de inicialização para suportar duas contas/páginas no Direct do CRM.

É carregado automaticamente pelo Python no boot. Importa o app já existente e
substitui somente o handler do Instagram, preservando o WhatsApp e o restante do CRM.
"""
import os
import re
import json
import urllib.request
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
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

    if "instagram_webhook" in crm.app.view_functions:
        crm.app.view_functions["instagram_webhook"] = instagram_webhook_multi

    TZ = ZoneInfo("America/Sao_Paulo")

    if "Prioridade / Reunião" not in crm.PIPELINE:
        try:
            idx = crm.PIPELINE.index("Reunião Agendada")
        except ValueError:
            idx = len(crm.PIPELINE)
        crm.PIPELINE.insert(idx, "Prioridade / Reunião")

    crm.TIMEFRAMES = ["Imediatamente", "Em até 30 dias", "Em até 60 dias", "Acima de 60 dias"]

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

    def _parse_timeframe_final(text):
        t = (text or "").strip().lower()
        if t.startswith("1") or any(x in t for x in ["imediatamente", "imediato", "agora", "hoje", "já", "ja"]):
            return "Imediatamente"
        if t.startswith("2") or "30" in t or "1 mês" in t or "1 mes" in t:
            return "Em até 30 dias"
        if t.startswith("3") or "60" in t or "2 meses" in t or "2 mes" in t:
            return "Em até 60 dias"
        return "Acima de 60 dias"

    def _score_final(lead):
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
        elif investment >= 18900:
            score += 10
        if lead.timeframe == "Imediatamente":
            score += 15
        elif lead.timeframe == "Em até 30 dias":
            score += 10
        elif lead.timeframe == "Em até 60 dias":
            score += 5
        objective = _tag_value(lead, "Q_OBJECTIVE")
        score += {"expandir": 5, "avaliar": 3, "renda_complementar": 1}.get(objective, 0)
        if lead.meeting_interest == "Sim":
            score += 5
        return min(score, 100)

    def _temperature_final(score):
        if score >= 60:
            return "Quente"
        if score >= 20:
            return "Morno"
        return "Frio"

    def _auto_stage_final(lead, preserve=True):
        if preserve and lead.stage in {"Prioridade / Reunião", "Reunião Agendada", "Proposta Enviada", "Negociação", "Fechado", "Perdido"}:
            return lead.stage
        if lead.meeting_interest == "Sim":
            return "Prioridade / Reunião"
        if lead.score >= 80:
            return "Prioridade / Reunião"
        if lead.score >= 60:
            return "Qualificado"
        if lead.score >= 20:
            return "Em Qualificação"
        return "Novo Lead"

    crm.score_lead = _score_final
    crm.temperature = _temperature_final
    crm.auto_stage = _auto_stage_final
    p._score_lead = _score_final
    p._temperature = _temperature_final
    p._auto_stage = _auto_stage_final

    def _meeting_hours():
        return [time(hour, 0) for hour in range(9, 20)]

    def _slot_is_free(local_dt, owner_id):
        utc_naive = local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        start = utc_naive
        end = utc_naive + timedelta(hours=1)
        query = crm.Task.query.filter(
            crm.Task.task_type == "Reunião",
            crm.Task.status == "Pendente",
            crm.Task.due_at >= start,
            crm.Task.due_at < end,
        )
        if owner_id is None:
            query = query.filter(crm.Task.owner_id.is_(None))
        else:
            query = query.filter(crm.Task.owner_id == owner_id)
        return query.first() is None

    def _meeting_options(lead, refresh=False):
        stored = []
        if not refresh:
            for i in range(1, 4):
                raw = _tag_value(lead, f"Q_SLOT_{i}")
                if raw:
                    try:
                        stored.append(datetime.fromisoformat(raw))
                    except Exception:
                        stored = []
                        break
            if len(stored) == 3:
                return stored

        now = datetime.now(TZ)
        options = []
        for add_day in range(0, 15):
            day = (now + timedelta(days=add_day)).date()
            if day.weekday() >= 5:
                continue
            for hr in _meeting_hours():
                slot = datetime.combine(day, hr, tzinfo=TZ)
                if slot <= now + timedelta(hours=2):
                    continue
                if _slot_is_free(slot, lead.owner_id):
                    options.append(slot)
                if len(options) == 3:
                    break
            if len(options) == 3:
                break

        for i, slot in enumerate(options, 1):
            _set_tag(lead, f"Q_SLOT_{i}", slot.isoformat())
        return options

    def _format_slot(slot):
        weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        return f"{weekdays[slot.weekday()]}, {slot.strftime('%d/%m')} às {slot.strftime('%H:%M')}"

    def _schedule_choice(lead, text):
        match = re.search(r"\b([123])\b", (text or "").strip())
        if not match:
            return False
        choice = int(match.group(1))
        options = _meeting_options(lead)
        if len(options) < choice:
            return False
        slot = options[choice - 1]
        if not _slot_is_free(slot, lead.owner_id):
            _meeting_options(lead, refresh=True)
            return False
        utc_naive = slot.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        crm.db.session.add(crm.Task(
            lead_id=lead.id,
            owner_id=lead.owner_id,
            title=f"Reunião com {lead.name}",
            task_type="Reunião",
            due_at=utc_naive,
            status="Pendente",
            notes=f"Reunião comercial de 1 hora agendada automaticamente para {_format_slot(slot)}.",
        ))
        lead.next_followup = utc_naive
        lead.stage = "Reunião Agendada"
        _set_tag(lead, "Q_MEETING_SLOT", slot.isoformat())
        _set_tag(lead, "Q_MEETING_CHOICE", choice)
        current = (lead.notes or "").strip()
        line = f"Reunião agendada: {_format_slot(slot)} | duração: 1 hora"
        lead.notes = current + ("\n" if current else "") + line
        return True

    def _qualification_reply_final(lead, channel):
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel=channel, direction="in"
        ).count()
        first = (lead.name or "Olá").split()[0]
        if inbound_count <= 1:
            return f"Olá, {first}! 🍻 Obrigado pelo interesse na Cervejeiros. Em qual cidade você pretende operar?"
        if inbound_count == 2:
            return f"Perfeito, {first}! Em qual estado fica essa cidade?"
        if inbound_count == 3:
            return ("Você já possui contato ou acesso a condomínios, clubes ou locais de grande circulação? "
                    "1) Já tenho locais em vista  2) Tenho alguns contatos  3) Ainda vou começar a prospectar")
        if inbound_count == 4:
            return "Quantos condomínios ou clubes você acredita conseguir prospectar? 1) 1 a 4  2) 5 a 9  3) 10 ou mais"
        if inbound_count == 5:
            return "Com quantas geladeiras você pretende começar? 1) 1 geladeira  2) 2 geladeiras  3) 3 ou mais"
        if inbound_count == 6:
            return ("Qual faixa de investimento você tem disponível para iniciar? "
                    "1) R$ 18.900 a R$ 29.999  2) R$ 30.000 a R$ 44.999  3) R$ 45.000 a R$ 55.000")
        if inbound_count == 7:
            return ("Em quanto tempo você pretende iniciar a prospecção de condomínios e clubes? "
                    "1) Imediatamente  2) Em até 30 dias  3) Em até 60 dias  4) Acima de 60 dias / estou apenas pesquisando")
        if inbound_count == 8:
            return ("Qual é o seu objetivo com o negócio? "
                    "1) Expandir para várias geladeiras  2) Começar e depois avaliar  3) Renda complementar")
        if inbound_count == 9:
            return "Se o modelo fizer sentido para você, gostaria de falar com um consultor para conhecer os planos e valores?"
        if inbound_count == 10:
            if lead.meeting_interest == "Sim":
                options = _meeting_options(lead, refresh=True)
                if len(options) >= 3:
                    crm.db.session.commit()
                    return (f"Perfeito, {first}! Tenho estes 3 horários disponíveis com seu consultor:\n"
                            f"1) {_format_slot(options[0])}\n"
                            f"2) {_format_slot(options[1])}\n"
                            f"3) {_format_slot(options[2])}\n"
                            "Cada reunião dura 1 hora. Responda somente 1, 2 ou 3 para reservar.")
                return "Perfeito! Nosso consultor vai entrar em contato para combinar o melhor horário."
            if lead.meeting_interest == "Talvez":
                return "Sem problema. Vamos manter seu perfil em acompanhamento e você pode avançar quando desejar. 🍻"
            return "Tudo certo. Seu contato continuará cadastrado e estaremos à disposição quando quiser avançar. 🍻"
        if inbound_count == 11 and lead.meeting_interest == "Sim":
            selected = _tag_value(lead, "Q_MEETING_SLOT")
            if selected:
                try:
                    slot = datetime.fromisoformat(selected)
                    return f"✅ Reunião confirmada para {_format_slot(slot)}. Duração: 1 hora. Nosso consultor falará com você no horário agendado. 🍻"
                except Exception:
                    pass
            options = _meeting_options(lead, refresh=True)
            crm.db.session.commit()
            if len(options) >= 3:
                return ("Esse horário não está mais disponível. Escolha uma destas novas opções:\n"
                        f"1) {_format_slot(options[0])}\n"
                        f"2) {_format_slot(options[1])}\n"
                        f"3) {_format_slot(options[2])}")
        return None

    def _apply_answer_final(lead, text, inbound_count, channel):
        if inbound_count == 2:
            lead.city = text.strip()[:120]
        elif inbound_count == 3:
            lead.state = text.strip().upper()[:40]
        elif inbound_count == 4:
            p._set_tag(lead, "Q_ACCESS", p._parse_access(text))
        elif inbound_count == 5:
            t = (text or "").strip().lower()
            if t.startswith("1"):
                p._set_tag(lead, "Q_PROSPECTS", 4)
            elif t.startswith("2"):
                p._set_tag(lead, "Q_PROSPECTS", 9)
            elif t.startswith("3"):
                p._set_tag(lead, "Q_PROSPECTS", 10)
            else:
                p._set_tag(lead, "Q_PROSPECTS", p._parse_prospects(text))
        elif inbound_count == 6:
            t = (text or "").strip().lower()
            if t.startswith("1"):
                p._set_tag(lead, "Q_FRIDGES", 1)
            elif t.startswith("2"):
                p._set_tag(lead, "Q_FRIDGES", 2)
            else:
                p._set_tag(lead, "Q_FRIDGES", 3)
        elif inbound_count == 7:
            t = (text or "").strip().lower()
            if t.startswith("1"):
                lead.investment = 18900
            elif t.startswith("2"):
                lead.investment = 30000
            elif t.startswith("3"):
                lead.investment = 45000
            else:
                value = p._parse_investment(text)
                if value > 0:
                    lead.investment = value
        elif inbound_count == 8:
            lead.timeframe = _parse_timeframe_final(text)
        elif inbound_count == 9:
            p._set_tag(lead, "Q_OBJECTIVE", p._parse_objective(text))
        elif inbound_count == 10:
            lead.meeting_interest = p._yes_no(text)
        elif inbound_count == 11 and lead.meeting_interest == "Sim":
            _schedule_choice(lead, text)

        crm.requalify(lead, preserve=False)
        if lead.meeting_interest == "Sim" and lead.stage != "Reunião Agendada":
            lead.stage = "Prioridade / Reunião"
        if _tag_value(lead, "Q_MEETING_SLOT"):
            lead.stage = "Reunião Agendada"

        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action=f"Pipeline atualizado pelo {channel}",
            detail=f"Resposta {inbound_count}; score {lead.score}; etapa {lead.stage}",
        ))

    p._qualification_reply = _qualification_reply_final
    p._reply_for_message = lambda lead, text: _qualification_reply_final(lead, "WhatsApp")
    p._reply_for_instagram = lambda lead: _qualification_reply_final(lead, "Instagram")
    p._apply_answer_by_count = _apply_answer_final

    def _apply_answer_to_lead_final(lead, text):
        inbound_count = crm.Interaction.query.filter_by(
            lead_id=lead.id, channel="WhatsApp", direction="in"
        ).count()
        _apply_answer_final(lead, text, inbound_count, "WhatsApp")

    p._apply_answer_to_lead = _apply_answer_to_lead_final