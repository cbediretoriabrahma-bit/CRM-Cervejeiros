"""Envia o vídeo de qualificação no Instagram antes da 3ª pergunta.

Este patch envolve o sender rico já instalado por flow_media_patch, preservando
quick replies e o restante do fluxo.
"""
import json
import urllib.request

import flow_media_patch as fm
import sitecustomize as sc


def _instagram_post(recipient_id, message_payload, token):
    if not token:
        return False, "Token da conta do Instagram não configurado."
    payload = json.dumps({
        "recipient": {"id": str(recipient_id)},
        "messaging_type": "RESPONSE",
        "message": message_payload,
    }).encode()
    req = urllib.request.Request(
        "https://graph.facebook.com/v23.0/me/messages",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return True, response.read().decode()
    except Exception as exc:
        return False, str(exc)


_original_send_instagram = sc._send_instagram


def _send_instagram_with_video(recipient_id, message, token):
    kind, data = fm._parse_marker(message)
    body = (data or {}).get("body", "") if kind else ""

    # A mensagem que vem imediatamente após cidade/estado inicia com este texto.
    if body.startswith("Agora vamos entender um pouco melhor o seu perfil") and fm.VIDEO_URL:
        _instagram_post(
            recipient_id,
            {"text": "Antes de continuarmos, veja rapidamente como funciona o sistema de geladeiras de autoatendimento CERVEJEIROS by WOC Group na prática. 👇🍻"},
            token,
        )
        ok_video, detail_video = _instagram_post(
            recipient_id,
            {
                "attachment": {
                    "type": "video",
                    "payload": {"url": fm.VIDEO_URL, "is_reusable": True},
                }
            },
            token,
        )
        if not ok_video:
            fm.crm.app.logger.warning("Vídeo Instagram não enviado recipient=%s: %s", recipient_id, detail_video)

    return _original_send_instagram(recipient_id, message, token)


sc._send_instagram = _send_instagram_with_video
