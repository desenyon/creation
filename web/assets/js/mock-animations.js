/** Hero prompt demo, editorial scroll, feature card cycles, logo marquee */

(function () {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PROMPT = "Build a CLI that syncs Linear tickets to markdown — 12 turns max, ship an MVP.";
  const TURN_BUDGET = 12;

  const PHASES = [
    { id: "nebius", logo: "nebius", label: "Nebius", detail: "Planning 12-turn MVP scope…" },
    { id: "tavily", logo: "tavily", label: "Tavily", detail: "Researching markets + competitors…" },
    { id: "firecrawl", logo: "firecrawl", label: "Firecrawl", detail: "Scraped 6 pages into build context" },
    { id: "mem0", logo: "mem0", label: "Mem0", detail: "Recalled 3 preferences from past runs" },
    { id: "compress", logo: "supercompress", label: "SuperCompress", detail: "Trimmed research context by 61%" },
    { id: "codex", logo: "openai", label: "Codex", detail: "Scaffolding CLI + pytest suite…" },
    { id: "qa", logo: "supercompress", label: "QA", detail: "Tests passing · browser review clean" },
    { id: "composio", logo: "composio", label: "Composio", detail: "GitHub PR opened · Linear LOO-12 · Gmail sent" },
  ];

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function logoImg(name, size) {
    const ext = name === "motherduck" ? "png" : "svg";
    const file = name === "motherduck" ? "motherduck-icon" : name;
    return `<img src="assets/images/logos/${file}.${ext}" alt="" width="${size}" height="${size}" class="logo-img">`;
  }

  async function typePrompt(el) {
    if (!el) return;
    el.textContent = "";
    for (let i = 0; i < PROMPT.length; i++) {
      el.textContent = PROMPT.slice(0, i + 1);
      await sleep(28 + Math.random() * 22);
    }
  }

  async function runHeroMock() {
    const root = document.getElementById("hero-mock");
    const typed = document.getElementById("mock-typed");
    const btn = document.getElementById("mock-loop-btn");
    const workspace = document.getElementById("mock-workspace");
    const timeline = document.getElementById("mock-timeline");
    const status = document.getElementById("mock-status");
    if (!root || !typed || !btn || !workspace || !timeline) return;

    async function cycle() {
      root.classList.remove("is-running", "is-done");
      workspace.hidden = true;
      btn.disabled = false;
      btn.classList.remove("is-clicked");
      typed.textContent = reduced ? PROMPT : "";
      timeline.querySelectorAll(".mock-phase-row").forEach((row) => {
        row.classList.remove("is-active", "is-done");
      });
      if (status) status.textContent = "Waiting for your idea…";

      if (reduced) {
        typed.textContent = PROMPT;
        btn.classList.add("is-clicked");
        workspace.hidden = false;
        timeline.querySelectorAll(".mock-phase-row").forEach((row) => row.classList.add("is-done"));
        if (status) status.textContent = "Shipped · PR ready · Linear updated";
        root.classList.add("is-done");
        return;
      }

      await sleep(700);
      await typePrompt(typed);
      await sleep(400);
      btn.classList.add("is-clicked");
      await sleep(350);
      btn.disabled = true;
      root.classList.add("is-running");
      workspace.hidden = false;
      if (status) status.textContent = "Loop running…";

      const rows = [...timeline.querySelectorAll(".mock-phase-row")];
      for (const row of rows) {
        row.classList.add("is-active");
        const phase = PHASES.find((p) => p.id === row.dataset.phase);
        if (status && phase) status.textContent = phase.detail;
        await sleep(Number(row.dataset.delay || 900));
        row.classList.remove("is-active");
        row.classList.add("is-done");
      }

      root.classList.remove("is-running");
      root.classList.add("is-done");
      if (status) status.textContent = "Shipped · PR ready · Linear updated · Gmail sent";
      await sleep(3200);
      cycle();
    }

    cycle();
  }

  function initAgentCycle() {
    const items = [...document.querySelectorAll("#agent-cycle li")];
    if (!items.length || reduced) return;
    let idx = 0;
    setInterval(() => {
      items.forEach((li) => li.classList.remove("active"));
      items[idx]?.classList.add("active");
      idx = (idx + 1) % items.length;
    }, 2200);
  }

  function initOpsPulse() {
    const items = [...document.querySelectorAll("#ops-cycle li")];
    if (!items.length || reduced) return;
    let idx = 0;
    setInterval(() => {
      items.forEach((li) => li.classList.remove("active"));
      items[idx]?.classList.add("active");
      idx = (idx + 1) % items.length;
    }, 1800);
  }

  function initEditorialScroll() {
    const section = document.querySelector(".editorial-scroll");
    const words = section?.querySelectorAll(".editorial-word");
    if (!section || !words?.length) return;

    if (reduced) {
      words.forEach((w) => w.classList.add("lit"));
      return;
    }

    function update() {
      const rect = section.getBoundingClientRect();
      const vh = window.innerHeight;
      const total = section.offsetHeight - vh;
      const scrolled = Math.min(Math.max(-rect.top, 0), total);
      const progress = total > 0 ? scrolled / total : 1;
      const litCount = Math.floor(progress * words.length * 1.08);
      words.forEach((w, i) => {
        w.classList.toggle("lit", i < litCount);
      });
    }

    window.addEventListener("scroll", update, { passive: true });
    update();
  }

  window.MockAnimations = {
    runHeroMock,
    initEditorialScroll,
    initAgentCycle,
    initOpsPulse,
    logoImg,
  };
})();
