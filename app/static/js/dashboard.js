"use strict";

const CORP_COLORS = ["#0B4EA2", "#2D7FF9", "#18B368", "#F4A300", "#6B5BFF", "#E34B4B", "#00B8C4", "#F47C20", "#3B82F6", "#A855F7"];
const CHARTS = {};
let dashboardDataCache = null;

function getDashboardData() {
  if (dashboardDataCache) return dashboardDataCache;
  const el = document.getElementById("dashboardData");
  if (!el) return null;
  try {
    dashboardDataCache = JSON.parse(el.textContent);
    return dashboardDataCache;
  } catch (err) {
    console.error("Dashboard verisi okunamadı:", err);
    return null;
  }
}

function destroyChart(key) {
  if (CHARTS[key]) {
    CHARTS[key].destroy();
    CHARTS[key] = null;
  }
}

function createVerticalGradient(ctx, top, bottom) {
  const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
  gradient.addColorStop(0, top);
  gradient.addColorStop(1, bottom);
  return gradient;
}

function numberTR(value, suffix = "") {
  const safeValue = Number(value || 0);
  return `${safeValue.toLocaleString("tr-TR")}${suffix}`;
}

function defaultTooltip() {
  return {
    backgroundColor: "rgba(11, 34, 67, .95)",
    titleColor: "#fff",
    bodyColor: "#fff",
    borderColor: "rgba(255,255,255,.12)",
    borderWidth: 1,
    cornerRadius: 10,
    padding: 10,
    displayColors: true,
    boxPadding: 4
  };
}

function chartPlaceholderMarkup(icon) {
  return `<div class="chart-placeholder"><i class="bi ${icon}"></i><div class="chart-placeholder-title">Veri bekleniyor</div><div class="chart-placeholder-sub">Henüz IMS verisi yüklenmedi</div></div><div class="chart-skeleton"><div class="chart-skeleton-bar"></div><div class="chart-skeleton-bar"></div><div class="chart-skeleton-bar"></div><div class="chart-skeleton-bar"></div></div>`;
}

function initMonthlyTrend(data) {
  const canvas = document.getElementById("monthlyTrendChart");
  if (!canvas || typeof Chart === "undefined" || !data || !Array.isArray(data.labels) || !data.labels.length) return;

  destroyChart("monthlyTrend");
  const ctx = canvas.getContext("2d");
  const gradReal = createVerticalGradient(ctx, "rgba(11, 78, 162, .35)", "rgba(11, 78, 162, .02)");
  const gradTarget = createVerticalGradient(ctx, "rgba(244, 163, 0, .22)", "rgba(244, 163, 0, .01)");

  CHARTS.monthlyTrend = new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Gerçekleşen",
          data: data.realization || [],
          borderColor: "#0B4EA2",
          backgroundColor: gradReal,
          fill: true,
          borderWidth: 2.8,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.42,
          cubicInterpolationMode: "monotone"
        },
        {
          label: "Hedef",
          data: data.target || [],
          borderColor: "#F4A300",
          backgroundColor: gradTarget,
          fill: true,
          borderWidth: 2.2,
          borderDash: [6, 5],
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.42,
          cubicInterpolationMode: "monotone"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      animation: { duration: 1100, easing: "easeOutQuart" },
      plugins: {
        legend: {
          position: "top",
          labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 7, padding: 14, font: { size: 12, weight: "600" } }
        },
        tooltip: {
          ...defaultTooltip(),
          callbacks: {
            label(ctx) {
              return ` ${ctx.dataset.label}: ${numberTR(ctx.parsed.y, " ₺")}`;
            }
          }
        }
      },
      scales: {
        x: { grid: { color: "rgba(13, 43, 83, .05)", drawBorder: false }, ticks: { color: "#6F8198" } },
        y: {
          grid: { color: "rgba(13, 43, 83, .05)", drawBorder: false },
          ticks: {
            color: "#6F8198",
            callback(v) {
              return `${Math.round(Number(v) / 1000)}K ₺`;
            }
          }
        }
      }
    }
  });
}

function initMarketShare(data) {
  const canvas = document.getElementById("marketShareChart");
  if (!canvas || typeof Chart === "undefined" || !data || !Array.isArray(data.labels) || !data.labels.length) return;

  destroyChart("marketShare");
  const ctx = canvas.getContext("2d");
  const grad = createVerticalGradient(ctx, "rgba(24, 179, 104, .30)", "rgba(24, 179, 104, .03)");

  CHARTS.marketShare = new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [{
        label: "Pazar Payı",
        data: data.values || [],
        borderColor: "#18B368",
        backgroundColor: grad,
        borderWidth: 2.8,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.4,
        cubicInterpolationMode: "monotone"
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 1000, easing: "easeOutQuart" },
      plugins: {
        legend: {
          position: "top",
          labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 7, font: { size: 12, weight: "600" } }
        },
        tooltip: {
          ...defaultTooltip(),
          callbacks: { label(ctx) { return ` Pazar Payı: %${ctx.parsed.y}`; } }
        }
      },
      scales: {
        x: { grid: { color: "rgba(13, 43, 83, .05)", drawBorder: false }, ticks: { color: "#6F8198" } },
        y: { grid: { color: "rgba(13, 43, 83, .05)", drawBorder: false }, ticks: { color: "#6F8198", callback(v) { return `%${v}`; } } }
      }
    }
  });
}

