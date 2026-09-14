"""Padronização visual das respostas automáticas do CRM.

Mantém toda a lógica de qualificação existente e apenas organiza a mensagem
antes do envio, com espaçamento e opções em linhas separadas para WhatsApp e
Instagram.
"""
import re

import patched_app as p


_original_reply_for_message = p._reply_for_message
_original_reply_for_instagram = p._reply_for_instagram


def _format_reply(message):
    if not message:
        return message

    text = str(message).replace("\r\n", "\n").replace("\r", "\n").strip()

    # Corrige mensagens montadas por concatenação, mantendo leitura limpa.
    text = re.sub(r"[ \t]+", " ", text)

    # Cada alternativa fica em uma linha própria, em um padrão único.
    option_icons = {"1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣"}
    for number, icon in option_icons.items():
        text = re.sub(
            rf"\s*{number}\)\s*",
            f"\n{icon} ",
            text,
        )

    # Benefícios sempre em linhas separadas.
    text = re.sub(r"\s*✅\s*", "\n✅ ", text)

    # Organiza o texto institucional mais longo em blocos curtos.
    block_starts = [
        "Hoje já contamos",
        "Já temos operações",
        "A Cervejeiros trabalha",
        "Em operações com bom desempenho",
        "É uma alternativa",
        "Gostaria de falar com um de nossos consultores",
    ]
    for marker in block_starts:
        text = text.replace(marker, f"\n\n{marker}")

    # Dá respiro entre a pergunta e as alternativas.
    text = re.sub(r"\?\n(1️⃣)", r"?\n\n\1", text)
    text = re.sub(r":\n(1️⃣)", r":\n\n\1", text)

    # Remove excessos de linhas, preservando no máximo uma linha em branco.
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _formatted_whatsapp_reply(lead, text):
    return _format_reply(_original_reply_for_message(lead, text))


def _formatted_instagram_reply(lead):
    return _format_reply(_original_reply_for_instagram(lead))


p._reply_for_message = _formatted_whatsapp_reply
p._reply_for_instagram = _formatted_instagram_reply
