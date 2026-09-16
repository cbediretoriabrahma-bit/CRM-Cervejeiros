"""Hotfix de resposta automática do Instagram.

Garante que o webhook do Direct aceite texto e quick replies, preserve a conversa
mesmo após o lead informar o WhatsApp, aplique o mesmo fluxo do WhatsApp e envie
mensagens longas (como a apresentação comercial) em partes seguras.
"""
import json
import os
from datetime import datetime
from flask import request

import flow_media_patch as fm
import instagram_flow_fix_patch as igf
import patched_app as p
import sitecustomize as sc

crm = p.crm


def _extract_text(message):
    quick = (message or {}).get("quick_reply") or {}
    payload = str(quick.get("payload") or "").strip()
    if payload:
        return payload
    return str((message or {}).get("text") or "").strip()


def _instagram_key(page_id, sender_id):
    return sc._lead_key(page_id, sender_id)


def _restore_instagram_identity(lead, page_id, sender_id, informed_whatsapp=""):
    """Mantém a chave IG no campo phone e guarda o WhatsApp informado nas notas."""
    key = _instagram_key(page_id, sender_id)
    if informed_whatsapp:
        try:
            sc._set_tag(lead, "Q_WHATSAPP", informed_whatsapp)
        except Exception:
            pass
    try:
        sc._set_tag(lead, "Q_INSTAGRAM_KEY", key)
    except Exception:
        pass
    lead.phone = key


def _recover_previous_instagram_lead(page_id, sender_id, account, current=None):
    """Recupera conversa quebrada anteriormente quando o WhatsApp substituiu a chave IG."""
    profile_name = sc._profile_name(sender_id, account["token"])
    if not profile_name:
        return current

    query = crm.Lead.query.filter(
        crm.Lead.source == "Instagram",
        crm.Lead.name == profile_name,
        crm.Lead.notes.ilike(f"%Page ID: {page_id}%"),
    )
    if current is not None:
        query = query.filter(crm.Lead.id != current.id)

    for candidate in query.order_by(crm.Lead.id.desc()).limit(10).all():
        count = crm.Interaction.query.filter_by(
            lead_id=candidate.id, channel="Instagram", direction="in"
        ).count()
        if count >= 2:
            old_phone = candidate.phone or ""
            if old_phone and not old_phone.startswith("IG-"):
                try:
                    sc._set_tag(candidate, "Q_WHATSAPP", old_phone)
                except Exception:
                    pass
            _restore_instagram_identity(candidate, page_id, sender_id)
            return candidate
    return current


def _split_text(text, limit=900):
    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < int(limit * 0.55):
            cut = remaining.rfind("\n", 0, limit)
        if cut < int(limit * 0.55):
            cut = remaining.rfind(" ", 0, limit)
        if cut < int(limit * 0.55):
            cut = limit
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _send_instagram_safe(recipient_id, reply, token):
    """Envia apresentação longa em partes e mantém quick replies no fim."""
    if not reply:
        return False, "Resposta vazia"

    reply = igf._instagramize(reply)
    kind, data = fm._parse_marker(reply)

    if kind in {"buttons", "list"}:
        body = (data or {}).get("body", "")
        chunks = _split_text(body)
        if not chunks:
            return False, "Mensagem sem conteúdo"

        for chunk in chunks[:-1]:
            ok, detail = sc._send_instagram(recipient_id, chunk, token)
            if not ok:
                return False, detail

        final_data = dict(data or {})
        final_data["body"] = chunks[-1]
        prefix = "[[BUTTONS]]" if kind == "buttons" else "[[LIST]]"
        final_message = prefix + json.dumps(final_data, ensure_ascii=False)
        return sc._send_instagram(recipient_id, final_message, token)

    last_detail = ""
    for chunk in _split_text(reply):
        ok, last_detail = sc._send_instagram(recipient_id, chunk, token)
        if not ok:
            return False, last_detail
    return True, last_detail


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

                if lead:
                    current_count = crm.Interaction.query.filter_by(
                        lead_id=lead.id, channel="Instagram", direction="in"
                    ).count()
                    if current_count <= 1:
                        recovered = _recover_previous_instagram_lead(
                            page_id, sender_id, account, current=lead
                        )
                        if recovered is not None:
                            lead = recovered
                else:
                    recovered = _recover_previous_instagram_lead(
                        page_id, sender_id, account, current=None
                    )
                    if recovered is not None:
                        lead = recovered

                if not lead:
                    profile_name = sc._profile_name(sender_id, account["token"])
                    lead = crm.Lead(
                        name=profile_name or f"Instagram {sender_id[-4:]}",
                        phone=_instagram_key(page_id, sender_id),
                        source="Instagram",
                        timeframe="Sem prazo",
                        stage="Novo Lead",
                        notes=f"Conta de origem: {account['label']} | Page ID: {page_id}",
                    )
                    crm.db.session.add(lead)
                    crm.db.session.flush()
                    _restore_instagram_identity(lead, page_id, sender_id)
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

                informed_whatsapp = text if inbound_count == 3 else ""
                p._apply_answer_by_count(lead, text, inbound_count, "Instagram")
                _restore_instagram_identity(
                    lead, page_id, sender_id, informed_whatsapp=informed_whatsapp
                )

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
                        ok, detail = _send_instagram_safe(sender_id, reply, account["token"])
                        if ok:
                            log_message = reply
                            kind, parsed = fm._parse_marker(reply)
                            if kind:
                                log_message = (parsed or {}).get("body", reply)
                            crm.db.session.add(crm.Interaction(
                                lead_id=lead.id,
                                channel="Instagram",
                                direction="out",
                                message=log_message,
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