function updateDonutLegendColors(dataLength) {
  for (let i = 0; i < dataLength; i += 1) {
    const dot = document.getElementById(`donut-dot-${i}`);
    if (dot) dot.style.background = CORP_COLORS[i % CORP_COLORS.length];
  }
}

function initDonutLegendInteractions(chart, dataLength) {
  const items = document.querySelectorAll("#productDonutLegend [data-donut-index]");
  items.forEach((item) => {
    item.addEventListener("click", () => {
      const index = Number(item.getAttribute("data-donut-index"));
      if (Number.isNaN(index) || index >= dataLength) return;
      const hidden = chart.getDataVisibility(index);
      chart.toggleDataVisibility(index);
      chart.update();
      item.classList.toggle("inactive", hidden);
    }, { passive: true });
  });
}

function initProductDonut(data) {
  const canvas = document.getElementById("productDonutChart");
  if (!canvas || typeof Chart === "undefined") return;
  if (!data || !Array.isArray(data.values) || !data.values.length || data.values.every((v) => Number(v || 0) === 0)) {
    const body = canvas.closest(".section-card-body");
    if (body) body.innerHTML = chartPlaceholderMarkup("bi-pie-chart");
    return;
  }

  destroyChart("productDonut");
  updateDonutLegendColors(data.labels.length);

  CHARTS.productDonut = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: data.labels,
      datasets: [{
        data: data.values,
        backgroundColor: CORP_COLORS.slice(0, data.labels.length),
        borderColor: "#fff",
        borderWidth: 2,
        hoverOffset: 9,
        spacing: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "67%",
      animation: { animateRotate: true, animateScale: true, duration: 1100 },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...defaultTooltip(),
          callbacks: {
            label(ctx) {
              const val = Number(ctx.parsed || 0);
              const total = (ctx.dataset.data || []).reduce((sum, item) => sum + Number(item || 0), 0);
              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : "0.0";
              return ` ${ctx.label}: ${numberTR(val, " ₺")} (%${pct})`;
            }
          }
        }
      }
    }
  });

  initDonutLegendInteractions(CHARTS.productDonut, data.labels.length);
}

function initGaugeChart(data) {
  const canvas = document.getElementById("gaugeChart");
  if (!canvas || typeof Chart === "undefined") return;

  destroyChart("gauge");
  const pct = Math.max(0, Math.min(100, Number(data && data.percent ? data.percent : 0)));
  let fill = "#18B368";
  if (pct < 70) fill = "#E34B4B";
  else if (pct < 90) fill = "#F4A300";

  CHARTS.gauge = new Chart(canvas, {
    type: "doughnut",
    data: {
      datasets: [{
        data: [pct, 100 - pct],
        backgroundColor: [fill, "#E7EEF8"],
        borderWidth: 0,
        hoverOffset: 0,
        borderRadius: 12
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      circumference: 180,
      rotation: 270,
      cutout: "78%",
      animation: { duration: 1200, easing: "easeOutQuart" },
      plugins: { legend: { display: false }, tooltip: { enabled: false } }
    }
  });
}

function initTurkeyMap(cityPerformance) {
  const wrapper = document.getElementById("turkeyMapWrapper");
  const regions = document.querySelectorAll(".map-region");
  const tooltip = document.getElementById("mapTooltip");
  if (!wrapper || !regions.length) return;

  const palette = {
    high: "#0B4EA2",
    good: "#2D7FF9",
    medium: "#F4A300",
    low: "#E34B4B",
    empty: "#E7ECF4"
  };
  let selectedRegion = null;

  regions.forEach((region, index) => {
    const regionName = region.dataset.region || "Bölge";
    const cities = (region.dataset.cities || "").split(",").map((c) => c.trim()).filter(Boolean);
    const percentages = cities
      .map((city) => cityPerformance && cityPerformance[city] ? Number(cityPerformance[city].percent || 0) : 0)
      .filter((value) => value > 0);

    const avg = percentages.length ? percentages.reduce((sum, value) => sum + value, 0) / percentages.length : 0;
    const path = region.querySelector(".region-path");
    if (!path) return;

    let fill = palette.empty;
    if (percentages.length) {
      if (avg >= 90) fill = palette.high;
      else if (avg >= 70) fill = palette.good;
      else if (avg >= 50) fill = palette.medium;
      else fill = palette.low;
    }

    path.style.fill = fill;
    path.style.animation = "none";
    requestAnimationFrame(() => {
      path.style.animation = `mapPulse .45s ease ${Math.min(index * 0.04, 0.35)}s both`;
    });

    region.addEventListener("click", () => {
      if (selectedRegion) selectedRegion.classList.remove("map-region-selected");
      if (selectedRegion === region) {
        selectedRegion = null;
        return;
      }
      region.classList.add("map-region-selected");
      selectedRegion = region;
    });

    if (!tooltip) return;
    region.addEventListener("mouseenter", () => {
      tooltip.innerHTML = percentages.length
        ? `<strong>${regionName}</strong><br>%${avg.toFixed(1)} · ${percentages.length} il verisi`
        : `<strong>${regionName}</strong><br>Veri yok`;
      tooltip.style.display = "block";
    });

    region.addEventListener("mousemove", (event) => {
      const bounds = wrapper.getBoundingClientRect();
      tooltip.style.left = `${event.clientX - bounds.left + 12}px`;
      tooltip.style.top = `${event.clientY - bounds.top + 12}px`;
    });

    region.addEventListener("mouseleave", () => {
      tooltip.style.display = "none";
    });
  });
}

function initCompetitionMarket(data) {
  const canvas = document.getElementById("competitionMarketChart"), groups = data && Array.isArray(data.groups) ? data.groups.slice(0, 8) : [];
  if (!canvas || typeof Chart === "undefined" || !groups.length) return;
  destroyChart("competitionMarket");
  CHARTS.competitionMarket = new Chart(canvas, { type: "bar", data: { labels: groups.map(g => g.product_group), datasets: [{ label: "Şirket IMS", data: groups.map(g => g.company_sales_tl || 0), backgroundColor: "#0B4EA2", borderRadius: 5 }, { label: "Rakip satış alanı", data: groups.map(g => g.competitor_sales_tl || 0), backgroundColor: "#F4A300", borderRadius: 5 }] }, options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "top", labels: { usePointStyle: true, boxWidth: 8 } }, tooltip: { ...defaultTooltip(), callbacks: { label(ctx) { return ` ${ctx.dataset.label}: ${numberTR(ctx.parsed.x, " ₺")}`; } } } }, scales: { x: { stacked: true, ticks: { callback(v) { return `${Math.round(Number(v) / 1000000)} Mn ₺`; } }, grid: { color: "rgba(13, 43, 83, .06)" } }, y: { stacked: true, grid: { display: false } } } } });
}

