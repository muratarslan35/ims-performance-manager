(function () {
  "use strict";
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
  document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-exec-cockpit]").forEach(root => setPeriod(root, "monthly")));
})();
