"""Deixa o convite para reunião com consultor com uma única opção de avanço."""

import flow_media_patch as fm
import onboarding_contact_patch as ob
import patched_app as p


def _reply(lead, channel):
    n = ob._count(lead, channel)

    if n == 11:
        return fm._buttons_marker(
            "🍻 *Obrigado pelas respostas!*\n\n"
            "Agora já conseguimos entender melhor o seu perfil. *Gostaria de conversar com um de nossos consultores* para conhecer melhor o projeto, os planos, valores e as oportunidades disponíveis para sua região?",
            [
                {"id": "1", "title": "SIM, AGENDAR REUNIÃO"},
            ],
        )

    return ob._reply(lead, channel)


def _reply_whatsapp(lead, text):
    return _reply(lead, "WhatsApp")


def _reply_instagram(lead):
    return _reply(lead, "Instagram")


def _qualification(lead, channel):
    return _reply(lead, channel)


p._reply_for_message = _reply_whatsapp
p._reply_for_instagram = _reply_instagram
p._qualification_reply = _qualification
fm._qualification_reply = _qualification

# Corrige o envio da apresentação longa no WhatsApp dividindo o texto em partes
# seguras e mantendo os botões na última mensagem.
import whatsapp_long_message_patch  # noqa: F401,E402
