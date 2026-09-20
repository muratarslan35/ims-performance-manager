(function(){
  const scope=document.getElementById('reportScope');const value=document.getElementById('reportScopeValue');
  const all=document.getElementById('reportAllProducts');const products=[...document.querySelectorAll('input[name="product_id"]')];
  function syncScope(){const selected=scope.value;[...value.options].forEach(option=>{option.hidden=Boolean(option.dataset.scope&&option.dataset.scope!==selected);});value.disabled=selected==='national';if(selected==='national')value.value='';else if(![...value.selectedOptions].some(option=>!option.hidden))value.value='';document.getElementById('scopeValueLabel').textContent={region:'Bölge',city:'İl',representative:'Temsilci'}[selected]||'Kapsam';}
  scope?.addEventListener('change',syncScope);syncScope();
  all?.addEventListener('change',()=>{if(all.checked)products.forEach(item=>item.checked=false);});products.forEach(item=>item.addEventListener('change',()=>{if(item.checked)all.checked=false;if(!products.some(product=>product.checked))all.checked=true;}));
  document.querySelectorAll('.report-export').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();const params=new URLSearchParams(new FormData(document.getElementById('executiveReportFilters')));window.location.href=link.pathname+'?'+params.toString();}));
})();
