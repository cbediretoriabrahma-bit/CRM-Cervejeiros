"""Divide mensagens longas do WhatsApp antes de enviar botões/listas.

Evita falha da Cloud API quando uma apresentação comercial ultrapassa o limite
aceito no corpo de uma mensagem interativa. Mantém o conteúdo completo e deixa
os botões apenas na última parte.
"""

import flow_media_patch as fm
import patched_app as p

crm = p.crm

# Texto comum do WhatsApp suporta mensagens maiores, mas o corpo de mensagens
# interativas (botões/listas) precisa ser bem menor. Usamos margem de segurança.
MAX_TEXT_BODY = 3000
MAX_INTERACTIVE_BODY = 900


def _split_text(text, limit=MAX_TEXT_BODY):
    text = (text or "").strip()
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _send_whatsapp_rich_safe(phone, message):
    kind, data = fm._parse_marker(message)

    if kind in {"buttons", "list"}:
        body = data.get("body", "")

        # Para garantir que a ÚLTIMA mensagem interativa seja aceita pela API,
        # todo o corpo é dividido em blocos de no máximo 900 caracteres.
        # Assim, o fechamento da apresentação e o botão CONTINUAR sempre chegam.
        chunks = _split_text(body, MAX_INTERACTIVE_BODY)

        for chunk in chunks[:-1]:
            ok, detail = fm._wa_post(phone, {
                "type": "text",
                "text": {"body": chunk},
            })
            if not ok:
                return False, detail

        final_body = chunks[-1] if chunks else ""

        if kind == "buttons":
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": str(opt["id"]),
                        "title": opt["title"][:20],
                    },
                }
                for opt in data.get("options", [])[:3]
            ]
            return fm._wa_post(phone, {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": final_body},
                    "action": {"buttons": buttons},
                },
            })

        rows = [
            {"id": str(opt["id"]), "title": opt["title"][:24]}
            for opt in data.get("options", [])[:10]
        ]
        return fm._wa_post(phone, {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": final_body},
                "action": {
                    "button": data.get("button", "Escolher")[:20],
                    "sections": [{"title": "Opções", "rows": rows}],
                },
            },
        })

    if isinstance(message, str) and len(message) > MAX_TEXT_BODY:
        chunks = _split_text(message, MAX_TEXT_BODY)
        last_detail = ""
        for chunk in chunks:
            ok, last_detail = fm._wa_post(phone, {
                "type": "text",
                "text": {"body": chunk},
            })
            if not ok:
                return False, last_detail
        return True, last_detail

    return fm._wa_post(phone, {"type": "text", "text": {"body": message}})


# O webhook do flow_media_patch resolve esta função pelo namespace do módulo,
# então substituir o atributo corrige também as respostas automáticas existentes.
fm._send_whatsapp_rich = _send_whatsapp_rich_safe
crm.send_whatsapp_cloud = _send_whatsapp_rich_safe
