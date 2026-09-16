"""Central de contato direto na ficha do lead.

Permite iniciar/retomar contato por WhatsApp ou Instagram a partir do CRM,
registrando o envio no histórico do lead. A interface é injetada na ficha sem
alterar o template principal.
"""
import re
from datetime import datetime
from urllib.parse import quote

from flask import flash, redirect, request, url_for

import patched_app as patched
import sitecustomize as sc

crm = patched.crm
app = patched.app


def _tag_value(lead, key):
    try:
        return sc._tag_value(lead, key)
    except Exception:
        notes = lead.notes or ""
        m = re.search(rf"^\[{re.escape(key)}\]=(.*)$", notes, flags=re.MULTILINE)
        return m.group(1).strip() if m else ""


def _whatsapp_number(lead):
    # Leads do Instagram preservam a chave IG em phone e guardam o WhatsApp em Q_WHATSAPP.
    if str(lead.phone or "").startswith("IG-"):
        return _tag_value(lead, "Q_WHATSAPP")
    return lead.phone or _tag_value(lead, "Q_WHATSAPP")


def _instagram_identity(lead):
    key = _tag_value(lead, "Q_INSTAGRAM_KEY") or (lead.phone or "")
    m = re.match(r"^IG-([^-]+)-(.+)$", str(key))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _channel_status(lead):
    wa = _whatsapp_number(lead)
    page_id, sender_id = _instagram_identity(lead)
    return {
        "whatsapp": bool(wa),
        "whatsapp_number": wa,
        "instagram": bool(page_id and sender_id),
        "instagram_page_id": page_id,
        "instagram_sender_id": sender_id,
    }


@app.route("/lead/<int:lead_id>/contact-outreach", methods=["POST"])
@crm.login_required
def lead_contact_outreach(lead_id):
    lead = crm.visible_leads_query().filter_by(id=lead_id).first_or_404()
    channel = (request.form.get("channel") or "").strip().lower()
    message = (request.form.get("message") or "").strip()
    if not message:
        flash("Digite a mensagem antes de enviar.", "warning")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    ok = False
    detail = ""
    label = ""

    if channel == "whatsapp":
        number = _whatsapp_number(lead)
        if not number:
            flash("Este lead não possui WhatsApp disponível para contato.", "danger")
            return redirect(url_for("lead_detail", lead_id=lead.id))
        ok, detail = crm.send_whatsapp_cloud(number, message)
        label = "WhatsApp"

    elif channel == "instagram":
        page_id, sender_id = _instagram_identity(lead)
        if not page_id or not sender_id:
            flash("Este lead não possui identificação do Instagram para contato direto.", "danger")
            return redirect(url_for("lead_detail", lead_id=lead.id))
        account = sc._account_config(page_id)
        ok, detail = sc._send_instagram(sender_id, message, account.get("token"))
        label = "Instagram"
    else:
        flash("Escolha WhatsApp ou Instagram.", "warning")
        return redirect(url_for("lead_detail", lead_id=lead.id))

    if ok:
        crm.db.session.add(crm.Interaction(
            lead_id=lead.id,
            user_id=request.cookies.get("user_id") if False else None,
            channel=label,
            direction="out",
            message=message,
            ai_generated=False,
        ))
        lead.last_contact = datetime.utcnow()
        crm.db.session.add(crm.AutomationLog(
            lead_id=lead.id,
            action=f"Contato manual via {label}",
            detail="Mensagem iniciada pelo usuário diretamente na ficha do lead.",
        ))
        crm.db.session.commit()
        flash(f"Mensagem enviada pelo {label} e registrada no histórico.", "success")
    else:
        crm.db.session.rollback()
        flash(f"Não foi possível enviar pelo {label}: {detail}", "danger")

    return redirect(url_for("lead_detail", lead_id=lead.id))


def _outreach_html(lead):
    status = _channel_status(lead)
    wa_number = re.sub(r"\D", "", status["whatsapp_number"] or "")
    wa_link = f"https://wa.me/{wa_number}" if wa_number else ""

    options = []
    if status["whatsapp"]:
        options.append('<option value="whatsapp">WhatsApp</option>')
    if status["instagram"]:
        options.append('<option value="instagram">Instagram</option>')
    if not options:
        options.append('<option value="">Nenhum canal disponível</option>')

    buttons = ''
    if wa_link:
        buttons += f'<a class="btn whatsapp" target="_blank" rel="noopener" href="{wa_link}">Abrir WhatsApp</a>'
    if status["instagram"]:
        buttons += '<span class="badge" style="padding:10px 12px">📸 Instagram conectado ao lead</span>'

    disabled = ' disabled' if not (status["whatsapp"] or status["instagram"]) else ''
    default_message = "Olá, tudo bem? Sou da equipe Cervejeiros. Gostaria de falar com você sobre seu interesse em nossa operação."
    return f'''
<section class="panel" style="margin-top:18px;border:2px solid #dbe4ee">
  <div class="title-row" style="margin-bottom:10px">
    <div>
      <h2 style="margin:0">💬 Chamar cliente</h2>
      <p class="muted" style="margin:4px 0 0">Inicie ou retome uma conversa com <b>{lead.name}</b> diretamente pelo CRM.</p>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">{buttons}</div>
  </div>
  <form method="post" action="/lead/{lead.id}/contact-outreach" style="display:grid;gap:10px">
    <label><b>Canal de contato</b>
      <select name="channel" required{disabled}>{''.join(options)}</select>
    </label>
    <label><b>Mensagem para o cliente</b>
      <textarea name="message" rows="4" required{disabled}>{default_message}</textarea>
    </label>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <button class="btn primary" type="submit"{disabled}>Enviar mensagem</button>
      <span class="muted">O envio fica registrado automaticamente no Histórico de contatos.</span>
    </div>
  </form>
</section>
'''


@app.after_request
def _inject_outreach_panel(response):
    try:
        if request.method != "GET" or not request.path.startswith("/lead/"):
            return response
        if response.status_code != 200 or not response.content_type.startswith("text/html"):
            return response
        m = re.fullmatch(r"/lead/(\d+)", request.path.rstrip("/"))
        if not m:
            return response
        lead = crm.visible_leads_query().filter_by(id=int(m.group(1))).first()
        if not lead:
            return response
        html = response.get_data(as_text=True)
        if 'id="crm-chamar-cliente"' in html or '💬 Chamar cliente' in html:
            return response
        panel = _outreach_html(lead).replace('<section class="panel"', '<section id="crm-chamar-cliente" class="panel"', 1)
        marker = '<h2>Histórico de contatos</h2>'
        pos = html.find(marker)
        if pos != -1:
            section_pos = html.rfind('<section', 0, pos)
            if section_pos != -1:
                html = html[:section_pos] + panel + html[section_pos:]
            else:
                html = html.replace(marker, panel + marker, 1)
        else:
            html = html.replace('</main>', panel + '</main>', 1)
        response.set_data(html)
        response.headers['Content-Length'] = str(len(response.get_data()))
    except Exception as exc:
        app.logger.warning("Falha ao injetar central de contato: %s", exc)
    return response
