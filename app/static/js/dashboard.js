/* ═══════════════════════════════════════════════════════════
   IMS Performance Manager – Enterprise Ana Sayfa (PR-3)
   dashboard.js – Chart.js tabanlı grafik başlatma
   ═══════════════════════════════════════════════════════════ */

"use strict";

/* ── Kurumsal renk paleti ────────────────────────────────── */
const CORP_COLORS = [
  "#0B4EA2", "#2D7FF9", "#18B368", "#F4A300",
  "#6B5BFF", "#E34B4B", "#00B8C4", "#F47C20",
  "#3B82F6", "#A855F7"
];

/* ── Gradyan yardımcı fonksiyon ──────────────────────────── */
function makeGradient(ctx, colorStart, colorEnd) {
  const grad = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
  grad.addColorStop(0, colorStart);
  grad.addColorStop(1, colorEnd);
  return grad;
}

/* ── Dashboard veri nesnesi (template'den JSON) ──────────── */
function getDashboardData() {
  const el = document.getElementById("dashboardData");
  if (!el) return null;
  try {
    return JSON.parse(el.textContent);
  } catch (e) {
    console.error("Dashboard verisi okunamadı:", e);
    return null;
  }
}

/* ════════════════════════════════════════════════════════════
   1. ÜRÜN DONUT CHART
   ════════════════════════════════════════════════════════════ */
function initProductDonut(data) {
  const canvas = document.getElementById("productDonutChart");
  if (!canvas || typeof Chart === "undefined") return;
  if (!data || !data.values || data.values.every(v => v === 0)) {
    canvas.closest(".chart-container").innerHTML =
      '<div class="empty-state"><i class="bi bi-pie-chart"></i><p>Veri bulunmuyor</p></div>';
    return;
  }

  /* Legend noktalarını renklendir */
  data.labels.forEach((_, i) => {
    const dot = document.getElementById("donut-dot-" + i);
    if (dot) dot.style.background = CORP_COLORS[i % CORP_COLORS.length];
  });

  new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: data.labels,
      datasets: [{
        data: data.values,
        backgroundColor: CORP_COLORS.slice(0, data.labels.length),
        borderWidth: 3,
        borderColor: "#fff",
        hoverOffset: 8
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: "68%",
      animation: { animateRotate: true, duration: 900 },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(ctx) {
              const val = ctx.parsed;
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
              return ` ${ctx.label}: ${val.toLocaleString("tr-TR")} ₺ (%${pct})`;
            }
          }
        }
      }
    }
  });
}

/* ════════════════════════════════════════════════════════════
   2. GAUGE (DOUGHNUT) CHART
   ════════════════════════════════════════════════════════════ */
function initGaugeChart(data) {
  const canvas = document.getElementById("gaugeChart");
  if (!canvas || typeof Chart === "undefined") return;

  const pct = Math.min(data ? data.percent : 0, 100);
  const remaining = Math.max(0, 100 - pct);
  let fillColor = "#18B368";
  if (pct < 70) fillColor = "#E34B4B";
  else if (pct < 90) fillColor = "#F4A300";

  new Chart(canvas, {
    type: "doughnut",
    data: {
      datasets: [{
        data: [pct, remaining],
        backgroundColor: [fillColor, "#EEF2F9"],
        borderWidth: 0,
        hoverOffset: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      circumference: 270,
      rotation: -135,
      cutout: "75%",
      animation: { duration: 1000, easing: "easeInOutQuart" },
      plugins: { legend: { display: false }, tooltip: { enabled: false } }
    }
  });
}

/* ════════════════════════════════════════════════════════════
   3. AYLIK CİRO TRENDİ (LINE CHART)
   ════════════════════════════════════════════════════════════ */
function initMonthlyTrend(data) {
  const canvas = document.getElementById("monthlyTrendChart");
  if (!canvas || typeof Chart === "undefined") return;
  if (!data || !data.labels || data.labels.length === 0) return;

  const ctx = canvas.getContext("2d");
  const gradR = makeGradient(ctx, "rgba(11,78,162,.30)", "rgba(11,78,162,.02)");
  const gradT = makeGradient(ctx, "rgba(244,163,0,.20)", "rgba(244,163,0,.02)");

  new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Gerçekleşen",
          data: data.realization,
          borderColor: "#0B4EA2",
          backgroundColor: gradR,
          borderWidth: 2.5,
          pointRadius: 4,
          pointBackgroundColor: "#0B4EA2",
          pointBorderColor: "#fff",
          pointBorderWidth: 2,
          fill: true,
          tension: 0.4
        },
        {
          label: "Hedef",
          data: data.target,
          borderColor: "#F4A300",
          backgroundColor: gradT,
          borderWidth: 2,
          borderDash: [6, 4],
          pointRadius: 3,
          pointBackgroundColor: "#F4A300",
          pointBorderColor: "#fff",
          pointBorderWidth: 2,
          fill: true,
          tension: 0.4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      animation: { duration: 900 },
      plugins: {
        legend: {
          position: "top",
          labels: { font: { size: 12, weight: "600" }, padding: 16, usePointStyle: true }
        },
        tooltip: {
          callbacks: {
            label(ctx) {
              return ` ${ctx.dataset.label}: ${(ctx.parsed.y || 0).toLocaleString("tr-TR")} ₺`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: { font: { size: 11 }, color: "#6B7280" }
        },
        y: {
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: {
            font: { size: 11 }, color: "#6B7280",
            callback(v) { return (v / 1000).toFixed(0) + "K ₺"; }
          }
        }
      }
    }
  });
}

/* ════════════════════════════════════════════════════════════
   4. PAZAR PAYI TRENDİ (LINE CHART)
   ════════════════════════════════════════════════════════════ */
function initMarketShare(data) {
  const canvas = document.getElementById("marketShareChart");
  if (!canvas || typeof Chart === "undefined") return;
  if (!data || !data.labels || data.labels.length === 0) return;

  const ctx = canvas.getContext("2d");
  const grad = makeGradient(ctx, "rgba(24,179,104,.28)", "rgba(24,179,104,.02)");

  new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [{
        label: "Pazar Payı (%)",
        data: data.values,
        borderColor: "#18B368",
        backgroundColor: grad,
        borderWidth: 2.5,
        pointRadius: 4,
        pointBackgroundColor: "#18B368",
        pointBorderColor: "#fff",
        pointBorderWidth: 2,
        fill: true,
        tension: 0.4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 900 },
      plugins: {
        legend: {
          position: "top",
          labels: { font: { size: 12, weight: "600" }, usePointStyle: true }
        },
        tooltip: {
          callbacks: {
            label(ctx) { return ` Pazar Payı: %${ctx.parsed.y}`; }
          }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: { font: { size: 11 }, color: "#6B7280" }
        },
        y: {
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: {
            font: { size: 11 }, color: "#6B7280",
            callback(v) { return "%" + v; }
          }
        }
      }
    }
  });
}

