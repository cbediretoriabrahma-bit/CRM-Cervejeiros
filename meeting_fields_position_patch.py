"""Reposiciona os campos de resumo da 1ª e 2ª reunião junto à qualificação do lead.

Também garante um campo de resumo para a 1ª reunião mesmo quando o lead antigo
não possui uma tarefa de reunião vinculada. Assim o consultor consegue registrar
o pós-reunião sem depender do agendamento ter sido criado pelo fluxo novo.
"""
from flask import request

import patched_app as p

crm = p.crm

_SCRIPT = r"""
<script id="meeting-fields-position-patch">
document.addEventListener('DOMContentLoaded', function () {
  try {
    const pathMatch = window.location.pathname.match(/^\/lead\/(\d+)\/?$/);
    if (!pathMatch) return;
    const leadId = pathMatch[1];

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
    if (firstTitle) {
      firstTitle.textContent = '📝 Resumo da conversa após a 1ª reunião';
      const firstBox = firstTitle.closest('section');
      if (firstBox && !firstBox.querySelector('textarea[name="report_text"]')) {
        const oldEmpty = Array.from(firstBox.querySelectorAll('p')).find(p =>
          (p.textContent || '').includes('Nenhuma 1ª reunião cadastrada')
        );
        if (oldEmpty) oldEmpty.remove();

        const helper = document.createElement('p');
        helper.className = 'muted';
        helper.textContent = 'Registre abaixo o que foi conversado na 1ª reunião.';
        firstBox.appendChild(helper);

        const form = document.createElement('form');
        form.method = 'post';
        form.action = '/lead/' + leadId + '/meeting-report';
        form.style.display = 'grid';
        form.style.gap = '10px';
        form.innerHTML = `
          <label><b>Resumo da conversa da 1ª reunião</b>
            <textarea name="report_text" rows="7" placeholder="Escreva aqui o resumo da reunião: interesse do cliente, dúvidas, objeções, valores apresentados, condições combinadas e próximos passos..." required style="width:100%"></textarea>
          </label>
          <label><b>Próxima ação</b>
            <select name="next_action" style="width:100%">
              <option value="">Selecione</option>
              <option>Enviar contrato</option>
              <option>Retornar contato</option>
              <option>Agendar nova reunião</option>
              <option>Aguardando decisão</option>
              <option>Fechado</option>
              <option>Sem interesse</option>
            </select>
          </label>
          <label><b>Data do próximo contato</b>
            <input type="datetime-local" name="next_followup_at" style="width:100%">
          </label>
          <button class="btn primary" type="submit">Salvar resumo da 1ª reunião</button>
        `;
        firstBox.appendChild(form);
      }
    }

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
