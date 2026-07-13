/* PARÇA 1 BAŞLANGICI */

"use strict";

const App={

    init(){

        this.initializeTooltips();

        this.initializePopovers();

        this.initializeSearch();

        this.initializeTables();

        this.initializeAnimations();

        this.initializeAutoDismissAlerts();

    },

    initializeTooltips(){

        document

        .querySelectorAll(

            '[data-bs-toggle="tooltip"]'

        )

        .forEach(

            element=>{

                new bootstrap.Tooltip(

                    element

                );

            }

        );

    },

    initializePopovers(){

        document

        .querySelectorAll(

            '[data-bs-toggle="popover"]'

        )

        .forEach(

            element=>{

                new bootstrap.Popover(

                    element

                );

            }

        );

    },

    initializeSearch(){

        document

        .querySelectorAll(

            'input[type="search"]'

        )

        .forEach(

            input=>{

                input.addEventListener(

                    "keyup",

                    function(){

                        const keyword=this.value

                        .toLowerCase();

                        const table=this

                        .closest(

                            ".card"

                        )

                        ?.querySelector(

                            "tbody"

                        );

                        if(!table){

                            return;

                        }

                        table

                        .querySelectorAll(

                            "tr"

                        )

                        .forEach(

                            row=>{

                                row.style.display=

                                row.innerText

                                .toLowerCase()

                                .includes(

                                    keyword

                                )

                                ?

                                ""

                                :

                                "none";

                            }

                        );

                    }

                );

            }

        );

    },

    initializeTables(){

        document

        .querySelectorAll(

            ".datatable"

        )

        .forEach(

            table=>{

                table.classList.add(

                    "table-hover"

                );

            }

        );

    },

    initializeAnimations(){

        document

        .querySelectorAll(

            ".card"

        )

        .forEach(

            (

                card,

                index

            )=>{

                card.style.animationDelay=

                (index*0.05)+"s";

            }

        );

    },

    initializeAutoDismissAlerts(){

        setTimeout(

            ()=>{

                document

                .querySelectorAll(

                    ".alert"

                )

                .forEach(

                    alert=>{

                        alert.classList.add(

                            "fade"

                        );

                        setTimeout(

                            ()=>{

                                alert.remove();

                            },

                            400

                        );

                    }

                );

            },

            4000

        );

    }

};

/* PARÇA 1 BİTTİ */
/* PARÇA 2 BAŞLANGICI */

function showLoading(

    message="Yükleniyor..."

){

    let overlay=document.getElementById(

        "loadingOverlay"

    );

    if(!overlay){

        overlay=document.createElement(

            "div"

        );

        overlay.id="loadingOverlay";

        overlay.className="loading-overlay show";

        overlay.innerHTML=`

<div class="text-center">

<div class="loading-spinner"></div>

<div class="mt-3 fw-bold">

${message}

</div>

</div>

`;

        document.body.appendChild(

            overlay

        );

    }

    else{

        overlay.classList.add(

            "show"

        );

        overlay.querySelector(

            ".fw-bold"

        ).innerText=message;

    }

}

function hideLoading(){

    const overlay=document.getElementById(

        "loadingOverlay"

    );

    if(

        overlay

    ){

        overlay.classList.remove(

            "show"

        );

    }

}

function showToast(

    title,

    message,

    type="success"

){

    const toast=document.createElement(

        "div"

    );

    toast.className=`toast show position-fixed top-0 end-0 m-3 bg-${type} text-white`;

    toast.style.zIndex=9999;

    toast.innerHTML=`

<div class="toast-header">

<strong class="me-auto">

${title}

</strong>

<button

type="button"

class="btn-close"

></button>

</div>

<div class="toast-body">

${message}

</div>

`;

    document.body.appendChild(

        toast

    );

    toast

    .querySelector(

        ".btn-close"

    )

    .addEventListener(

        "click",

        ()=>toast.remove()

    );

    setTimeout(

        ()=>toast.remove(),

        3500

    );

}

async function apiRequest(

    url,

    method="GET",

    data=null

){

    showLoading();

    try{

        const response=await fetch(

            url,

            {

                method:method,

                headers:{

                    "Content-Type":"application/json"

                },

                body:data?

                JSON.stringify(

                    data

                ):null

            }

        );

        const result=await response.json();

        hideLoading();

        return result;

    }

    catch(

        error

    ){

        hideLoading();

        showToast(

            "Hata",

            error,

            "danger"

        );

        throw error;

    }

}

