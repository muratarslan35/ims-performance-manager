(function () {
  "use strict";

  let activePeriod = "monthly";
  let loadSequence = 0;
  const regionHtmlCache = new Map();
  const regionInflight = new Map();
  let regionPackPromise = null;
  let regionPackReady = false;

  function initAnnualChart(root) {
    if (typeof Chart === "undefined") return;
    const canvas = root.querySelector("[data-manager-annual-chart]");
    if (!canvas) return;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    let rows = [];
    try { rows = JSON.parse(canvas.dataset.rows || "[]"); } catch (_) { rows = []; }

    const labelsPlugin = {
      id: "managerAnnualLabels",
      afterDatasetsDraw(chart) {
        const ctx = chart.ctx;
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

    new Chart(canvas, {
      type: "line",
      data: {
        labels: rows.map(item => item.label),
        datasets: [{
          data: rows.map(item => item.has_data ? item.percent : null),
          borderColor: "#b77900",
          backgroundColor: "rgba(244,163,0,.16)",
          pointBackgroundColor: "#f4a300",
          pointBorderColor: "#fff",
          pointBorderWidth: 2,
          pointRadius: 5,
          borderWidth: 2,
          fill: true,
          tension: .28,
          spanGaps: false
        }]
      },
      plugins: [labelsPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {padding: {top: 24, right: 12}},
        plugins: {legend: {display: false}},
        scales: {
          x: {offset: true, grid: {display: false}, ticks: {color: "#5f748b", font: {weight: "600"}}},
          y: {beginAtZero: true, suggestedMax: 120, ticks: {callback: value => `%${value}`, color: "#71859b"}, grid: {color: "rgba(18,62,112,.08)"}}
        }
      }
    });
  }

  function applyPeriod(root) {
    root.querySelectorAll("[data-manager-period-panel]").forEach(panel => {
      panel.classList.toggle("active", panel.dataset.managerPeriodPanel === activePeriod);
    });
    document.querySelectorAll("[data-manager-period-button]").forEach(button => {
      button.classList.toggle("active", button.dataset.managerPeriodButton === activePeriod);
    });
  }

  function activateSibling(button, buttonSelector, paneSelector, valueAttr, paneAttr) {
    const scope = button.closest(".manager-region-snapshot") || document;
    const value = button.dataset[valueAttr];
    scope.querySelectorAll(buttonSelector).forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    scope.querySelectorAll(paneSelector).forEach(pane => {
      pane.classList.toggle("active", pane.dataset[paneAttr] === value);
    });
  }

  function fetchRegionHtml(url) {
    if (regionHtmlCache.has(url)) return Promise.resolve(regionHtmlCache.get(url));
    if (regionInflight.has(url)) return regionInflight.get(url);

    const request = fetch(url, {
      headers: {"X-Requested-With": "fetch"},
      credentials: "same-origin"
    }).then(async response => {
      const html = await response.text();
      if (!response.ok) throw new Error(html || "Bölge verisi yüklenemedi");
      regionHtmlCache.set(url, html);
      return html;
    }).finally(() => regionInflight.delete(url));

    regionInflight.set(url, request);
    return request;
  }

  function hydratePack(pack) {
    if (!pack || !pack.ready || !pack.regions) return false;
    document.querySelectorAll("[data-manager-region-button]").forEach(button => {
      const regionKey = button.dataset.managerRegionButton;
      const html = pack.regions[regionKey];
      if (html && button.dataset.url) regionHtmlCache.set(button.dataset.url, html);
    });
    regionPackReady = true;
    document.documentElement.dataset.managerRegionPack = "ready";
    return true;
  }

  function ensureRegionPack() {
    if (regionPackReady) return Promise.resolve(true);
    if (regionPackPromise) return regionPackPromise;
    const cockpit = document.querySelector(".manager-region-cockpit[data-region-pack-url]");
    if (!cockpit || !cockpit.dataset.regionPackUrl) return Promise.resolve(false);

    regionPackPromise = fetch(cockpit.dataset.regionPackUrl, {
      headers: {"X-Requested-With": "fetch"},
      credentials: "same-origin",
      cache: "no-store"
    }).then(async response => {
      if (!response.ok) return false;
      const pack = await response.json();
      return hydratePack(pack);
    }).catch(() => false).finally(() => {
      if (!regionPackReady) regionPackPromise = null;
    });
    return regionPackPromise;
  }

  function renderRegion(target, html) {
    target.innerHTML = html;
    applyPeriod(target);
    initAnnualChart(target);
  }

  async function loadRegion(button) {
    const target = document.getElementById("managerRegionSnapshotHost");
    if (!target || button.classList.contains("active")) return;
    const sequence = ++loadSequence;
    document.querySelectorAll("[data-manager-region-button]").forEach(item => item.classList.remove("active"));
    button.classList.add("active");

    let cached = regionHtmlCache.get(button.dataset.url);
    if (!cached) {
      await ensureRegionPack();
      cached = regionHtmlCache.get(button.dataset.url);
    }
    if (sequence !== loadSequence) return;
    if (cached) {
      renderRegion(target, cached);
      return;
    }

    target.innerHTML = '<div class="manager-region-loading"><span class="spinner-border spinner-border-sm me-2"></span>Bölge verisi hazırlanıyor…</div>';
    try {
      const html = await fetchRegionHtml(button.dataset.url);
      if (sequence !== loadSequence) return;
      renderRegion(target, html);
    } catch (error) {
      if (sequence !== loadSequence) return;
      target.innerHTML = '<div class="manager-region-empty"><i class="bi bi-exclamation-triangle"></i><strong>Bölge verisi yüklenemedi</strong><span>Tekrar deneyin.</span></div>';
    }
  }

  document.addEventListener("pointerenter", event => {
    const button = event.target.closest && event.target.closest("[data-manager-region-button]");
    if (button) ensureRegionPack();
  }, true);

  document.addEventListener("focusin", event => {
    const button = event.target.closest && event.target.closest("[data-manager-region-button]");
    if (button) ensureRegionPack();
  });

  document.addEventListener("click", event => {
    const regionButton = event.target.closest("[data-manager-region-button]");
    if (regionButton) { loadRegion(regionButton); return; }

    const periodButton = event.target.closest("[data-manager-period-button]");
    if (periodButton) {
      activePeriod = periodButton.dataset.managerPeriodButton;
      const host = document.getElementById("managerRegionSnapshotHost");
      if (host) applyPeriod(host);
      return;
    }

    const productButton = event.target.closest("[data-market-product-tab]");
    if (productButton) {
      activateSibling(productButton, "[data-market-product-tab]", "[data-market-product-pane]", "marketProductTab", "marketProductPane");
      return;
    }

    const groupButton = event.target.closest("[data-rival-group-tab]");
    if (groupButton) {
      const scope = groupButton.closest(".manager-region-snapshot");
      const value = groupButton.dataset.rivalGroupTab;
      scope.querySelectorAll("[data-rival-group-tab]").forEach(item => item.classList.remove("active"));
      groupButton.classList.add("active");
      scope.querySelectorAll("[data-rival-product-nav]").forEach(nav => nav.classList.toggle("active", nav.dataset.rivalProductNav === value));
      const first = scope.querySelector(`[data-rival-product-nav="${value}"] [data-rival-product-tab]`);
      if (first) first.click();
      return;
    }

    const rivalButton = event.target.closest("[data-rival-product-tab]");
    if (rivalButton) {
      const scope = rivalButton.closest(".manager-region-snapshot");
      const value = rivalButton.dataset.rivalProductTab;
      scope.querySelectorAll("[data-rival-product-tab]").forEach(item => item.classList.remove("active"));
      rivalButton.classList.add("active");
      scope.querySelectorAll("[data-rival-pane]").forEach(pane => pane.classList.toggle("active", pane.dataset.rivalPane === value));
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    const host = document.getElementById("managerRegionSnapshotHost");
    if (!host) return;
    const activeButton = document.querySelector("[data-manager-region-button].active");
    if (activeButton && activeButton.dataset.url && host.querySelector(".manager-region-snapshot")) {
      regionHtmlCache.set(activeButton.dataset.url, host.innerHTML);
    }
    applyPeriod(host);
    initAnnualChart(host);
    // One background request warms every region. No per-region prefetch fan-out.
    ensureRegionPack();
  });
})();
