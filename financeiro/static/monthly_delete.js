document.addEventListener('DOMContentLoaded',()=>{
  const accountLinks=[...document.querySelectorAll('a[href*="/conta/"]')]
    .filter(a=>/\/conta\/\d+/.test(a.getAttribute('href')||''));

  accountLinks.forEach(link=>{
    const match=(link.getAttribute('href')||'').match(/\/conta\/(\d+)/);
    if(!match) return;

    const accountId=match[1];
    const row=link.closest('tr');
    const actionWrap=link.closest('td')?.querySelector('div') || link.parentElement;
    if(!actionWrap || actionWrap.querySelector('.delete-month-btn')) return;

    let reference='esta competência';
    if(row){
      const cells=row.querySelectorAll('td');
      const dueText=(cells[2]?.textContent||'').trim();
      const parts=dueText.split('/');
      if(parts.length===3) reference=`${parts[1]}/${parts[2]}`;
    }

    const button=document.createElement('button');
    button.type='button';
    button.className='btn small delete-month-btn';
    button.textContent='🗑 Excluir mês';
    button.style.background='#7f1d1d';
    button.style.color='#fff';
    button.style.borderColor='#7f1d1d';

    button.addEventListener('click',async()=>{
      const message=`Excluir somente a conta de ${reference}?\n\nA recorrência e as contas dos outros meses serão mantidas. Se houver pagamento lançado nesta conta, ele também será removido.`;
      if(!confirm(message)) return;

      const original=button.textContent;
      button.disabled=true;
      button.textContent='Excluindo...';

      try{
        const response=await fetch(`/conta/${accountId}/excluir-mes`,{
          method:'POST',
          credentials:'same-origin',
          headers:{'X-Requested-With':'XMLHttpRequest'}
        });
        const data=await response.json().catch(()=>({}));
        if(!response.ok || data.ok===false) throw new Error(data.error||'Falha ao excluir');
        window.location.reload();
      }catch(error){
        button.disabled=false;
        button.textContent=original;
        alert('Não foi possível excluir esta conta. Tente novamente.');
      }
    });

    actionWrap.appendChild(button);
  });
});
