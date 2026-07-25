/* PARÇA 1 BAŞLANGICI */

"use strict";

const Dashboard={

    charts:{},

    init(){

        this.initializeCharts();

        this.initializeCounters();

        this.initializeRefresh();

        this.initializeQuickActions();

        this.loadSummary();

    },

    initializeCharts(){

        this.renderPerformanceChart();

        this.renderGoalChart();

        this.renderRegionChart();

    },

    renderPerformanceChart(){

        const element=document.querySelector(

            "#dashboardPerformanceChart"

        );

        if(

            !element ||

            typeof ApexCharts==="undefined"

        ){

            return;

        }

        this.charts.performance=new ApexCharts(

            element,

            {

                chart:{

                    type:"area",

                    height:380,

                    toolbar:{

                        show:false

                    }

                },

                stroke:{

                    curve:"smooth",

                    width:3

                },

                dataLabels:{

                    enabled:false

                },

                series:[

                    {

                        name:"TL",

                        data:[

                            42,

                            51,

                            48,

                            59,

                            68,

                            73,

                            79,

                            84,

                            91,

                            96,

                            103,

                            112

                        ]

                    }

                ],

                xaxis:{

                    categories:[

                        "Oca",

                        "Şub",

                        "Mar",

                        "Nis",

                        "May",

                        "Haz",

                        "Tem",

                        "Ağu",

                        "Eyl",

                        "Eki",

                        "Kas",

                        "Ara"

                    ]

                }

            }

        );

        this.charts.performance.render();

    }
    /* PARÇA 1 BİTTİ */
    /* PARÇA 2 BAŞLANGICI */

    renderGoalChart(){

        const element=document.querySelector(

            "#goalChart"

        );

        if(

            !element ||

            typeof ApexCharts==="undefined"

        ){

            return;

        }

        this.charts.goal=new ApexCharts(

            element,

            {

                chart:{

                    type:"radialBar",

                    height:280

                },

                series:[82],

                labels:[

                    "Toplam Hedef"

                ],

                plotOptions:{

                    radialBar:{

                        hollow:{

                            size:"65%"

                        },

                        dataLabels:{

                            value:{

                                fontSize:"24px"

                            }

                        }

                    }

                }

            }

        );

        this.charts.goal.render();

    },

    renderRegionChart(){

        const element=document.querySelector(

            "#regionPerformanceChart"

        );

        if(

            !element ||

            typeof ApexCharts==="undefined"

        ){

            return;

        }

        this.charts.region=new ApexCharts(

            element,

            {

                chart:{

                    type:"bar",

                    height:340,

                    toolbar:{

                        show:false

                    }

                },

                series:[

                    {

                        name:"Gerçekleşme",

                        data:[

                            94,

                            88,

                            101,

                            97,

                            109,

                            92

                        ]

                    }

                ],

                xaxis:{

                    categories:[

                        "901",

                        "902",

                        "903",

                        "904",

                        "905",

                        "906"

                    ]

                },

                dataLabels:{

                    enabled:false

                }

            }

        );

        this.charts.region.render();

    },

    initializeCounters(){

        document

        .querySelectorAll(

            ".display-5,.display-6"

        )

        .forEach(

            element=>{

                element.classList.add(

                    "fade-in"

                );

            }

        );

    },

    initializeQuickActions(){

        document

        .querySelectorAll(

            ".btn"

        )

        .forEach(

            button=>{

                button.addEventListener(

                    "click",

                    function(){

                        this.blur();

                    }

                );

            }

        );

    },

    loadSummary(){

        console.log(

            "Dashboard özeti yüklendi."

        );

    },
    /* PARÇA 2 BİTTİ */
    /* PARÇA 3 BAŞLANGICI */

    initializeRefresh(){

        setInterval(

            ()=>{

                this.refreshDashboard();

            },

            300000

        );

    },

    async refreshDashboard(){

        try{

            console.log(

                "Dashboard yenileniyor..."

            );

            const response=await fetch(

                "/dashboard/health"

            );

            if(

                response.ok

            ){

                console.log(

                    "Dashboard güncellendi."

                );

            }

        }

        catch(

            error

        ){

            console.error(

                error

            );

        }

    }

};

document.addEventListener(

    "DOMContentLoaded",

    function(){

        Dashboard.init();

    }

);

window.Dashboard=Dashboard;

/* PARÇA 3 BİTTİ */

/* DOSYA TAMAMLANDI */