/* ════════════════════════════════════════════════════════════
   5. TÜRKİYE HARİTASI – bölge renklendirme
   ════════════════════════════════════════════════════════════ */
function initTurkeyMap(cityPerformance) {
  const regions = document.querySelectorAll(".map-region");
  if (!regions.length) return;

  const tooltip = document.getElementById("mapTooltip");
  const wrapper = document.getElementById("turkeyMapWrapper");

  /* Her bölge için şehir listesinden ortalama performans hesapla */
  regions.forEach(region => {
    const regionName = region.dataset.region || "";
    const cities = (region.dataset.cities || "").split(",").map(c => c.trim());

    let total = 0, count = 0;
    cities.forEach(city => {
      if (cityPerformance[city] && cityPerformance[city].percent) {
        total += cityPerformance[city].percent;
        count++;
      }
    });

    const path = region.querySelector(".region-path");
    if (!path) return;

    if (count === 0) {
      path.style.fill = "#E7ECF4";  /* veri yok */
    } else {
      const avg = total / count;
      if (avg >= 90)       path.style.fill = "#0B4EA2";
      else if (avg >= 70)  path.style.fill = "#2D7FF9";
      else if (avg >= 50)  path.style.fill = "#F4A300";
      else                 path.style.fill = "#E34B4B";
    }

    /* Tooltip */
    if (tooltip && wrapper) {
      region.addEventListener("mouseenter", e => {
        const label = count > 0
          ? `${regionName}: %${(total / count).toFixed(1)}`
          : `${regionName}: Veri yok`;
        tooltip.textContent = label;
        tooltip.style.display = "block";
      });
      region.addEventListener("mousemove", e => {
        const rect = wrapper.getBoundingClientRect();
        tooltip.style.left = (e.clientX - rect.left + 8) + "px";
        tooltip.style.top  = (e.clientY - rect.top  + 8) + "px";
      });
      region.addEventListener("mouseleave", () => {
        tooltip.style.display = "none";
      });
    }
  });
}

/* ════════════════════════════════════════════════════════════
   6. KPI COUNTER ANİMASYON
   ════════════════════════════════════════════════════════════ */
function animateCounters() {
  document.querySelectorAll(".kpi-value").forEach(el => {
    el.style.opacity = "0";
    el.style.transform = "translateY(10px)";
    el.style.transition = "opacity 0.5s ease, transform 0.5s ease";
    setTimeout(() => {
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    }, 100 + Math.random() * 300);
  });
}

/* ════════════════════════════════════════════════════════════
   7. KPI CARD HOVER – progress bar animasyonu
   ════════════════════════════════════════════════════════════ */
function initProgressBars() {
  document.querySelectorAll(".progress-sm-bar").forEach(bar => {
    const w = bar.style.width || "0%";
    bar.style.width = "0%";
    setTimeout(() => { bar.style.width = w; }, 400);
  });
}

/* ════════════════════════════════════════════════════════════
   BAŞLAT
   ════════════════════════════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", function () {
  const d = getDashboardData();
  if (!d) return;

  initProductDonut(d.productDonut);
  initGaugeChart(d.gauge);
  initMonthlyTrend(d.monthlyTrend);
  initMarketShare(d.marketShare);
  initTurkeyMap(d.cityPerformance || {});
  animateCounters();
  initProgressBars();
});
