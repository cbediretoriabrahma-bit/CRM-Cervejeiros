document.addEventListener('DOMContentLoaded',()=>{
  const accountLinks=[...document.querySelectorAll('a[href*="/conta/"]')].filter(a=>/\/conta\/\d+/.test(a.getAttribute('href')||''));
  if(!accountLinks.length) return;

  const categoryGroups={
    'CMV':['CMV: Custo de mercadorias','CMV: Custo de geladeiras'],
    'Despesas com pessoal':['Pessoal empresa: Salários','Pessoal empresa: Freelancer','Pessoal empresa: Horas extras','Pessoal empresa: Comissões','Pessoal empresa: INSS','Pessoal empresa: FGTS','Pessoal empresa: Refeições'],
    'Despesas de ocupação':['Ocupação: Aluguel','Ocupação: Condomínio','Ocupação: IPTU','Ocupação: Energia elétrica','Ocupação: Água','Ocupação: Internet','Ocupação: Telefone','Ocupação: Segurança','Ocupação: Limpeza'],
    'Despesas comerciais':['Comercial: Marketing','Comercial: Taxa de cartão','Comercial: Propaganda','Comercial: Ação de divulgação','Comercial: Combustível','Comercial: Manutenção de veículo','Comercial: Manutenção de loja'],
    'Despesas administrativas':['Administrativa: Contabilidade','Administrativa: Sistema ERP','Administrativa: Material de escritório','Administrativa: Honorários advocatícios','Administrativa: Licenças e alvarás'],
    'Despesas financeiras':['Financeira: Juros','Financeira: Antecipação de cartão'],
    'Impostos sobre vendas':['Impostos: Simples Nacional','Impostos: ICMS','Impostos: ISS','Impostos: PIS/COFINS','Impostos: Outros impostos sobre vendas'],
    'Despesas pessoais':['Despesa pessoal: Mercado','Despesa pessoal: Farmácia','Despesa pessoal: Passeio','Despesa pessoal: Viagens','Despesa pessoal: Escola','Despesa pessoal: Pet Shop','Despesa pessoal: Empregada','Despesa pessoal: Compra na loja','Despesa pessoal: Saúde','Despesa pessoal: Unimed','Despesa pessoal: Dentista','Despesa pessoal: Parcelamento de imposto','Despesa pessoal: Financiamento','Despesa pessoal: Karina','Despesa pessoal: iFood','Despesa pessoal: Piscina','Despesa pessoal: Cartão de crédito','Despesa pessoal: Combustível','Despesa pessoal: Energia elétrica','Despesa pessoal: Água','Despesa pessoal: Condomínio','Despesa pessoal: Telefone','Despesa pessoal: Internet']
  };
  const dreGroups={
    'cmv':'CMV','pessoal_empresa':'Despesas com pessoal','ocupacao':'Despesas de ocupação','comercial':'Despesas comerciais','administrativa':'Despesas administrativas','financeira':'Despesas financeiras','impostos':'Impostos sobre vendas','pessoal':'Despesas pessoais — fora do DRE operacional','nao_classificado':'Não classificado'
  };

  const style=document.createElement('style');
  style.textContent=`
    .quick-action-btn{white-space:nowrap}
    .qe-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.48);display:none;align-items:center;justify-content:center;z-index:9999;padding:16px}
    .qe-backdrop.open{display:flex}.qe-modal{background:#fff;border-radius:14px;max-width:560px;width:100%;max-height:90vh;overflow:auto;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.25)}
    .qe-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.qe-head h3{margin:0}.qe-close{border:0;background:transparent;font-size:28px;cursor:pointer}
    .qe-card{border:1px solid #ddd;border-radius:10px;padding:14px;margin-top:16px}.qe-card select{width:100%;margin:8px 0 10px}.qe-status{display:inline-block;padding:5px 9px;border-radius:999px;font-weight:700;font-size:12px}.qe-on{background:#dcfce7;color:#166534}.qe-off{background:#f3f4f6;color:#4b5563}
  `;
  document.head.appendChild(style);

  const backdrop=document.createElement('div');
  backdrop.className='qe-backdrop';
  backdrop.innerHTML=`<div class="qe-modal">
    <div class="qe-head"><div><h3 id="qe-title"></h3><div id="qe-sub" class="muted"></div></div><button class="qe-close" type="button">×</button></div>
    <div class="qe-card" id="qe-category-card" style="display:none"><strong>Categoria da conta</strong><form id="qe-category" method="post"><select name="category" id="qe-category-select"></select><button class="btn primary small" type="submit">Salvar categoria</button></form></div>
    <div class="qe-card" id="qe-dre-card" style="display:none"><strong>Classificação do DRE</strong><form id="qe-dre" method="post"><select name="dre_class" id="qe-dre-select"></select><button class="btn primary small" type="submit">Salvar classificação</button></form></div>
    <div class="qe-card" id="qe-recurring-card" style="display:none"><strong>Conta recorrente</strong><p id="qe-recurring-text" class="muted"></p><form id="qe-recurring" method="post"><button id="qe-recurring-btn" class="btn small" type="submit"></button></form></div>
  </div>`;
  document.body.appendChild(backdrop);
  const close=()=>backdrop.classList.remove('open');
  backdrop.querySelector('.qe-close').addEventListener('click',close);
  backdrop.addEventListener('click',e=>{if(e.target===backdrop) close();});

  const categorySelect=backdrop.querySelector('#qe-category-select');
  Object.entries(categoryGroups).forEach(([label,items])=>{const g=document.createElement('optgroup');g.label=label;items.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v.replace(/^[^:]+:\s*/,'');g.appendChild(o)});categorySelect.appendChild(g)});
  const other=document.createElement('option');other.value='Outros';other.textContent='Outros';categorySelect.appendChild(other);
  const dreSelect=backdrop.querySelector('#qe-dre-select');
  Object.entries(dreGroups).forEach(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;dreSelect.appendChild(o)});

  async function openEditor(id,mode){
    const response=await fetch(`/conta/${id}/edicao-rapida-status`,{credentials:'same-origin'});
    if(!response.ok){alert('Não foi possível carregar os dados da conta.');return;}
    const data=await response.json();
    backdrop.querySelector('#qe-sub').textContent=`${data.supplier||''} • ${data.description||''}`;
    ['qe-category-card','qe-dre-card','qe-recurring-card'].forEach(x=>backdrop.querySelector('#'+x).style.display='none');

    if(mode==='category'){
      backdrop.querySelector('#qe-title').textContent='Alterar categoria';
      backdrop.querySelector('#qe-category-card').style.display='block';
      if([...categorySelect.options].some(o=>o.value===data.category)) categorySelect.value=data.category; else {const custom=document.createElement('option');custom.value=data.category;custom.textContent=data.category||'Sem categoria';categorySelect.insertBefore(custom,categorySelect.firstChild);categorySelect.value=data.category;}
      backdrop.querySelector('#qe-category').action=`/conta/${id}/categoria-rapida`;
    }
    if(mode==='dre'){
      backdrop.querySelector('#qe-title').textContent='Classificar no DRE';
      backdrop.querySelector('#qe-dre-card').style.display='block';
      dreSelect.value=data.dre_class||'nao_classificado';
      backdrop.querySelector('#qe-dre').action=`/conta/${id}/dre-rapido`;
    }
    if(mode==='recurring'){
      backdrop.querySelector('#qe-title').textContent='Conta recorrente';
      backdrop.querySelector('#qe-recurring-card').style.display='block';
      backdrop.querySelector('#qe-recurring').action=`/conta/${id}/recorrencia-rapida`;
      const text=backdrop.querySelector('#qe-recurring-text'),btn=backdrop.querySelector('#qe-recurring-btn');
      if(data.recurring){text.innerHTML='<span class="qe-status qe-on">SIM, RECORRENTE</span> Esta conta já gera os próximos vencimentos automaticamente.';btn.textContent='Desativar recorrência';btn.className='btn small';}
      else{text.innerHTML='<span class="qe-status qe-off">NÃO RECORRENTE</span> Esta conta ainda não gera os próximos vencimentos.';btn.textContent='Tornar recorrente';btn.className='btn primary small';}
    }
    backdrop.classList.add('open');
  }

  accountLinks.forEach(link=>{
    const m=(link.getAttribute('href')||'').match(/\/conta\/(\d+)/); if(!m) return;
    const actionWrap=link.closest('td')?.querySelector('div') || link.parentElement;
    if(!actionWrap || actionWrap.querySelector('.quick-category-btn')) return;

    const categoryBtn=document.createElement('button');categoryBtn.type='button';categoryBtn.className='btn small quick-action-btn quick-category-btn';categoryBtn.textContent='Categoria';categoryBtn.addEventListener('click',()=>openEditor(m[1],'category'));
    const dreBtn=document.createElement('button');dreBtn.type='button';dreBtn.className='btn small quick-action-btn';dreBtn.textContent='DRE';dreBtn.addEventListener('click',()=>openEditor(m[1],'dre'));
    const recurringBtn=document.createElement('button');recurringBtn.type='button';recurringBtn.className='btn small quick-action-btn';recurringBtn.textContent='Recorrente';recurringBtn.addEventListener('click',()=>openEditor(m[1],'recurring'));

    actionWrap.appendChild(categoryBtn);actionWrap.appendChild(dreBtn);actionWrap.appendChild(recurringBtn);
  });
});