function formatCurrency(

    value

){

    return Number(

        value

    ).toLocaleString(

        "tr-TR",

        {

            minimumFractionDigits:2,

            maximumFractionDigits:2

        }

    )+" ₺";

}

function formatPercent(

    value

){

    return Number(

        value

    ).toFixed(

        2

    )+"%";

}

/* PARÇA 2 BİTTİ */
/* PARÇA 3 BAŞLANGICI */

function validateForm(

    form

){

    let valid=true;

    form.querySelectorAll(

        "[required]"

    ).forEach(

        field=>{

            if(

                field.value.trim()===""

            ){

                field.classList.add(

                    "is-invalid"

                );

                valid=false;

            }

            else{

                field.classList.remove(

                    "is-invalid"

                );

            }

        }

    );

    return valid;

}

function confirmDelete(

    message="Kayıt silinsin mi?"

){

    return confirm(

        message

    );

}

function refreshPage(

    delay=1000

){

    setTimeout(

        ()=>{

            location.reload();

        },

        delay

    );

}

function scrollTopPage(){

    window.scrollTo(

        {

            top:0,

            behavior:"smooth"

        }

    );

}

function setButtonLoading(

    button,

    loading=true

){

    if(

        loading

    ){

        button.dataset.oldText=

        button.innerHTML;

        button.disabled=true;

        button.innerHTML=`

<span

class="spinner-border spinner-border-sm me-2">

</span>

Yükleniyor...

`;

    }

    else{

        button.disabled=false;

        button.innerHTML=

        button.dataset.oldText;

    }

}

document

.querySelectorAll(

    "form"

)

.forEach(

    form=>{

        form.addEventListener(

            "submit",

            function(

                e

            ){

                if(

                    !validateForm(

                        this

                    )

                ){

                    e.preventDefault();

                    showToast(

                        "Eksik Bilgi",

                        "Lütfen zorunlu alanları doldurun.",

                        "warning"

                    );

                    return;

                }

                const submit=this.querySelector(

                    "button[type='submit']"

                );

                if(

                    submit

                ){

                    setButtonLoading(

                        submit,

                        true

                    );

                }

            }

        );

    }

);

window.addEventListener(

    "scroll",

    function(){

        document.body.classList.toggle(

            "scrolled",

            window.scrollY>25

        );

    }

);

/* PARÇA 3 BİTTİ */
/* PARÇA 4 BAŞLANGICI */

function initializeCharts(){

    if(

        typeof ApexCharts==="undefined"

    ){

        return;

    }

}

function initializeDashboard(){

    const cards=document.querySelectorAll(

        ".dashboard-card"

    );

    cards.forEach(

        card=>{

            card.addEventListener(

                "mouseenter",

                function(){

                    this.style.transform="translateY(-4px)";

                }

            );

            card.addEventListener(

                "mouseleave",

                function(){

                    this.style.transform="";

                }

            );

        }

    );

}

function initializeSidebar(){

    const current=window.location.pathname;

    document

    .querySelectorAll(

        ".navbar .nav-link,.navbar-vertical .nav-link"

    )

    .forEach(

        link=>{

            const href=link.getAttribute(

                "href"

            );

            if(

                href &&

                current.startsWith(

                    href

                ) &&

                href!=="/"

            ){

                link.classList.add(

                    "active"

                );

            }

        }

    );

}

function initializeNumbers(){

    document

    .querySelectorAll(

        "[data-currency]"

    )

    .forEach(

        element=>{

            element.innerHTML=

            formatCurrency(

                element.dataset.currency

            );

        }

    );

    document

    .querySelectorAll(

        "[data-percent]"

    )

    .forEach(

        element=>{

            element.innerHTML=

            formatPercent(

                element.dataset.percent

            );

        }

    );

}

document.addEventListener(

    "DOMContentLoaded",

    function(){

        App.init();

        initializeCharts();

        initializeDashboard();

        initializeSidebar();

        initializeNumbers();

    }

);

window.showLoading=showLoading;

window.hideLoading=hideLoading;

window.showToast=showToast;

window.apiRequest=apiRequest;

window.formatCurrency=formatCurrency;

window.formatPercent=formatPercent;

window.refreshPage=refreshPage;

window.scrollTopPage=scrollTopPage;

window.confirmDelete=confirmDelete;

/* PARÇA 4 BİTTİ */

/* DOSYA TAMAMLANDI */
