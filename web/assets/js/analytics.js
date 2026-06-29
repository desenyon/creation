/** Vercel Web Analytics — custom events (works once deployed on Vercel). */

window.creationTrack = function creationTrack(name, data) {
  if (typeof window.va !== "function") return;
  window.va("event", { name, data: data || {} });
};

document.querySelector('.hero-df-actions a[href="#quickstart"]')?.addEventListener("click", () => {
  window.creationTrack("cta_get_started");
});

document.querySelector('.df-cta-pill a[href*="github"]')?.addEventListener("click", () => {
  window.creationTrack("cta_github");
});

document.querySelectorAll(".df-nav-pill a, #df-mobile-nav a").forEach((link) => {
  link.addEventListener("click", () => {
    const section = link.getAttribute("href") || link.textContent?.trim() || "nav";
    window.creationTrack("nav_click", { section });
  });
});
