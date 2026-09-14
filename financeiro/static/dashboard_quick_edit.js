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
    .quick-action-btn{white-space:nowrap;position:relative}
    .quick-action-btn.done{border-color:#16a34a!important;background:#dcfce7!important;color:#166534!important;font-weight:700}
    .quick-action-btn.done::before{content:'✓ ';font-weight:900}
    .quick-action-btn.pending{opacity:.92}
    .qe-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.48);display:none;align-items:center;justify-content:center;z-index:9999;padding:16px}
    .qe-backdrop.open{display:flex}.qe-modal{background:#fff;border-radius:14px;max-width:640px;width:100%;max-height:90vh;overflow:auto;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.25)}
    .qe-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.qe-head h3{margin:0}.qe-close{border:0;background:transparent;font-size:28px;cursor:pointer}
    .qe-card{border:1px solid #ddd;border-radius:10px;padding:14px;margin-top:16px}.qe-card select{width:100%;margin:8px 0 10px}.qe-status{display:inline-block;padding:5px 9px;border-radius:999px;font-weight:700;font-size:12px}.qe-on{background:#dcfce7;color:#166534}.qe-off{background:#f3f4f6;color:#4b5563}
  `;
  document.head.appendChild(style);

  const backdrop=document.createElement('div');
  backdrop.className='qe-backdrop';
  backdrop.innerHTML=`<div class="qe-modal">
    <div class="qe-head"><div><h3 id="qe-title">Atualização rápida</h3><div id="qe-sub" class="muted"></div></div><button class="qe-close" type="button">×</button></div>
    <div class="qe-card" id="qe-category-card" style="display:none"><strong>Categoria</strong><form id="qe-category" method="post"><select name="category" id="qe-category-select"></select><button class="btn primary small" type="submit">Salvar categoria</button></form></div>
    <div class="qe-card" id="qe-dre-card" style="display:none"><strong>Classificação do DRE</strong><form id="qe-dre" method="post"><select name="dre_class" id="qe-dre-select"></select><button class="btn primary small" type="submit">Salvar DRE</button></form></div>
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

  function setVisible(kind){
    backdrop.querySelector('#qe-category-card').style.display=kind==='category'?'block':'none';
    backdrop.querySelector('#qe-dre-card').style.display=kind==='dre'?'block':'none';
    backdrop.querySelector('#qe-recurring-card').style.display=kind==='recurring'?'block':'none';
    backdrop.querySelector('#qe-title').textContent=kind==='category'?'Alterar categoria':kind==='dre'?'Classificar no DRE':'Conta recorrente';
  }

  async function loadStatus(id){
    const response=await fetch(`/conta/${id}/edicao-rapida-status`,{credentials:'same-origin'});
    if(!response.ok) throw new Error('status');
    return await response.json();
  }

  function applyButtonState(buttons,data){
    const categoryDone=!!(data.category && data.category.trim() && data.category.trim().toLowerCase()!=='outros');
    const dreDone=!!(data.dre_class && data.dre_class!=='nao_classificado');
    const recurringDone=!!data.recurring;
    buttons.category.classList.toggle('done',categoryDone);buttons.category.classList.toggle('pending',!categoryDone);
    buttons.dre.classList.toggle('done',dreDone);buttons.dre.classList.toggle('pending',!dreDone);
    buttons.recurring.classList.toggle('done',recurringDone);buttons.recurring.classList.toggle('pending',!recurringDone);
    buttons.category.title=categoryDone?`Categoria definida: ${data.category}`:'Categoria ainda não definida';
    buttons.dre.title=dreDone?`DRE: ${dreGroups[data.dre_class]||data.dre_class}`:'DRE ainda não classificado';
    buttons.recurring.title=recurringDone?'Conta recorrente ativa':'Conta não recorrente';
  }

  async function openEditor(id,kind,buttons){
    let data;
    try{data=await loadStatus(id);}catch(e){alert('Não foi possível carregar os dados da conta.');return;}
    applyButtonState(buttons,data);
    backdrop.querySelector('#qe-sub').textContent=`${data.supplier||''} • ${data.description||''}`;
    setVisible(kind);
    if(kind==='category'){
      if([...categorySelect.options].some(o=>o.value===data.category)) categorySelect.value=data.category;
      else {const custom=document.createElement('option');custom.value=data.category;custom.textContent=data.category||'Sem categoria';categorySelect.insertBefore(custom,categorySelect.firstChild);categorySelect.value=data.category;}
      backdrop.querySelector('#qe-category').action=`/conta/${id}/categoria-rapida`;
    }
    if(kind==='dre'){
      dreSelect.value=data.dre_class||'nao_classificado';
      backdrop.querySelector('#qe-dre').action=`/conta/${id}/dre-rapido`;
    }
    if(kind==='recurring'){
      backdrop.querySelector('#qe-recurring').action=`/conta/${id}/recorrencia-rapida`;
      const text=backdrop.querySelector('#qe-recurring-text'),btn=backdrop.querySelector('#qe-recurring-btn');
      if(data.recurring){text.innerHTML='<span class="qe-status qe-on">RECORRENTE</span> Esta conta gera os próximos vencimentos automaticamente.';btn.textContent='Desativar recorrência';btn.className='btn small';}
      else{text.innerHTML='<span class="qe-status qe-off">NÃO RECORRENTE</span> Você pode transformar esta conta em recorrente.';btn.textContent='Tornar recorrente';btn.className='btn primary small';}
    }
    backdrop.classList.add('open');
  }

  accountLinks.forEach(link=>{
    const m=(link.getAttribute('href')||'').match(/\/conta\/(\d+)/); if(!m) return;
    const id=m[1];
    const actionWrap=link.closest('td')?.querySelector('div') || link.parentElement;
    if(!actionWrap || actionWrap.querySelector('.quick-category-btn')) return;

    const categoryBtn=document.createElement('button');categoryBtn.type='button';categoryBtn.className='btn small quick-action-btn quick-category-btn pending';categoryBtn.textContent='Categoria';
    const dreBtn=document.createElement('button');dreBtn.type='button';dreBtn.className='btn small quick-action-btn quick-dre-btn pending';dreBtn.textContent='DRE';
    const recurringBtn=document.createElement('button');recurringBtn.type='button';recurringBtn.className='btn small quick-action-btn quick-recurring-btn pending';recurringBtn.textContent='Recorrente';
    const buttons={category:categoryBtn,dre:dreBtn,recurring:recurringBtn};
    categoryBtn.addEventListener('click',()=>openEditor(id,'category',buttons));
    dreBtn.addEventListener('click',()=>openEditor(id,'dre',buttons));
    recurringBtn.addEventListener('click',()=>openEditor(id,'recurring',buttons));
    actionWrap.appendChild(categoryBtn);actionWrap.appendChild(dreBtn);actionWrap.appendChild(recurringBtn);

    loadStatus(id).then(data=>applyButtonState(buttons,data)).catch(()=>{});
  });
});
