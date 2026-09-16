"""Mantém o Instagram com o MESMO fluxo de qualificação do WhatsApp.

A única diferença deste patch é visual: no Direct, trechos entre *asteriscos*
são convertidos para caracteres em negrito Unicode para evitar que os asteriscos
apareçam literalmente. Perguntas, ordem, opções, score e agendamento vêm
exatamente de final_qualification_patch.py, igual ao WhatsApp.
"""
import json
import re

import final_qualification_patch as fq
import flow_media_patch as fm
import patched_app as p


def _unicode_bold(text):
    out = []
    for ch in str(text):
        code = ord(ch)
        if 65 <= code <= 90:
            out.append(chr(0x1D5D4 + (code - 65)))
        elif 97 <= code <= 122:
            out.append(chr(0x1D5EE + (code - 97)))
        elif 48 <= code <= 57:
            out.append(chr(0x1D7EC + (code - 48)))
        else:
            out.append(ch)
    return "".join(out)


def _render_instagram_markup(text):
    if not isinstance(text, str):
        return text

    def repl(match):
        return _unicode_bold(match.group(1))

    return re.sub(r"\*([^*]+)\*", repl, text)


def _instagramize(message):
    if not message:
        return message
    kind, data = fm._parse_marker(message)
    if kind:
        data = dict(data or {})
        data["body"] = _render_instagram_markup(data.get("body", ""))
        prefix = "[[BUTTONS]]" if kind == "buttons" else "[[LIST]]"
        return prefix + json.dumps(data, ensure_ascii=False)
    return _render_instagram_markup(message)


def _same_flow_reply(lead, channel):
    # Usa a MESMA função de qualificação do WhatsApp.
    reply = fq._qualification_reply_final_v2(lead, channel)
    if channel == "Instagram":
        return _instagramize(reply)
    return reply


# WhatsApp e Instagram passam a compartilhar o mesmo questionário e a mesma ordem.
p._qualification_reply = _same_flow_reply
p._reply_for_message = lambda lead, text: _same_flow_reply(lead, "WhatsApp")
p._reply_for_instagram = lambda lead: _same_flow_reply(lead, "Instagram")
fm._qualification_reply = _same_flow_reply
