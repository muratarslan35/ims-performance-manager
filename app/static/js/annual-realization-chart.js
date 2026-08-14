(function () {
  "use strict";

  const valueLabels = {
    id: "annualRealizationValueLabels",
    afterDatasetsDraw(chart) {
      const {ctx} = chart;
      ctx.save();
      ctx.fillStyle = "#7a5200";
      ctx.font = "700 11px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      chart.getDatasetMeta(0).data.forEach((point, index) => {
        const value = chart.data.datasets[0].data[index];
        if (value === null || value === undefined) return;
        ctx.fillText(`%${Number(value).toLocaleString("tr-TR", {maximumFractionDigits: 1})}`, point.x, point.y - 8);
      });
      ctx.restore();
    }
  };

  document.querySelectorAll("[data-annual-realization-chart]").forEach(canvas => {
    if (typeof Chart === "undefined") return;
    const rows = JSON.parse(canvas.dataset.rows || "[]");
    new Chart(canvas, {
      type: "line",
      data: {
        labels: rows.map(item => item.label),
        datasets: [{
          label: "Aylık toplam realizasyon",
          data: rows.map(item => item.has_data ? item.percent : null),
          borderColor: "#b77900",
          backgroundColor: "rgba(244,163,0,.16)",
          pointBackgroundColor: "#f4a300",
          pointBorderColor: "#fff",
          pointBorderWidth: 2,
          pointRadius: 5,
          pointHoverRadius: 7,
          borderWidth: 2,
          fill: true,
          tension: .28,
          spanGaps: false
        }]
      },
      plugins: [valueLabels],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {padding: {top: 24, right: 12}},
        plugins: {
          legend: {display: false},
          tooltip: {callbacks: {label(context) {return context.raw === null ? " Veri yok" : ` Realizasyon: %${Number(context.raw).toLocaleString("tr-TR")}`;}}}
        },
        scales: {
          x: {offset: true, grid: {display: false}, ticks: {color: "#5f748b", font: {weight: "600"}}},
          y: {beginAtZero: true, suggestedMax: 120, ticks: {callback: value => `%${value}`, color: "#71859b"}, grid: {color: "rgba(18,62,112,.08)"}}
        }
      }
    });
  });
})();
