document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll("[data-scope-ai]").forEach(root=>root.querySelectorAll("[data-scope-ai-tab]").forEach(button=>button.addEventListener("click",()=>{root.querySelectorAll("[data-scope-ai-tab]").forEach(item=>item.classList.toggle("active",item===button));root.querySelectorAll("[data-scope-ai-panel]").forEach(panel=>panel.classList.toggle("active",panel.dataset.scopeAiPanel===button.dataset.scopeAiTab));})));

  const table=document.querySelector(".trend-analysis-table");
  if(!table)return;

  const headers=table.querySelectorAll("thead th");
  if(headers.length>=7){
    headers[3].textContent="Şirket kutu farkı";
    headers[4].textContent="Şirket değişim %";
    headers[5].textContent="Rakip kutu farkı";
  }

  const formatTurkishInteger=value=>{
    const normalized=String(value||"").trim().replace(/[^0-9+\-]/g,"");
    if(!normalized||normalized==="+"||normalized==="-")return String(value||"").trim();
    const sign=normalized.startsWith("-")?"-":normalized.startsWith("+")?"+":"";
    const digits=normalized.replace(/[+\-]/g,"");
    return `${sign}${digits.replace(/\B(?=(\d{3})+(?!\d))/g,".")}`;
  };

  table.querySelectorAll("tbody tr").forEach(row=>{
    const cells=row.querySelectorAll("td");
    if(cells.length<7)return;

    const companyPill=cells[3].querySelector(".trend-pill");
    if(companyPill){
      const arrow=companyPill.textContent.includes("▼")?"▼":companyPill.textContent.includes("▲")?"▲":"—";
      const number=formatTurkishInteger(companyPill.textContent);
      companyPill.textContent=`${arrow} Şirket ${number} kutu`;
      companyPill.setAttribute("aria-label",`Şirket kutu farkı ${number} kutu`);
    }

    const rivalPill=cells[5].querySelector(".trend-pill");
    if(rivalPill){
      const arrow=rivalPill.textContent.includes("▼")?"▼":rivalPill.textContent.includes("▲")?"▲":"—";
      const number=formatTurkishInteger(rivalPill.textContent);
      rivalPill.textContent=`${arrow} Rakip ${number} kutu`;
      rivalPill.setAttribute("aria-label",`Rakip kutu farkı ${number} kutu`);
    }
  });
});
