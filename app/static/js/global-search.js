(function () {
  "use strict";

  const input = document.getElementById("globalRepresentativeSearch");
  const results = document.getElementById("globalSearchResults");
  if (!input || !results) return;

  let timer = null;
  const close = () => { results.classList.remove("is-open"); results.innerHTML = ""; };
  const escapeHtml = (value) => String(value || "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"})[char]);

  input.addEventListener("input", () => {
    const query = input.value.trim();
    window.clearTimeout(timer);
    if (query.length < 2) { close(); return; }
    timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`/representatives/search?q=${encodeURIComponent(query)}`, { headers: { Accept: "application/json" } });
        const payload = await response.json();
        const items = payload.results || [];
        results.innerHTML = items.length ? items.map((item) => `
          <a class="global-search-item" href="${escapeHtml(item.url)}" role="option">
            <i class="bi ${item.kind === "brick" ? "bi-geo-alt-fill" : "bi-person-fill"}"></i>
            <span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.meta)}</small></span>
          </a>`).join("") : '<div class="global-search-empty">Eşleşen temsilci veya brick bulunamadı.</div>';
        results.classList.add("is-open");
      } catch (_) {
        close();
      }
    }, 220);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && results.querySelector("a")) {
      event.preventDefault(); results.querySelector("a").click();
    }
    if (event.key === "Escape") close();
  });
  document.addEventListener("click", (event) => { if (!event.target.closest(".navbar-search")) close(); });
}());
