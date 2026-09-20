(function () {
  "use strict";

  const nationalTrendValueLabels = {
    id: "nationalTrendValueLabels",
    afterDatasetsDraw(chart) {
      const dataset = chart.data.datasets[0];
      const meta = chart.getDatasetMeta(0);
      if (!dataset || !meta || meta.hidden) return;
      const dark = document.documentElement.dataset.theme === "dark";
      const ctx = chart.ctx;
      ctx.save();
      ctx.font = "700 11px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.fillStyle = dark ? "#f4f8fc" : "#173a55";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      meta.data.forEach((point, index) => {
        const value = dataset.data[index];
        if (value === null || value === undefined || Number.isNaN(Number(value))) return;
        ctx.fillText(`%${Number(value).toLocaleString("tr-TR", {maximumFractionDigits: 1})}`, point.x, point.y - 8);
      });
      ctx.restore();
    }
  };

  function initNationalTrend() {
    if (typeof Chart === "undefined") return;
    const canvas = document.querySelector("[data-exec-national-trend]");
    if (!canvas) return;
    Chart.getChart(canvas)?.destroy();
    let rows = [];
    try { rows = JSON.parse(canvas.dataset.rows || "[]"); } catch (_) { rows = []; }
    const dark = document.documentElement.dataset.theme === "dark";
    new Chart(canvas, {
      type: "line",
      data: {
        labels: rows.map(row => row.label),
        datasets: [{
          label: "National realizasyon",
          data: rows.map(row => row.has_data ? row.realization_percent : null),
          borderColor: dark ? "#65c2ff" : "#0b6db7",
          backgroundColor: dark ? "rgba(101,194,255,.18)" : "rgba(11,109,183,.12)",
          pointBackgroundColor: dark ? "#a4ddff" : "#0b6db7",
          pointBorderColor: dark ? "#13283c" : "#fff",
          pointBorderWidth: 2,
          borderWidth: 3,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: .28,
          spanGaps: false,
          fill: true
        }]
      },
      plugins: [nationalTrendValueLabels],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {padding: {top: 20, right: 8}},
        interaction: {mode: "index", intersect: false},
        plugins: {legend: {display: false}, tooltip: {callbacks: {label: context => `%${context.parsed.y}`}}},
        scales: {
          x: {grid: {display: false}, ticks: {color: dark ? "#cfdeea" : "#526b7e"}},
          y: {
            beginAtZero: true,
            suggestedMax: 120,
            grid: {color: dark ? "rgba(214,233,247,.14)" : "rgba(37,68,94,.10)"},
            ticks: {color: dark ? "#dce9f3" : "#526b7e", callback: value => `%${value}`}
          }
        }
      }
    });
  }
  function setPeriod(root, key) {
    root.querySelectorAll("[data-exec-period-button]").forEach(button => button.classList.toggle("active", button.dataset.execPeriodButton === key));
    root.querySelectorAll("[data-exec-period-panel]").forEach(panel => panel.classList.toggle("active", panel.dataset.execPeriodPanel === key));
  }
  function openRegion(regionKey) {
    const button = document.querySelector(`[data-manager-region-button="${regionKey}"]`);
    if (!button) return;
    button.click();
    document.querySelector(".manager-region-cockpit")?.scrollIntoView({behavior: "smooth", block: "start"});
  }
  document.addEventListener("click", event => {
    const root = event.target.closest?.("[data-exec-cockpit]");
    if (!root) return;
    const periodButton = event.target.closest("[data-exec-period-button]");
    if (periodButton) return setPeriod(root, periodButton.dataset.execPeriodButton);
    const region = event.target.closest("[data-exec-region-key]");
    if (region) return openRegion(region.dataset.execRegionKey);
    if (event.target.closest("[data-exec-jump-regions]")) document.querySelector(".manager-region-cockpit")?.scrollIntoView({behavior: "smooth", block: "start"});
  });
  document.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key)) return;
    const row = event.target.closest?.("[data-exec-region-key]");
    if (!row) return;
    event.preventDefault();
    openRegion(row.dataset.execRegionKey);
  });
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-exec-cockpit]").forEach(root => setPeriod(root, "monthly"));
    initNationalTrend();
    new MutationObserver(mutations => {
      if (mutations.some(item => item.attributeName === "data-theme")) initNationalTrend();
    }).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  });
})();
