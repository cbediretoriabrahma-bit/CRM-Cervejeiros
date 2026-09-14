"""Correções de robustez para o fluxo final do CRM Cervejeiros.

- Permite respostas iguais em perguntas consecutivas sem tratá-las como duplicadas.
- Interpreta corretamente os textos dos botões de reunião, inclusive quando o
  usuário digita a resposta em vez de tocar no botão.
"""

import unicodedata

import final_qualification_patch as fq
import patched_app as p


# O webhook já possui proteção pelo message_id da Meta. A deduplicação adicional
# por texto podia ignorar respostas legítimas iguais, por exemplo "1" em duas
# perguntas diferentes. Desativamos somente essa deduplicação textual.
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

    # Primeira opção: reunião/agendamento.
    if (
        t == "1"
        or "quero agendar" in t
        or "quero marcar" in t
        or "agendar reuniao" in t
        or "marcar reuniao" in t
        or "quero uma reuniao" in t
        or t in {"sim", "quero", "agendar", "reuniao"}
    ):
        return "1"

    # Segunda opção: ainda quer entender melhor antes da reunião.
    if (
        t == "2"
        or "entender melhor" in t
        or "saber mais" in t
        or "mais informacoes primeiro" in t
        or "talvez" in t
    ):
        return "2"

    # Terceira opção: somente informações / não quer reunião agora.
    if (
        t == "3"
        or "so informacoes" in t
        or "somente informacoes" in t
        or "apenas informacoes" in t
        or "agora nao" in t
        or t in {"nao", "não"}
    ):
        return "3"

    return text


def _apply_answer_resilient(lead, text, inbound_count, channel):
    # Na etapa do convite para reunião, converte tanto o texto exibido no botão
    # quanto frases digitadas livremente para os IDs 1/2/3 esperados pelo parser.
    if inbound_count == 8:
        text = _meeting_choice(text)
    return _original_apply(lead, text, inbound_count, channel)


p._apply_answer_by_count = _apply_answer_resilient
