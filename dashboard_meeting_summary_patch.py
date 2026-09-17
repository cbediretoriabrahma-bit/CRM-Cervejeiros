"""Resumo de qualificação para os cartões de reunião do Dashboard."""
import re

import patched_app as p

crm = p.crm


def _tag(lead, key):
    notes = lead.notes or ""
    match = re.search(rf"^\[{re.escape(key)}\]=(.*)$", notes, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _money(value):
    try:
        value = float(value or 0)
    except Exception:
        value = 0
    if not value:
        return "Não informado"
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _label_access(value):
    return {
        "locais_em_vista": "Já tem locais em vista",
        "alguns_contatos": "Tem alguns contatos",
        "vai_prospectar": "Ainda vai prospectar",
    }.get(value, value or "Não informado")


def _label_objective(value):
    return {
        "expandir": "Expandir o negócio",
        "avaliar": "Começar e avaliar expansão",
        "renda_complementar": "Renda complementar",
    }.get(value, value or "Não informado")


def _meeting_qualification(lead):
    if not lead:
        return {}
    prospects = _tag(lead, "Q_PROSPECTS") or "Não informado"
    fridges = _tag(lead, "Q_FRIDGES") or "Não informado"
    return {
        "name": lead.name or "-",
        "phone": lead.phone or "Não informado",
        "city": lead.city or "Não informado",
        "state": lead.state or "-",
        "source": lead.source or "Não informado",
        "owner": lead.owner.name if lead.owner else "Não atribuído",
        "temperature": lead.temperature or "-",
        "score": lead.score or 0,
        "investment": _money(lead.investment),
        "timeframe": lead.timeframe or "Não informado",
        "access": _label_access(_tag(lead, "Q_ACCESS")),
        "prospects": prospects,
        "fridges": fridges,
        "objective": _label_objective(_tag(lead, "Q_OBJECTIVE")),
        "meeting_interest": lead.meeting_interest or "Não informado",
        "stage": lead.stage or "-",
    }


@crm.app.context_processor
def _dashboard_meeting_summary_context():
    return {"meeting_qualification": _meeting_qualification}


# Carrega depois dos helpers de reunião para que o Dashboard use a agenda
# sincronizada com a etapa atual do Pipeline.
import dashboard_calendar_patch  # noqa: F401,E402
