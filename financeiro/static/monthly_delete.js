document.addEventListener('DOMContentLoaded',()=>{
  const accountLinks=[...document.querySelectorAll('a[href*="/conta/"]')]
    .filter(a=>/\/conta\/\d+/.test(a.getAttribute('href')||''));

  accountLinks.forEach(link=>{
    const match=(link.getAttribute('href')||'').match(/\/conta\/(\d+)/);
    if(!match) return;

    const accountId=match[1];
    const actionWrap=link.closest('td')?.querySelector('div') || link.parentElement;
    if(!actionWrap || actionWrap.querySelector('.delete-system-account-btn')) return;

    const button=document.createElement('button');
    button.type='button';
    button.className='btn small delete-system-account-btn';
    button.textContent='🗑 Excluir esta conta do sistema';
    button.style.background='#7f1d1d';
    button.style.color='#fff';
    button.style.borderColor='#7f1d1d';

    button.addEventListener('click',async()=>{
      const message='Tem certeza que deseja excluir esta conta do sistema?\n\nEsta ação removerá a conta e seus lançamentos vinculados e não poderá ser desfeita. Se a conta for recorrente, todos os meses vinculados à mesma recorrência também serão excluídos.';
      if(!confirm(message)) return;

      const original=button.textContent;
      button.disabled=true;
      button.textContent='Excluindo...';

      try{
        const response=await fetch(`/conta/${accountId}/excluir-sistema`,{
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
        alert('Não foi possível excluir esta conta do sistema. Tente novamente.');
      }
    });

    actionWrap.appendChild(button);
  });
});
