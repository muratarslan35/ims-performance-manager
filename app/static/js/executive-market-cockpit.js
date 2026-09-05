(function () {
  "use strict";

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
      options: {
        responsive: true,
        maintainAspectRatio: false,
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
