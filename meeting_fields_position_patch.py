"""Reposiciona os campos de resumo da 1ª e 2ª reunião junto à qualificação do lead.

Os formulários já existentes continuam usando a mesma rota e o mesmo histórico;
este patch apenas leva o bloco para a área em que o usuário consulta a
qualificação, logo após a conversa registrada, para facilitar o preenchimento.
"""
from flask import request

import patched_app as p

crm = p.crm

_SCRIPT = r"""
<script id="meeting-fields-position-patch">
document.addEventListener('DOMContentLoaded', function () {
  try {
    if (!window.location.pathname.match(/^\/lead\/\d+\/?$/)) return;

    const panelHeadings = Array.from(document.querySelectorAll('section.panel > h2'));
    const qualificationHeading = panelHeadings.find(h =>
      (h.textContent || '').trim().includes('Qualificação completa')
    );
    const reportsHeading = panelHeadings.find(h =>
      (h.textContent || '').includes('Relatórios das reuniões')
    );

    if (!qualificationHeading || !reportsHeading) return;

    const qualificationPanel = qualificationHeading.closest('section.panel');
    const reportsSection = reportsHeading.closest('section.panel');
    if (!qualificationPanel || !reportsSection || qualificationPanel.contains(reportsSection)) return;

    const moverForm = qualificationPanel.querySelector('form.inline');
    if (moverForm) {
      qualificationPanel.insertBefore(reportsSection, moverForm);
    } else {
      qualificationPanel.appendChild(reportsSection);
    }

    reportsHeading.textContent = '📝 Resumo pós-reunião';
    reportsSection.style.marginTop = '18px';
    reportsSection.style.padding = '16px';
    reportsSection.style.border = '1px solid #e5e7eb';
    reportsSection.style.borderRadius = '12px';
    reportsSection.style.boxShadow = 'none';

    Array.from(reportsSection.querySelectorAll('.grid2')).forEach(function (grid) {
      grid.style.gridTemplateColumns = '1fr';
    });

    const firstTitle = Array.from(reportsSection.querySelectorAll('h3')).find(h =>
      (h.textContent || '').trim() === '1ª reunião'
    );
    if (firstTitle) firstTitle.textContent = '📝 Resumo da conversa após a 1ª reunião';

    const secondTitle = Array.from(reportsSection.querySelectorAll('h3')).find(h =>
      (h.textContent || '').trim() === '2ª reunião'
    );
    if (secondTitle) secondTitle.textContent = '📝 Novo resumo da conversa após a 2ª reunião';
  } catch (err) {
    console.warn('meeting-fields-position-patch', err);
  }
});
</script>
"""


@crm.app.after_request
def _position_meeting_summary_fields(response):
    try:
        if request.endpoint != 'lead_detail':
            return response
        if response.mimetype != 'text/html':
            return response

        html = response.get_data(as_text=True)
        if 'meeting-fields-position-patch' in html:
            return response
        if '</body>' not in html:
            return response

        html = html.replace('</body>', _SCRIPT + '\n</body>', 1)
        response.set_data(html)
        response.headers['Content-Length'] = str(len(response.get_data()))
    except Exception:
        crm.app.logger.exception('Falha ao reposicionar os campos de resumo das reuniões')
    return response