function animateCounters() {
  document.querySelectorAll(".kpi-value").forEach((el, idx) => {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    el.style.transition = "opacity .45s ease, transform .45s ease";
    setTimeout(() => {
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    }, 70 * idx);
  });
}

function initProgressBars() {
  const bars = document.querySelectorAll(".progress-sm-bar, .table-progress-bar");
  bars.forEach((bar) => {
    const targetWidth = bar.style.width;
    bar.style.width = "0%";
    requestAnimationFrame(() => {
      setTimeout(() => {
        bar.style.width = targetWidth;
      }, 180);
    });
  });
}

function lazyInitCharts(data) {
  const initializers = [
    { id: "monthlyTrendChart", fn: () => initMonthlyTrend(data.monthlyTrend) },
    { id: "marketShareChart", fn: () => initMarketShare(data.marketShare) },
    { id: "productDonutChart", fn: () => initProductDonut(data.productDonut) },
    { id: "competitionMarketChart", fn: () => initCompetitionMarket(data.competitionAnalysis) },
    { id: "gaugeChart", fn: () => initGaugeChart(data.gauge) }
  ];

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const match = initializers.find((item) => item.id === entry.target.id);
      if (match) match.fn();
      obs.unobserve(entry.target);
    });
  }, { threshold: 0.2, rootMargin: "60px" });

  initializers.forEach((item) => {
    const element = document.getElementById(item.id);
    if (element) observer.observe(element);
  });
}

function initMapPulseStyle() {
  if (document.getElementById("mapPulseAnimationStyle")) return;
  const style = document.createElement("style");
  style.id = "mapPulseAnimationStyle";
  style.textContent = "@keyframes mapPulse{from{opacity:.2;transform:translateY(3px)}to{opacity:1;transform:translateY(0)}}";
  document.head.appendChild(style);
}

document.addEventListener("DOMContentLoaded", () => {
  const lastUpdateEl = document.getElementById("dashLastUpdate");
  if (lastUpdateEl) {
    const now = new Date();
    lastUpdateEl.textContent = `Son güncelleme: ${now.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}`;
  }

  const searchInput = document.getElementById("productTableSearch");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      const q = searchInput.value.toLowerCase();
      document.querySelectorAll(".premium-table tbody tr").forEach((row) => {
        const name = (row.querySelector(".product-name-cell") || {}).textContent || "";
        row.style.display = name.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }

  const data = getDashboardData();
  if (!data) return;
  initMapPulseStyle();
  lazyInitCharts(data);
  initTurkeyMap(data.cityPerformance || {});
  animateCounters();
  initProgressBars();
});

window.addEventListener("beforeunload", () => {
  Object.keys(CHARTS).forEach((key) => destroyChart(key));
});
