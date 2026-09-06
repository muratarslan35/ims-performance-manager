(function () {
  "use strict";

  const trendValueLabels = {
    id: "execTrendValueLabels",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      const dataset = chart.data.datasets[0];
      const meta = chart.getDatasetMeta(0);
      if (!dataset || !meta || meta.hidden) return;

      ctx.save();
      ctx.font = "700 11px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.fillStyle = "#173a55";
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

  function initTrend(root) {
    if (!root || typeof Chart === "undefined") return;
    const canvas = root.querySelector("[data-exec-trend]");
    if (!canvas) return;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    let rows = [];
    try { rows = JSON.parse(canvas.dataset.rows || "[]"); } catch (_) { rows = []; }
    new Chart(canvas, {
      type: "line",
      data: {
        labels: rows.map(row => row.label),
        datasets: [{
          label: "Türkiye realizasyonu",
          data: rows.map(row => row.has_data ? row.realization_percent : null),
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: .28,
          spanGaps: false,
          fill: true
        }]
      },
      plugins: [trendValueLabels],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {padding: {top: 18}},
        interaction: {mode: "index", intersect: false},
        plugins: {legend: {display: false}, tooltip: {callbacks: {label: context => `%${context.parsed.y}`}}},
        scales: {
          x: {grid: {display: false}},
          y: {beginAtZero: true, suggestedMax: 120, ticks: {callback: value => `%${value}`}}
        }
      }
    });
  }

  function setPeriod(root, key) {
    root.querySelectorAll("[data-exec-period-button]").forEach(button => {
      button.classList.toggle("active", button.dataset.execPeriodButton === key);
    });
    root.querySelectorAll("[data-exec-period-panel]").forEach(panel => {
      panel.classList.toggle("active", panel.dataset.execPeriodPanel === key);
    });
    root.querySelectorAll("[data-exec-ai-panel]").forEach(panel => {
      panel.classList.toggle("active", panel.dataset.execAiPanel === key);
    });
  }

  function openRegion(regionKey) {
    const button = document.querySelector(`[data-manager-region-button="${regionKey}"]`);
    if (button) {
      button.click();
      const cockpit = document.querySelector(".manager-region-cockpit");
      if (cockpit) cockpit.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }

  document.addEventListener("click", event => {
    const root = event.target.closest && event.target.closest("[data-exec-cockpit]");
    if (!root) return;

    const periodButton = event.target.closest("[data-exec-period-button]");
    if (periodButton) {
      setPeriod(root, periodButton.dataset.execPeriodButton);
      return;
    }

    const region = event.target.closest("[data-exec-region-key]");
    if (region) {
      openRegion(region.dataset.execRegionKey);
      return;
    }

    const jump = event.target.closest("[data-exec-jump-regions]");
    if (jump) {
      const cockpit = document.querySelector(".manager-region-cockpit");
      if (cockpit) cockpit.scrollIntoView({behavior: "smooth", block: "start"});
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-exec-cockpit]").forEach(root => {
      setPeriod(root, "monthly");
      initTrend(root);
    });
  });
})();
