(function(){
  const scope=document.getElementById('reportScope');
  const form=document.getElementById('executiveReportFilters');
  const all=document.getElementById('reportAllProducts');
  const products=[...document.querySelectorAll('input[name="product_id"]')];
  const scopePanels=[...document.querySelectorAll('[data-scope-panel]')];
  const scopeCount=document.getElementById('reportScopeCount');

  function activeScopeInputs(){
    const selected=scope?.value||'national';
    return [...document.querySelectorAll('[data-scope-panel="'+selected+'"] input[name="scope_value"]')];
  }

  function updateScopeCount(){
    if(!scopeCount)return;
    if((scope?.value||'national')==='national'){
      scopeCount.textContent='Tüm kapsam';
      return;
    }
    const count=activeScopeInputs().filter(input=>input.checked).length;
    scopeCount.textContent=count?count+' seçili':'Tümü';
  }

  function syncScope(){
    const selected=scope?.value||'national';
    scopePanels.forEach(panel=>{
      const active=panel.dataset.scopePanel===selected;
      panel.hidden=!active;
      panel.querySelectorAll('input[name="scope_value"]').forEach(input=>{
        input.disabled=!active;
      });
    });
    updateScopeCount();
  }

  function normalizeSearch(value){
    return String(value||'').toLocaleLowerCase('tr-TR').trim();
  }

  document.querySelectorAll('[data-scope-search]').forEach(input=>{
    input.addEventListener('input',()=>{
      const type=input.dataset.scopeSearch;
      const query=normalizeSearch(input.value);
      document.querySelectorAll('[data-scope-option="'+type+'"]').forEach(option=>{
        option.hidden=Boolean(query&&!normalizeSearch(option.dataset.search).includes(query));
      });
    });
  });

  document.querySelectorAll('[data-scope-all]').forEach(button=>{
    button.addEventListener('click',()=>{
      const type=button.dataset.scopeAll;
      document.querySelectorAll('[data-scope-option="'+type+'"]:not([hidden]) input[name="scope_value"]').forEach(input=>input.checked=true);
      updateScopeCount();
    });
  });

  document.querySelectorAll('[data-scope-clear]').forEach(button=>{
    button.addEventListener('click',()=>{
      const type=button.dataset.scopeClear;
      document.querySelectorAll('[data-scope-option="'+type+'"] input[name="scope_value"]').forEach(input=>input.checked=false);
      updateScopeCount();
    });
  });

  document.querySelectorAll('input[name="scope_value"]').forEach(input=>{
    input.addEventListener('change',updateScopeCount);
  });

  function filenameFromDisposition(response,fallback){
    const disposition=response.headers.get('Content-Disposition')||'';
    const utf=disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if(utf){
      try{return decodeURIComponent(utf[1].replace(/["']/g,''));}catch(_error){}
    }
    const plain=disposition.match(/filename="?([^";]+)"?/i);
    return plain&&plain[1]?plain[1]:fallback;
  }

  async function saveBlobResponse(response,fallback){
    const blob=await response.blob();
    const filename=filenameFromDisposition(response,fallback);
    const objectUrl=URL.createObjectURL(blob);
    const download=document.createElement('a');
    download.href=objectUrl;
    download.download=filename;
    download.style.display='none';
    document.body.appendChild(download);
    download.click();
    download.remove();
    window.setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
  }

  function wait(ms){return new Promise(resolve=>window.setTimeout(resolve,ms));}

  async function pollExport(statusUrl,link,fallback){
    const deadline=Date.now()+180000;
    while(Date.now()<deadline){
      const response=await fetch(statusUrl,{credentials:'same-origin',headers:{'X-Requested-With':'fetch'}});
      if(!response.ok)throw new Error('Rapor durumu alınamadı.');
      const payload=await response.json();
      if(payload.status==='COMPLETED'&&payload.download_url){
        const fileResponse=await fetch(payload.download_url,{credentials:'same-origin',headers:{'X-Requested-With':'fetch'}});
        if(!fileResponse.ok)throw new Error('Hazırlanan rapor indirilemedi.');
        await saveBlobResponse(fileResponse,fallback);
        return;
      }
      if(payload.status==='FAILED')throw new Error(payload.error||'Rapor hazırlanamadı.');
      const position=payload.position?(' · sıra '+payload.position):'';
      link.dataset.exportStatus='Rapor hazırlanıyor'+position;
      await wait(750);
    }
    throw new Error('Rapor hazırlama süresi aşıldı. Lütfen tekrar deneyin.');
  }

  async function downloadReport(link){
    const params=new URLSearchParams(new FormData(form));
    const url=link.pathname+'?'+params.toString();
    const originalHtml=link.innerHTML;
    const fallback=link.pathname.endsWith('/pdf')
      ?'analiz-raporu.pdf'
      :(link.pathname.endsWith('/pptx')?'analiz-raporu.pptx':'analiz-raporu.xlsx');
    link.classList.add('disabled');
    link.setAttribute('aria-busy','true');
    link.innerHTML='<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Hazırlanıyor';
    try{
      const response=await fetch(url,{credentials:'same-origin',headers:{'X-Requested-With':'fetch'}});
      if(response.status===202){
        const payload=await response.json();
        if(!payload.status_url)throw new Error('Rapor kuyruğa alınamadı.');
        await pollExport(payload.status_url,link,fallback);
      }else{
        if(!response.ok)throw new Error('Rapor indirilemedi.');
        await saveBlobResponse(response,fallback);
      }
    }catch(error){
      window.alert(error&&error.message?error.message:'Rapor indirilemedi.');
    }finally{
      link.innerHTML=originalHtml;
      link.classList.remove('disabled');
      link.removeAttribute('aria-busy');
      delete link.dataset.exportStatus;
      if(window.IMSPageLoader&&typeof window.IMSPageLoader.finish==='function'){
        window.IMSPageLoader.finish();
      }
    }
  }

  scope?.addEventListener('change',syncScope);
  syncScope();

  all?.addEventListener('change',()=>{
    if(all.checked)products.forEach(item=>item.checked=false);
  });
  products.forEach(item=>item.addEventListener('change',()=>{
    if(item.checked)all.checked=false;
    if(!products.some(product=>product.checked))all.checked=true;
  }));

  document.querySelectorAll('.report-export').forEach(link=>{
    link.addEventListener('click',event=>{
      event.preventDefault();
      event.stopPropagation();
      downloadReport(link);
    });
  });
})();