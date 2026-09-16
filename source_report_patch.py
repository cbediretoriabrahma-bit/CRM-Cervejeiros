"""Relatório de origem dos leads no Dashboard."""

import patched_app as patched

crm = patched.crm
app = patched.app


def source_lead_report():
    """Retorna quantidade e percentual de leads por origem respeitando a visibilidade do usuário."""
    leads = crm.visible_leads_query().all()
    total = len(leads)

    counts = {}
    for lead in leads:
        source = (lead.source or "Não informado").strip() or "Não informado"
        counts[source] = counts.get(source, 0) + 1

    # Mantém WhatsApp e Instagram sempre visíveis no relatório, mesmo quando estiverem zerados.
    for source in ("WhatsApp", "Instagram"):
        counts.setdefault(source, 0)

    preferred = ["WhatsApp", "Instagram"]
    others = sorted((s for s in counts if s not in preferred), key=lambda s: (-counts[s], s.lower()))
    ordered = preferred + others

    rows = []
    for source in ordered:
        count = counts[source]
        rows.append({
            "source": source,
            "count": count,
            "percent": round((count / total * 100), 1) if total else 0.0,
        })

    return {"total": total, "rows": rows}


app.jinja_env.globals["source_lead_report"] = source_lead_report
