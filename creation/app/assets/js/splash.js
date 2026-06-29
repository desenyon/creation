(function () {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const holdMs = reduced ? 500 : 1600;
  const fadeMs = reduced ? 0 : 850;

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function resolveDestination() {
    try {
      const response = await fetch("/api/composio/onboarding");
      if (!response.ok) return "/onboarding";
      const state = await response.json();
      if (state.complete) return "/dashboard";
    } catch (_) {
      /* fall through */
    }
    return "/onboarding";
  }

  async function run() {
    const destination = await resolveDestination();
    await sleep(holdMs);
    document.body.classList.add("is-exiting");
    if (fadeMs) await sleep(fadeMs);
    window.location.replace(destination);
  }

  run();
})();
