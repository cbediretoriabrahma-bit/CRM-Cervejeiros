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

  const style=document.createElement('style');
  style.textContent=`
    .quick-action-btn{white-space:nowrap;position:relative}
    .quick-action-btn.done{border-color:#16a34a!important;background:#dcfce7!important;color:#166534!important;font-weight:700}
    .quick-action-btn.done::before{content:'✓ ';font-weight:900}
    .quick-action-btn.pending{opacity:.92}
    .qe-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.48);display:none;align-items:center;justify-content:center;z-index:9999;padding:16px}
    .qe-backdrop.open{display:flex}
    .qe-modal{background:#fff;border-radius:14px;max-width:640px;width:100%;max-height:90vh;overflow:auto;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.25)}
    .qe-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.qe-head h3{margin:0}.qe-close{border:0;background:transparent;font-size:28px;cursor:pointer}
    .qe-card{border:1px solid #ddd;border-radius:10px;padding:14px;margin-top:16px}
    .qe-card label{display:block;font-weight:700;margin-top:10px}
    .qe-card select{width:100%;margin:6px 0 10px;padding:10px;border:1px solid #d8c6a5;border-radius:8px;background:white}
    .qe-save-row{margin-top:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
    .qe-note{font-size:12px;color:#6b7280}
  `;
  document.head.appendChild(style);

  const backdrop=document.createElement('div');
  backdrop.className='qe-backdrop';
  backdrop.innerHTML=`<div class="qe-modal">
    <div class="qe-head"><div><h3>Categoria / Recorrência</h3><div id="qe-sub" class="muted"></div></div><button class="qe-close" type="button">×</button></div>
    <div class="qe-card">
      <form id="qe-combined" method="post">
        <label for="qe-category-select">Categoria</label>
        <select name="category" id="qe-category-select"></select>
        <div class="qe-note">Ao salvar a categoria, a classificação do DRE é atualizada automaticamente.</div>
        <label for="qe-recurring-select">Recorrência</label>
        <select name="recurring" id="qe-recurring-select">
          <option value="no">Não recorrente</option>
          <option value="yes">Recorrente</option>
        </select>
        <div class="qe-save-row"><button id="qe-save-btn" class="btn primary small" type="submit">Salvar categoria e recorrência</button></div>
      </form>
    </div>
  </div>`;
  document.body.appendChild(backdrop);

  const close=()=>backdrop.classList.remove('open');
  backdrop.querySelector('.qe-close').addEventListener('click',close);
  backdrop.addEventListener('click',e=>{if(e.target===backdrop) close();});

  const categorySelect=backdrop.querySelector('#qe-category-select');
  Object.entries(categoryGroups).forEach(([label,items])=>{
    const g=document.createElement('optgroup');g.label=label;
    items.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v.replace(/^[^:]+:\s*/,'');g.appendChild(o)});
    categorySelect.appendChild(g);
  });
  const other=document.createElement('option');other.value='Outros';other.textContent='Outros';categorySelect.appendChild(other);
  const recurringSelect=backdrop.querySelector('#qe-recurring-select');
  const form=backdrop.querySelector('#qe-combined');
  const saveBtn=backdrop.querySelector('#qe-save-btn');
  const buttonMap=new Map();
  const statusCache=new Map();

  async function loadStatus(id){
    if(statusCache.has(String(id))) return statusCache.get(String(id));
    const response=await fetch(`/conta/${id}/edicao-rapida-status`,{credentials:'same-origin'});
    if(!response.ok) throw new Error('status');
    const data=await response.json();
    statusCache.set(String(id),data);
    return data;
  }

  function applyButtonState(button,data){
    const categoryDone=!!(data.category && data.category.trim() && data.category.trim().toLowerCase()!=='outros');
    button.classList.toggle('done',categoryDone);
    button.classList.toggle('pending',!categoryDone);
    button.title=categoryDone?`Categoria definida: ${data.category}. Recorrência: ${data.recurring?'Sim':'Não'}`:'Categoria ainda não definida';
  }

  async function openEditor(id,button){
    let data;
    try{data=await loadStatus(id);}catch(e){alert('Não foi possível carregar os dados da conta.');return;}
    applyButtonState(button,data);
    backdrop.querySelector('#qe-sub').textContent=`${data.supplier||''} • ${data.description||''}`;

    if([...categorySelect.options].some(o=>o.value===data.category)) categorySelect.value=data.category;
    else {
      const custom=document.createElement('option');custom.value=data.category;custom.textContent=data.category||'Sem categoria';
      categorySelect.insertBefore(custom,categorySelect.firstChild);categorySelect.value=data.category;
    }
    recurringSelect.value=data.recurring?'yes':'no';
    form.dataset.accountId=id;
    form.dataset.currentRecurring=data.recurring?'yes':'no';
    backdrop.classList.add('open');
  }

  form.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const id=form.dataset.accountId;
    if(!id) return;
    const desiredRecurring=recurringSelect.value;
    const currentRecurring=form.dataset.currentRecurring;
    saveBtn.disabled=true;saveBtn.textContent='Salvando...';
    try{
      const categoryData=new FormData();
      categoryData.append('category',categorySelect.value);
      const categoryResponse=await fetch(`/conta/${id}/categoria-rapida`,{method:'POST',body:categoryData,credentials:'same-origin'});
      if(!categoryResponse.ok) throw new Error('categoria');

      if(desiredRecurring!==currentRecurring){
        const recurringResponse=await fetch(`/conta/${id}/recorrencia-rapida`,{method:'POST',body:new FormData(),credentials:'same-origin'});
        if(!recurringResponse.ok) throw new Error('recorrencia');
      }
      window.location.reload();
    }catch(e){
      saveBtn.disabled=false;saveBtn.textContent='Salvar categoria e recorrência';
      alert('Não foi possível salvar as alterações. Tente novamente.');
    }
  });

  accountLinks.forEach(link=>{
    const m=(link.getAttribute('href')||'').match(/\/conta\/(\d+)/); if(!m) return;
    const id=m[1];
    const actionWrap=link.closest('td')?.querySelector('div') || link.parentElement;
    if(!actionWrap || actionWrap.querySelector('.quick-combined-btn')) return;

    actionWrap.querySelectorAll('.quick-category-btn,.quick-dre-btn,.quick-recurring-btn').forEach(el=>el.remove());
    const button=document.createElement('button');
    button.type='button';button.className='btn small quick-action-btn quick-combined-btn pending';button.textContent='Categoria / Recorrência';
    button.addEventListener('click',()=>openEditor(id,button));
    actionWrap.appendChild(button);
    buttonMap.set(String(id),button);
  });

  const ids=[...buttonMap.keys()];
  if(ids.length){
    fetch(`/contas/edicao-rapida-status?ids=${encodeURIComponent(ids.join(','))}`,{credentials:'same-origin'})
      .then(r=>r.ok?r.json():Promise.reject())
      .then(data=>{
        Object.entries(data).forEach(([id,status])=>{
          statusCache.set(String(id),status);
          const button=buttonMap.get(String(id));
          if(button) applyButtonState(button,status);
        });
      })
      .catch(()=>{});
  }
});
