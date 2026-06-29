/** Datafruit-style interactions: nav, video, vision scroll, FAQ, scroll reveal */

(function () {
  "use strict";

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Mobile nav */
  const menuBtn = document.getElementById("df-menu-btn");
  const mobileNav = document.getElementById("df-mobile-nav");
  menuBtn?.addEventListener("click", () => {
    const hidden = mobileNav?.classList.toggle("hidden");
    menuBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
  });
  mobileNav?.querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", () => {
      mobileNav.classList.add("hidden");
      menuBtn?.setAttribute("aria-expanded", "false");
    });
  });

  /* Launch video — YouTube embed + self-hosted fallback */
  const LAUNCH_VIDEO_YT = "https://www.youtube.com/embed/aeCW_H-WDHU";

  function wireLaunchVideo(frameId, playSel) {
    const frame = document.getElementById(frameId);
    if (!frame) return;

    const playBtn = playSel ? frame.querySelector(playSel) : frame.querySelector(".hero-frame-play");
    const iframe = frame.querySelector(".hero-frame-youtube");
    const fallback = frame.querySelector(".hero-frame-video--fallback");
    if (!playBtn || !iframe) return;

    function startFallback() {
      if (!fallback) return false;
      iframe.classList.add("is-hidden");
      fallback.classList.add("is-active");
      fallback.removeAttribute("aria-hidden");
      fallback.muted = false;
      return fallback.play().then(() => {
        frame.classList.add("is-playing");
      }).catch(() => {
        fallback.muted = true;
        return fallback.play().then(() => frame.classList.add("is-playing"));
      }).catch(() => false);
    }

    playBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (frame.classList.contains("is-playing")) return;

      if (!navigator.onLine && fallback) {
        startFallback();
        return;
      }

      iframe.src = `${LAUNCH_VIDEO_YT}?autoplay=1&rel=0`;
      frame.classList.add("is-playing");
    });
  }

  wireLaunchVideo("launch-video-frame", "#launch-video-play");
  wireLaunchVideo("launch-video-frame-mobile", ".launch-video-play");

  /* Vision scroll word reveal */
  const runway = document.getElementById("vision-runway");
  const words = document.querySelectorAll(".vision-word");

  if (words.length && !reduced) {
    words.forEach((w) => {
      w.style.opacity = "0.12";
    });

    function updateVision() {
      if (!runway) return;
      const rect = runway.getBoundingClientRect();
      const vh = window.innerHeight;
      const total = runway.offsetHeight - vh;
      const scrolled = Math.min(Math.max(-rect.top, 0), total);
      const progress = total > 0 ? scrolled / total : 1;

      words.forEach((w, i) => {
        const wordProgress = (progress * words.length - i) / 2;
        const opacity = Math.min(1, Math.max(0.12, wordProgress));
        w.style.opacity = String(opacity);
      });
    }

    window.addEventListener("scroll", updateVision, { passive: true });
    window.addEventListener("resize", updateVision, { passive: true });
    updateVision();
  } else {
    words.forEach((w) => {
      w.style.opacity = "1";
    });
  }

  /* FAQ accordion */
  document.querySelectorAll(".df-faq-item button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = btn.closest(".df-faq-item");
      const open = item?.classList.toggle("is-open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  /* Scroll reveal */
  function inViewport(el, margin = 80) {
    const rect = el.getBoundingClientRect();
    return rect.top < window.innerHeight - margin && rect.bottom > margin;
  }

  function revealEl(el) {
    el.classList.add("is-visible");
  }

  function initScrollReveal() {
    const revealEls = document.querySelectorAll(".df-reveal, .df-reveal-stagger");
    if (!revealEls.length) return;

    if (reduced) {
      revealEls.forEach(revealEl);
      return;
    }

    document.querySelectorAll(".df-reveal-stagger").forEach((parent) => {
      [...parent.children].forEach((child, i) => child.style.setProperty("--stagger-i", String(i)));
    });

    const pending = new Set(revealEls);

    function flushVisible() {
      pending.forEach((el) => {
        if (inViewport(el, 40)) {
          revealEl(el);
          pending.delete(el);
          io?.unobserve(el);
        }
      });
    }

    let io = null;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            revealEl(entry.target);
            pending.delete(entry.target);
            io.unobserve(entry.target);
          });
        },
        { threshold: 0.05, rootMargin: "0px 0px -40px 0px" }
      );
      revealEls.forEach((el) => io.observe(el));
    } else {
      revealEls.forEach(revealEl);
      return;
    }

    flushVisible();
    window.addEventListener("scroll", flushVisible, { passive: true });
    window.addEventListener("resize", flushVisible, { passive: true });
    requestAnimationFrame(flushVisible);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initScrollReveal);
  } else {
    initScrollReveal();
  }
})();
