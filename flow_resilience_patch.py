"""Correções de robustez para o fluxo final do CRM Cervejeiros.

- Permite respostas iguais em perguntas consecutivas sem tratá-las como duplicadas.
- Interpreta corretamente os textos dos botões de reunião, inclusive quando o
  usuário digita a resposta em vez de tocar no botão.
- Garante a ordem visual após o estado: primeiro o vídeo e só depois a próxima
  pergunta de qualificação no WhatsApp.
"""

import time
import unicodedata

import final_qualification_patch as fq
import flow_media_patch as fm
import patched_app as p


def _allow_repeated_valid_answers(lead, text):
    return False


p._recent_duplicate = _allow_repeated_valid_answers


_original_apply = p._apply_answer_by_count


def _normalize(text):
    value = (text or "").strip().lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _meeting_choice(text):
    t = _normalize(text)

    if (
        t == "1"
        or "quero agendar" in t
        or "quero marcar" in t
        or "agendar reuniao" in t
        or "marcar reuniao" in t
        or "quero uma reuniao" in t
        or t in {"sim", "quero", "agendar", "reuniao"}
    ):
        return "Sim"

    if (
        t == "2"
        or "entender melhor" in t
        or "saber mais" in t
        or "mais informacoes primeiro" in t
        or "talvez" in t
    ):
        return "Talvez"

    if (
        t == "3"
        or "so informacoes" in t
        or "somente informacoes" in t
        or "apenas informacoes" in t
        or "agora nao" in t
        or t in {"nao", "não"}
    ):
        return "Não"

    return text


def _apply_answer_resilient(lead, text, inbound_count, channel):
    if inbound_count == 8:
        text = _meeting_choice(text)
    return _original_apply(lead, text, inbound_count, channel)


p._apply_answer_by_count = _apply_answer_resilient


_original_send_whatsapp_video = fm._send_whatsapp_video


def _send_whatsapp_video_in_order(phone):
    ok, detail = _original_send_whatsapp_video(phone)
    if ok:
        # A API confirma o envio antes de o WhatsApp terminar de processar o vídeo.
        # Uma espera maior evita que a pergunta seguinte apareça acima do vídeo.
        time.sleep(6.0)
    return ok, detail


fm._send_whatsapp_video = _send_whatsapp_video_in_order
