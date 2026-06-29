/** Creation dashboard — live SSE progress */

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

let activeProjectId = null;
let activeRunId = null;
let eventSource = null;
let agentPollTimer = null;
const runStreams = new Map();
let usagePollTimer = null;
let pipeline = [];
let currentTurn = 0;
let currentMaxTurns = 0;
let setupCollapsed = false;
let defaultAgent = "codex";
let defaultMaxTurns = 200;
let settingsOpen = false;

const SETUP_PHASES = new Set([
  "tavily",
  "firecrawl",
  "composio",
  "plan",
  "brand",
  "composio-setup",
  "ops",
]);

const TOOL_ICONS = {
  tavily: "🔍",
  firecrawl: "🕸",
  composio: "⚡",
  mem0: "🧠",
  supercompress: "🗜",
  plan: "📋",
  brand: "✦",
  agent: "⌨",
  ops: "🚀",
  qa: "✓",
  route: "🧠",
};

async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!r.ok) {
    const text = await r.text();
    try {
      const j = JSON.parse(text);
      throw new Error(j.detail || j.error || text);
    } catch (err) {
      if (err instanceof Error && err.message !== text) throw err;
      throw new Error(text || `Request failed (${r.status})`);
    }
  }
  return r.json();
}

function renderUsageMeters(agents, root = "#settings-agent-usage") {
  const el = $(root);
  if (!el || !agents?.length) {
    if (el) el.innerHTML = '<p class="sf-dim">No agent usage yet.</p>';
    return;
  }
  el.innerHTML = agents
    .slice(0, 4)
    .map((a) => {
      const pct = Math.min(100, Math.round(a.pct || 0));
      const status = a.status || (pct >= 90 ? "critical" : pct >= 75 ? "warn" : "ok");
      return `<div class="lp-usage-chip ${status}" title="${esc(a.agent)} · ${pct}% · ${a.used || 0}/${a.limit || "?"} turns">
        <strong>${esc(a.agent)} ${pct}%</strong>
        <div class="lp-usage-track"><div class="lp-usage-fill" style="width:${pct}%"></div></div>
      </div>`;
    })
    .join("");
}

async function refreshAgentUsage() {
  try {
    const data = await api("/agents/usage");
    renderUsageMeters(data.agents);
  } catch (_) {}
}

function showPage(page) {
  settingsOpen = false;
  $$(".lp-page").forEach((p) => p.classList.remove("active"));
  $(`#page-${page}`)?.classList.add("active");
  const settings = $("#view-settings");
  if (settings) {
    settings.classList.add("hidden");
    settings.style.display = "";
  }
}

function unlockPage(_page) {
  /* step pills removed — navigation is automatic */
}

function showManualPanel(show) {
  const panel = $("#manual-takeover-panel");
  if (!panel) return;
  panel.classList.toggle("hidden", !show);
}

function renderManualMessage(msg) {
  const ul = $("#manual-message-list");
  if (!ul) return;
  const consumed = msg.status === "consumed";
  const meta = consumed
    ? `Applied · turn ${msg.consumed_turn || "?"}`
    : "Queued for next turn";
  ul.insertAdjacentHTML(
    "beforeend",
    `<li class="${consumed ? "consumed" : ""}" data-id="${esc(msg.id)}">
      <span>${esc(msg.text)}</span>
      <span class="sf-manual-meta">${esc(meta)}</span>
    </li>`
  );
  ul.lastElementChild?.scrollIntoView({ block: "nearest" });
}

function loadManualMessages(messages) {
  const ul = $("#manual-message-list");
  if (!ul) return;
  ul.innerHTML = "";
  (messages || []).forEach(renderManualMessage);
}

async function sendManualMessage(e) {
  e?.preventDefault();
  if (!activeRunId) {
    showToast("Start a loop first");
    return;
  }
  const input = $("#manual-message-input");
  const text = input?.value?.trim();
  if (!text) return;
  const btn = $(".sf-manual-send");
  if (btn) btn.disabled = true;
  try {
    const msg = await api(`/runs/${activeRunId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    renderManualMessage(msg);
    if (input) input.value = "";
    showToast("Message queued");
  } catch (err) {
    showToast(err?.message || "Could not send message");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function markManualMessagesConsumed(turn) {
  $$("#manual-message-list li:not(.consumed)").forEach((li) => {
    li.classList.add("consumed");
    const meta = li.querySelector(".sf-manual-meta");
    if (meta) meta.textContent = `Applied · turn ${turn}`;
  });
}

function showView(name) {
  $$(".sf-nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "settings") {
    if (settingsOpen) {
      settingsOpen = false;
      $("#view-settings")?.classList.add("hidden");
      $$(".sf-nav-btn").forEach((b) => b.classList.remove("active"));
      showPage("compose");
      return;
    }
    settingsOpen = true;
    $$(".lp-page").forEach((p) => p.classList.remove("active"));
    const settings = $("#view-settings");
    if (settings) {
      settings.classList.remove("hidden");
      settings.style.display = "block";
    }
    loadSecrets();
    refreshAgentUsage();
    renderContextRest();
    return;
  }
  settingsOpen = false;
  $("#view-settings")?.classList.add("hidden");
  if (!$(".lp-page.active")) showPage("compose");
}

function renderShipReceipt(r) {
  if (!r) return;
  $("#ship-product-name").textContent = r.product_name || r.idea || "Shipped";
  $("#ship-tagline").textContent = r.tagline || r.idea || "";
  const rows = [
    { icon: "🌐", label: "Live URL", value: r.deploy_url, link: r.deploy_url, live: true },
    { icon: "⎇", label: "Pull request", value: r.pr_url, link: r.pr_url },
    { icon: "⌥", label: "GitHub", value: r.github_url, link: r.github_url },
    { icon: "◫", label: "Linear", value: r.linear_project || "Project", link: r.linear_url },
    { icon: "✉", label: "Gmail", value: r.gmail_sent ? "Ship notification sent" : "Not sent" },
    { icon: "📣", label: "Marketing", value: r.marketing_sent ? (r.marketing_message || "Launch campaign sent") : "" },
    { icon: "⌨", label: "Agents", value: (r.agents || []).join(" + ") || "—" },
  ].filter((row) => row.value && row.value !== "—");
  $("#ship-receipt-grid").innerHTML = rows
    .map(
      (row) => `<div class="lp-receipt-card ${row.live && row.link ? "lp-receipt-live" : ""}">
      <div class="lp-receipt-icon">${row.icon}</div>
      <div class="lp-receipt-body">
        <div class="lp-receipt-label">${esc(row.label)}</div>
        <div class="lp-receipt-value">${
          row.link
            ? `<a href="${esc(row.link)}" target="_blank" rel="noopener">${esc(row.value)}</a>`
            : esc(String(row.value))
        }</div>
      </div>
    </div>`
    )
    .join("");
  const liveBtn = $("#ship-live-btn");
  if (r.live_url) {
    liveBtn.href = r.live_url;
    liveBtn.classList.remove("hidden");
  } else {
    liveBtn.classList.add("hidden");
  }
  const tp = r.token_preservation || {};
  const savingsPct = tp.savings_pct != null ? tp.savings_pct : r.memory_savings_pct;
  const recalled = tp.mem0_recalled != null ? tp.mem0_recalled : r.mem0_recalled;
  $("#ship-stats").innerHTML = [
    r.turns != null
      ? `<div class="lp-ship-stat"><span class="lp-ship-stat-n">${r.turns}</span><span class="lp-ship-stat-l">turns</span></div>`
      : "",
    savingsPct != null
      ? `<div class="lp-ship-stat"><span class="lp-ship-stat-n">${Math.round(savingsPct)}%</span><span class="lp-ship-stat-l">tokens saved</span></div>`
      : "",
    tp.tokens_saved
      ? `<div class="lp-ship-stat"><span class="lp-ship-stat-n">${fmtTokens(tp.tokens_saved)}</span><span class="lp-ship-stat-l">tokens preserved</span></div>`
      : "",
    recalled != null
      ? `<div class="lp-ship-stat"><span class="lp-ship-stat-n">${recalled}</span><span class="lp-ship-stat-l">Mem0 recalled</span></div>`
      : "",
  ].join("");
  const tpBanner = $("#ship-token-preservation");
  if (tpBanner) {
    if (tp.summary && tp.original_tokens) {
      tpBanner.textContent = `Token preservation: ${tp.summary}`;
      tpBanner.classList.remove("hidden");
    } else {
      tpBanner.classList.add("hidden");
      tpBanner.textContent = "";
    }
  }
  const proofGrid = $("#ship-proof-grid");
  if (proofGrid && r.proof?.length) {
    proofGrid.classList.remove("hidden");
    proofGrid.innerHTML = `<p class="lp-sponsor-title">Proof ledger</p><div class="lp-proof-rows">${r.proof
      .map(
        (item) => `<div class="lp-proof-row ${esc(item.status || "partial")}">
          <span class="lp-proof-status">${esc(
            item.status ? item.status.charAt(0).toUpperCase() + item.status.slice(1) : "Partial"
          )}</span>
          <strong>${esc(item.axis)}</strong>
          <span>${esc(item.evidence || "")}</span>
        </div>`
      )
      .join("")}</div>`;
  } else if (proofGrid) {
    proofGrid.classList.add("hidden");
    proofGrid.innerHTML = "";
  }
  const sponsorGrid = $("#ship-sponsor-grid");
  if (sponsorGrid && r.sponsor_integrations?.length) {
    sponsorGrid.classList.remove("hidden");
    sponsorGrid.innerHTML = `<p class="lp-sponsor-title">Partner integrations</p><div class="lp-sponsor-chips">${r.sponsor_integrations
      .map(
        (s) =>
          `<span class="lp-sponsor-chip status-${esc(s.status || "unknown")}" title="${esc(s.integration || "")}"><strong>${esc(s.sponsor)}</strong> · ${esc(s.status || "unknown")}</span>`
      )
      .join("")}</div>`;
  } else if (sponsorGrid) {
    sponsorGrid.classList.add("hidden");
    sponsorGrid.innerHTML = "";
  }
  unlockPage("ship");
  showPage("ship");
  window.__lastShipReceipt = r;
}

function copyShipReceipt() {
  const r = window.__lastShipReceipt;
  if (!r) {
    showToast("No ship receipt yet");
    return;
  }
  const sponsors = (r.sponsor_integrations || [])
    .map((s) => `- ${s.sponsor}: ${s.integration} (${s.status})`)
    .join("\n");
  const text = [
    `# Creation Ship Receipt — ${r.product_name || r.idea}`,
    "",
    r.tagline || "",
    "",
    `- Live: ${r.live_url || r.deploy_url || "—"}`,
    `- GitHub: ${r.github_url || "—"}`,
    `- Linear: ${r.linear_url || "—"}`,
    `- Turns: ${r.turns ?? "—"}`,
    `- Token preservation: ${r.token_preservation?.summary || (r.memory_savings_pct != null ? Math.round(r.memory_savings_pct) + "% KV saved" : "—")}`,
    `- Mem0 recalled: ${r.token_preservation?.mem0_recalled ?? r.mem0_recalled ?? "—"}`,
    `- Verified artifacts: ${r.verified_artifacts ?? "—"}/4`,
    `- Live integrations: ${r.live_integration_count ?? "—"}`,
    "",
    "## Proof",
    ...(r.proof || []).map((item) => `- ${item.axis}: ${item.status} — ${item.evidence}`),
    "",
    "## Partner integrations",
    sponsors || "—",
    "",
    "Website: https://creation.dev",
    "Repo: https://github.com/arjunkshah/creation",
  ].join("\n");
  navigator.clipboard?.writeText(text).then(
    () => showToast("Receipt copied"),
    () => showToast("Could not copy")
  );
}

async function loadSuggestions(seed = "") {
  const list = $("#suggest-list");
  if (!list) return;
  list.innerHTML = `<p class="sf-dim" style="font-size:13px;padding:8px">Finding ideas…</p>`;
  try {
    const data = await api("/suggest", {
      method: "POST",
      body: JSON.stringify({ seed: seed || $("#loop-prompt")?.value?.trim() || "", count: 3 }),
    });
    const items = data.suggestions || [];
    if (!items.length) {
      list.innerHTML = `<p class="sf-dim" style="font-size:13px;padding:8px">No suggestions — type a seed topic.</p>`;
      return;
    }
    list.innerHTML = items
      .map(
        (s) => `<button type="button" class="sf-suggest-card" data-idea="${esc(s.idea || s.title)}">
        <span class="sf-suggest-score-ring" style="--score:${Math.round((s.score || 0.5) * 100)}"><span>${Math.round((s.score || 0.5) * 100)}</span></span>
        <div class="sf-suggest-title">${esc(s.title || "Idea")}</div>
        <div class="sf-suggest-idea">${esc(s.idea || "")}</div>
        ${s.pitch ? `<div class="sf-suggest-pitch">${esc(s.pitch)}</div>` : ""}
      </button>`
      )
      .join("");
    list.querySelectorAll(".sf-suggest-card[data-idea]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idea = btn.dataset.idea || "";
        if ($("#loop-prompt")) $("#loop-prompt").value = idea;
        showToast("Idea selected");
      });
    });
  } catch (err) {
    list.innerHTML = `<p class="sf-dim" style="font-size:13px;padding:8px">${esc(err?.message || "Could not load ideas")}</p>`;
  }
}

function loopBtn() {
  return $("#loop-btn");
}

function setLoopBtnRunning(running) {
  const btn = loopBtn();
  if (!btn) return;
  btn.disabled = running;
  btn.classList.toggle("running", running);
}

function switchMissionPane(name) {
  $$(".sf-mtab").forEach((t) => t.classList.toggle("active", t.dataset.pane === name));
  $$(".sf-mpane").forEach((p) => p.classList.add("hidden"));
  $(`#pane-${name}`)?.classList.remove("hidden");
}

function showMissionPanes() {
  $("#mission-panes")?.classList.remove("hidden");
}

function setMtabCount(pane, label) {
  const btn = $(`.sf-mtab[data-pane="${pane}"]`);
  if (btn) btn.textContent = label;
}

function renderQA(q) {
  if (!q) return;
  // --- Tests pane ---
  const pre = $("#terminal-log");
  if (pre) {
    let head;
    if (q.ran) {
      head = `$ ${q.command || "tests"}\n${q.passed ?? 0} passed · ${q.failed ?? 0} failed`;
    } else {
      head = "No test suite detected (pytest / npm test not found on PATH).";
    }
    const body = (q.output || "").trim();
    pre.textContent = body ? `${head}\n\n${body}` : head;
    pre.classList.toggle("sf-pane-placeholder", !q.ran && !body);
    pre.scrollTop = pre.scrollHeight;
  }
  if (q.ran) {
    setMtabCount("terminal", q.failed ? `Tests · ${q.failed} fail` : `Tests · ${q.passed ?? 0} ok`);
  } else {
    setMtabCount("terminal", "Tests");
  }

  // --- Browser pane ---
  const shots = $("#browser-shots");
  if (shots) {
    const urls = q.checkedUrls || [];
    const findings = q.findings || [];
    const notes = q.notes || [];
    const screenshots = q.screenshots || [];
    if (!q.browserChecked && !screenshots.length) {
      shots.innerHTML = `<p class="sf-dim">No browser-checkable URLs in this build — browser QA skipped.</p>`;
      setMtabCount("browser", "Browser");
    } else {
      const parts = [];
      const findClass = findings.length ? "sf-qa-warn" : "sf-qa-ok";
      parts.push(
        `<div class="sf-qa-summary ${findClass}">${q.engine || "browser"} · ${urls.length} page${
          urls.length === 1 ? "" : "s"
        } checked · ${findings.length} finding${findings.length === 1 ? "" : "s"}</div>`
      );
      if (urls.length) {
        parts.push(`<ul class="sf-qa-urls">${urls.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>`);
      }
      if (findings.length) {
        parts.push(
          `<ul class="sf-qa-findings">${findings
            .map(
              (f) =>
                `<li><span class="sf-qa-sev">${esc(f.severity || "note")}</span> ${esc(f.url || "")} — ${esc(
                  f.note || ""
                )}</li>`
            )
            .join("")}</ul>`
        );
      } else if (notes.length) {
        parts.push(`<ul class="sf-qa-findings">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`);
      } else if (urls.length) {
        parts.push(`<p class="sf-dim">No blocking issues detected on checked URLs.</p>`);
      }
      if (screenshots.length) {
        parts.push(
          `<div class="sf-qa-shots">${screenshots
            .map(
              (p) =>
                `<img src="/api/projects/${activeProjectId}/artifact?path=${encodeURIComponent(
                  p
                )}" alt="screenshot" loading="lazy" />`
            )
            .join("")}</div>`
        );
      }
      shots.innerHTML = parts.join("");
      setMtabCount("browser", findings.length ? `Browser · ${findings.length}` : "Browser");
    }
  }
}

function renderQAFromReceipt(qa) {
  if (!qa) return;
  if (!qa.tests_ran && !qa.browser_checked && !(qa.screenshots || []).length) return;
  showMissionPanes();
  renderQA({
    ran: qa.tests_ran,
    command: qa.tests_command,
    passed: qa.tests_passed,
    failed: qa.tests_failed,
    output: qa.tests_output,
    browserChecked: qa.browser_checked,
    engine: qa.browser_engine,
    checkedUrls: qa.browser_checked_urls,
    findings: qa.findings,
    screenshots: qa.screenshots,
  });
}

function showToast(msg) {
  const root = $("#toast-root");
  if (!root) return;
  const el = document.createElement("div");
  el.className = "sf-toast";
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => el.remove(), 3600);
}

let runProgressPct = 0;

function setRunProgress(pct) {
  runProgressPct = Math.min(100, Math.max(0, pct));
  const bar = $("#run-progress");
  const fill = $("#run-progress-fill");
  if (!bar || !fill) return;
  bar.classList.toggle("hidden", runProgressPct <= 0);
  fill.style.width = `${runProgressPct}%`;
  bar.setAttribute("aria-valuenow", String(Math.round(runProgressPct)));
}

function renderPillarDots(pillars) {
  const el = $("#pillar-dots");
  if (!el || !pillars) return;
  const keys = ["composio", "tavily", "nebius", "mem0", "agent"];
  el.innerHTML = keys
    .map((k) => `<span class="sf-pillar-dot ${pillars[k] ? "on" : ""}" title="${k}"></span>`)
    .join("");
}

function renderKeysPillars(pillars) {
  const el = $("#keys-pillar-bar");
  if (!el || !pillars) return;
  const labels = { composio: "Composio", tavily: "Tavily", nebius: "Nebius", mem0: "Mem0", agent: "Agent" };
  el.innerHTML = Object.entries(labels)
    .map(
      ([k, label]) =>
        `<span class="sf-pillar-pill ${pillars[k] ? "ready" : ""}"><span class="dot"></span>${label}</span>`
    )
    .join("");
}

function phaseIcon(phaseId) {
  if (phaseId.startsWith("deploy")) return "🌐";
  if (phaseId.startsWith("mem0")) return "🧠";
  if (phaseId.startsWith("compress")) return "🗜";
  if (phaseId.startsWith("route")) return "🧠";
  if (phaseId.startsWith("agent")) return "⌨";
  if (phaseId.startsWith("qa")) return "✓";
  if (phaseId.startsWith("research-refresh")) return "🔍";
  return TOOL_ICONS[phaseId] || "•";
}

function timelineForPhase(phaseId, stage) {
  if (stage === "setup" || SETUP_PHASES.has(phaseId)) return $("#setup-timeline");
  return $("#loop-timeline");
}

function ensureStep(phaseId, tool, label, stage) {
  if ($(`#step-${phaseId}`)) return;
  const icon = phaseIcon(phaseId);
  const host = timelineForPhase(phaseId, stage);
  host.insertAdjacentHTML(
    "beforeend",
    `<div class="sf-step pending" data-phase="${phaseId}" id="step-${phaseId}">
      <div class="sf-step-icon">${icon}</div>
      <div class="sf-step-body">
        <div class="sf-step-tool">${esc(tool)}</div>
        <div class="sf-step-detail">${esc(label)}</div>
      </div>
    </div>`
  );
}

function buildTimeline() {
  const setupEl = $("#setup-timeline");
  const loopEl = $("#loop-timeline");
  setupEl.innerHTML = "";
  loopEl.innerHTML = "";
  pipeline
    .filter((p) => SETUP_PHASES.has(p.id))
    .forEach((p) => {
      setupEl.insertAdjacentHTML(
        "beforeend",
        `<div class="sf-step pending" data-phase="${p.id}" id="step-${p.id}">
      <div class="sf-step-icon">${TOOL_ICONS[p.id] || "•"}</div>
      <div class="sf-step-body">
        <div class="sf-step-tool">${esc(p.tool)}</div>
        <div class="sf-step-detail">${esc(p.label)}</div>
      </div>
    </div>`
      );
    });
  ensureStep("brand", "Nebius", "Product name & repo slug", "setup");
  ensureStep("composio-setup", "Composio", "Linear · GitHub · kickoff email", "setup");
  $("#loop-section")?.classList.add("hidden");
  $("#setup-section")?.classList.remove("sf-setup-collapsed");
  setupCollapsed = false;
  updateTurnBadge(0);
}

function updateTurnBadge(turn, maxTurns = currentMaxTurns) {
  currentTurn = turn;
  if (maxTurns) currentMaxTurns = maxTurns;
  const badge = $("#turn-badge");
  const loopLabel = $("#loop-turn-label");
  if (!turn) {
    badge?.classList.add("hidden");
    if (badge) badge.textContent = "";
    if (loopLabel) loopLabel.textContent = "";
    return;
  }
  if (!badge) return;
  badge.classList.remove("hidden");
  const cap = currentMaxTurns ? ` / ${currentMaxTurns}` : "";
  badge.textContent = `Turn ${turn}${cap}`;
  if (loopLabel) loopLabel.textContent = currentMaxTurns ? `turn ${turn} of ${currentMaxTurns}` : `turn ${turn}`;
}

function collapseSetup() {
  if (setupCollapsed) return;
  setupCollapsed = true;
  $("#setup-section")?.classList.add("sf-setup-collapsed");
}

function revealLoop() {
  $("#loop-section")?.classList.remove("hidden");
}

function setStep(phaseId, status, detail) {
  const step = $(`#step-${phaseId}`);
  if (!step) return;
  step.className = `sf-step ${status}`;
  if (detail) step.querySelector(".sf-step-detail").textContent = detail;
}

function resetTimeline() {
  buildTimeline();
  currentTurn = 0;
  setupCollapsed = false;
  setRunProgress(0);
  $("#mission-panes")?.classList.add("hidden");
  $("#nebius-panel")?.classList.add("hidden");
  $("#playbook-panel")?.classList.add("hidden");
  $("#subagents-panel")?.classList.add("hidden");
  const subagentsList = $("#subagents-list");
  if (subagentsList) subagentsList.innerHTML = "";
  const playByPlay = $("#play-by-play");
  if (playByPlay) playByPlay.innerHTML = "";
  $("#tracking-panel")?.classList.add("hidden");
  $("#link-linear")?.classList.add("hidden");
  $("#link-github")?.classList.add("hidden");
  const agentLog = $("#agent-log");
  if (agentLog) agentLog.textContent = "";
  setAgentLive(false);
  const followUp = $("#follow-up-list");
  if (followUp) followUp.innerHTML = "";
  const liveStatus = $("#live-status");
  if (liveStatus) {
    liveStatus.textContent = "Idle";
    liveStatus.classList.remove("running");
  }
}

function appendFollowUp(turn, prompt, kind) {
  $("#nebius-panel")?.classList.remove("hidden");
  const label = kind === "plan" ? "Initial plan" : `Follow-up turn ${turn}`;
  $("#follow-up-list")?.insertAdjacentHTML(
    "beforeend",
    `<li><span class="turn-tag">${esc(label)}</span>${esc(prompt)}</li>`
  );
}

function setAgentLive(on) {
  $("#agent-panel")?.classList.toggle("is-live", on);
  $("#agent-live-dot")?.classList.toggle("hidden", !on);
}

function showAgentPanel(message = "") {
  showMissionPanes();
  const log = $("#agent-log");
  if (message && log && !log.textContent.trim()) {
    log.textContent = message + "\n";
  }
}

function appendAgentLine(line) {
  showAgentPanel();
  const pre = $("#agent-log");
  if (!pre) return;
  pre.textContent += line + "\n";
  pre.scrollTop = pre.scrollHeight;
}

function syncAgentLog(log, running = false) {
  if (!log) return;
  showAgentPanel();
  $("#agent-log").textContent = log;
  $("#agent-log").scrollTop = $("#agent-log").scrollHeight;
  setAgentLive(running);
}

function setLiveStatus(text, running = false) {
  const el = $("#live-status");
  el.textContent = text;
  el.classList.toggle("running", running);
}

// Real context-compression stats stream in from actual runs (see showMemory).
// Until a run reports, show an honest empty state — never fabricated numbers.
let realContextSeen = false;

function fmtTokens(n) {
  return typeof n === "number" ? n.toLocaleString() : n ?? "—";
}

function contextStatsHTML({ sessions, processed, kept, mem0_recalled }) {
  const saved = Math.max(0, (processed || 0) - (kept || 0));
  const pct = processed ? (saved / processed) * 100 : 0;
  return `
    ${sessions != null ? `<div class="lp-ctx-row"><span>Creation sessions</span><strong>${sessions}</strong></div>` : ""}
    <div class="lp-ctx-row"><span>Tokens processed</span><strong>${fmtTokens(processed)}</strong></div>
    <div class="lp-ctx-row"><span>Sent to model</span><strong>${fmtTokens(kept)}</strong></div>
    <div class="lp-ctx-row lp-ctx-save"><span>Tokens saved</span><strong>${fmtTokens(saved)}</strong></div>
    <div class="lp-ctx-row"><span>Context compression</span><strong>${pct.toFixed(1)}%</strong></div>
    ${mem0_recalled != null ? `<div class="lp-ctx-row"><span>Mem0 recalled</span><strong>${fmtTokens(mem0_recalled)}</strong></div>` : ""}
  `;
}

function renderContextRest() {
  if (realContextSeen) return;
  const el = $("#settings-context-stats");
  if (el) el.innerHTML = `<p class="sf-keys-status">No runs yet — context-compression stats appear here after your first build.</p>`;
}

function showMemory(mem) {
  if (!mem) return;
  realContextSeen = true;
  const el = $("#settings-context-stats");
  if (!el) return;
  el.innerHTML = contextStatsHTML({
    processed: mem.original_tokens,
    kept: mem.kept_tokens,
    mem0_recalled: mem.mem0_recalled,
  });
}

function renderSubagents(data) {
  const panel = $("#subagents-panel");
  const list = $("#subagents-list");
  if (!panel || !list) return;
  const members =
    data.members ||
    (data.tasks || []).map((task, index) => ({ index, name: `sub${index + 1}`, task }));
  if (!members.length) return;
  panel.classList.remove("hidden");
  const count = $("#subagents-count");
  if (count) count.textContent = `${members.length} working · turn ${data.turn ?? ""}`.trim();
  list.innerHTML = members
    .map(
      (m) => `
    <li class="sf-subagent" data-index="${m.index}">
      <span class="sf-subagent-dot" data-status="queued"></span>
      <span class="sf-subagent-name">${esc(m.name)}</span>
      <span class="sf-subagent-task">${esc(m.task || "")}</span>
      <span class="sf-subagent-status" data-status="queued">queued</span>
    </li>`
    )
    .join("");
  showToast(`${data.agent || "Agent"} spawned ${members.length} subagents: ${members.map((m) => m.name).join(", ")}`);
}

function setSubagentStatus(index, name, status) {
  const panel = $("#subagents-panel");
  const list = $("#subagents-list");
  if (!panel || !list) return;
  panel.classList.remove("hidden");
  let row = list.querySelector(`.sf-subagent[data-index="${index}"]`);
  if (!row) {
    list.insertAdjacentHTML(
      "beforeend",
      `<li class="sf-subagent" data-index="${index}">
        <span class="sf-subagent-dot" data-status="${status}"></span>
        <span class="sf-subagent-name">${esc(name || `sub${(index ?? 0) + 1}`)}</span>
        <span class="sf-subagent-task"></span>
        <span class="sf-subagent-status" data-status="${status}">${esc(status)}</span>
      </li>`
    );
    row = list.querySelector(`.sf-subagent[data-index="${index}"]`);
  }
  if (!row) return;
  const dot = row.querySelector(".sf-subagent-dot");
  const label = row.querySelector(".sf-subagent-status");
  if (dot) dot.setAttribute("data-status", status);
  if (label) {
    label.setAttribute("data-status", status);
    label.textContent = status;
  }
}

function appendPlay(entry) {
  $("#playbook-panel")?.classList.remove("hidden");
  const time = entry.ts ? new Date(entry.ts).toLocaleTimeString() : new Date().toLocaleTimeString();
  const kind = entry.kind || "info";
  const href = entry.linear_url || entry.url || "";
  const link = href
    ? `<a href="${esc(href)}" target="_blank" rel="noopener">${kind === "linear" ? "Open Linear →" : kind === "github" ? "Open GitHub →" : "Open →"}</a>`
    : "";
  $("#play-by-play")?.insertAdjacentHTML(
    "beforeend",
    `<li class="sf-play-item sf-play-${esc(kind)}">
      <span class="sf-play-time">${esc(time)}</span>
      <span class="sf-play-msg">${esc(entry.message)}</span>
      ${link}
    </li>`
  );
  $("#play-by-play")?.lastElementChild?.scrollIntoView({ block: "nearest" });
  if (entry.linear_url || entry.github_url) {
    showTracking({
      linear_url: entry.linear_url,
      github_url: entry.github_url,
      linear_project: entry.linear_project,
      detail: entry.message,
    });
  }
}

function showTracking(data) {
  $("#tracking-panel")?.classList.remove("hidden");
  const lin = $("#link-linear");
  const gh = $("#link-github");
  if (lin && data.linear_url) {
    lin.href = data.linear_url;
    lin.classList.remove("hidden");
    lin.textContent = data.linear_project ? `Open Linear · ${data.linear_project} →` : "Open Linear project →";
  }
  if (gh && data.github_url) {
    gh.href = data.github_url;
    gh.classList.remove("hidden");
    gh.textContent = "GitHub repo";
  }
  const dep = $("#link-deploy");
  if (dep && data.deploy_url) {
    dep.href = data.deploy_url;
    dep.classList.remove("hidden");
    dep.textContent = "Live URL →";
  }
  if (data.detail) {
    const detail = $("#tracking-detail");
    if (detail) detail.textContent = data.detail;
  }
}

function handleEvent(data) {
  if (data.type === "snapshot") {
    applyRun(data.run);
    return;
  }
  if (data.type === "started") {
    resetTimeline();
    setRunProgress(8);
    showManualPanel(true);
    loadManualMessages([]);
    if (data.max_turns) {
      currentMaxTurns = data.max_turns;
      updateTurnBadge(0, data.max_turns);
    }
    const orch = data.orchestration === "smart_router" ? " · Nebius routing" : "";
    const budget = data.max_turns ? ` · ${data.max_turns} turn budget` : "";
    setLiveStatus(`Agent company running${budget}${orch}…`, true);
    showAgentPanel("Nebius plans within your turn budget — agents build around the clock");
    setLoopBtnRunning(true);
    return;
  }
  if (data.type === "skills_loaded") {
    const n = data.lesson_count || 0;
    appendPlay({ message: n ? `Skills loaded · ${n} lessons` : "Skills loaded", kind: "info" });
    return;
  }
  if (data.type === "setup_complete") {
    collapseSetup();
    revealLoop();
    setRunProgress(28);
    appendPlay({ message: "Setup complete — build loop started", kind: "info" });
    return;
  }
  if (data.type === "turn_started") {
    updateTurnBadge(data.turn, data.max_turns || currentMaxTurns);
    revealLoop();
    const pct = currentMaxTurns ? Math.min(88, 28 + (data.turn / currentMaxTurns) * 60) : 28 + Math.min(60, data.turn * 6);
    setRunProgress(pct);
    return;
  }
  if (data.type === "qa_output") {
    showMissionPanes();
    renderQA({
      ran: data.ran,
      command: data.command,
      passed: data.passed,
      failed: data.failed,
      output: data.output,
      browserChecked: data.browser_checked,
      engine: data.browser_engine,
      checkedUrls: data.checked_urls,
      findings: data.findings,
      notes: data.notes,
      screenshots: data.screenshots,
    });
    return;
  }
  if (data.type === "git_diff") {
    showMissionPanes();
    const pre = $("#diff-log");
    if (pre && data.diff) {
      pre.textContent = data.diff;
      pre.scrollTop = pre.scrollHeight;
    }
    return;
  }
  if (data.type === "turn_plan") {
    const skips = [];
    if (!data.run_agent) skips.push("agent");
    if (!data.run_qa) skips.push("QA");
    const hint = data.refresh_research ? " · research refresh next turn" : "";
    appendPlay({
      message: `Turn ${data.turn} route: ${data.reason || "continue"}${hint}${skips.length ? ` (skip: ${skips.join(", ")})` : ""}`,
      kind: "route",
    });
    return;
  }
  if (data.type === "phase") {
    ensureStep(data.phase, data.tool || data.phase, data.detail || "", data.stage);
    if (data.stage === "loop" || !SETUP_PHASES.has(data.phase)) revealLoop();
    if (data.phase === "composio-setup" && data.status === "done") collapseSetup();
    if (data.status === "running") {
      $$(`.sf-step.running`).forEach((s) => {
        if (s.id !== `step-${data.phase}`) {
          s.classList.remove("running");
          s.classList.add("done");
        }
      });
      setStep(data.phase, "running", data.detail);
      setLiveStatus(`${data.tool || data.phase}…`, true);
      if (data.phase.startsWith("agent")) {
        showAgentPanel();
        setAgentLive(true);
        $("#agent-tool").textContent = data.tool || "agent";
      } else if (data.phase.startsWith("nebius-review")) {
        setAgentLive(false);
      }
    }
    if (data.status === "done") {
      setStep(data.phase, "done", data.detail);
      if (data.memory) showMemory(data.memory);
      if (data.phase === "composio-setup") setRunProgress(25);
    }
    return;
  }
  if (data.type === "follow_up") {
    appendFollowUp(data.turn, data.prompt, data.kind || "follow_up");
    if (data.done) setLiveStatus("Nebius: build complete", true);
    return;
  }
  if (data.type === "agent_turn") {
    appendAgentLine(`\n─── Turn ${data.turn} · ${data.agent} ───`);
    return;
  }
  if (data.type === "subagents") {
    renderSubagents(data);
    return;
  }
  if (data.type === "subagent_start") {
    setSubagentStatus(data.index, data.name, "running");
    return;
  }
  if (data.type === "subagent_done") {
    setSubagentStatus(data.index, data.name, data.success ? "done" : "failed");
    return;
  }
  if (data.type === "agent_usage") {
    refreshAgentUsage();
    return;
  }
  if (data.type === "agent_failover") {
    showToast(`${data.from_agent} at ${Math.round(data.pct || 0)}% → ${data.to_agent}`);
    appendPlay({ message: data.reason || `Failover to ${data.to_agent}`, kind: "route" });
    refreshAgentUsage();
    return;
  }
  if (data.type === "agent_line") {
    appendAgentLine(data.line);
    setAgentLive(true);
    setLiveStatus("Coding agent running…", true);
    return;
  }
  if (data.type === "play_by_play") {
    appendPlay(data);
    return;
  }
  if (data.type === "tracking") {
    showTracking(data);
    return;
  }
  if (data.type === "manual_message") {
    renderManualMessage(data);
    return;
  }
  if (data.type === "manual_takeover") {
    markManualMessagesConsumed(data.turn);
    appendPlay({ message: `Manual takeover applied (${data.messages?.length || 0} msg)`, kind: "manual" });
    return;
  }
  if (data.type === "deploy" && data.url) {
    showTracking({ deploy_url: data.url, detail: `Deployed via ${data.provider || "CLI"}` });
    return;
  }
  if (data.type === "ship_receipt") {
    renderShipReceipt(data);
    return;
  }
  if (data.type === "complete") {
    stopAgentPoll(activeProjectId);
    setAgentLive(false);
    showManualPanel(false);
    setRunProgress(data.status === "completed" ? 100 : runProgressPct);
    setLiveStatus(data.status === "completed" ? "Complete ✓" : "Finished with errors", false);
    showToast(data.status === "completed" ? "Build complete" : "Run finished with errors");
    if (activeProjectId) setLoopBtnRunning(false);
    if (data.result?.memory) showMemory(data.result.memory);
    if (data.result?.ship_receipt) renderShipReceipt(data.result.ship_receipt);
    loadProjects();
    refreshAgentUsage();
    if (activeProjectId) loadFiles(activeProjectId);
    return;
  }
  if (data.type === "error") {
    stopAgentPoll(activeProjectId);
    setAgentLive(false);
    showManualPanel(false);
    setLiveStatus(`Error: ${data.message}`, false);
    if (activeProjectId) setLoopBtnRunning(false);
    loadProjects();
  }
}

function applyRun(run) {
  if (!run) return;
  buildTimeline();
  let maxTurn = 0;
  (run.phases || []).forEach((ph) => {
    ensureStep(ph.phase, ph.tool || ph.phase, ph.detail || "", ph.stage);
    if (ph.status === "done") setStep(ph.phase, "done", ph.detail);
    else if (ph.status === "running") setStep(ph.phase, "running", ph.detail);
    if (ph.stage === "loop" || !SETUP_PHASES.has(ph.phase)) revealLoop();
    const m = String(ph.phase).match(/^(?:agent|route|qa|compress)-(\d+)/);
    if (m) maxTurn = Math.max(maxTurn, parseInt(m[1], 10));
  });
  if (maxTurn) updateTurnBadge(maxTurn, run.result?.max_turns || currentMaxTurns);
  if ((run.phases || []).some((p) => p.phase === "composio-setup" && p.status === "done")) collapseSetup();
  if (run.agent_log) {
    syncAgentLog(run.agent_log, run.status === "running");
  }
  const memPhase = (run.phases || []).find((p) => p.memory)?.memory || run.result?.memory;
  if (memPhase) showMemory(memPhase);
  if (activeProjectId === run.project_id) renderQAFromReceipt(run.result?.ship_receipt?.qa);
  const tr = run.result?.tracking;
  if (tr?.linear_project_url || tr?.github_url) {
    showTracking({
      linear_url: tr.linear_project_url,
      github_url: tr.github_url,
      linear_project: tr.linear_project_name,
      deploy_url: run.result?.deploy?.url || run.result?.ship_receipt?.deploy_url,
    });
  }
  if (run.result?.ship_receipt && run.status === "completed") {
    if (activeProjectId === run.project_id) renderShipReceipt(run.result.ship_receipt);
    return;
  }
  if (run.status === "running") {
    if (activeProjectId === run.project_id) {
      showManualPanel(true);
      if (run.manual_messages) loadManualMessages(run.manual_messages);
      setLiveStatus("Running…", true);
      setLoopBtnRunning(true);
    }
  } else if (activeProjectId === run.project_id) {
    setLoopBtnRunning(false);
  }
}

function stopAgentPoll(projectId = activeProjectId) {
  if (agentPollTimer && projectId === activeProjectId) {
    clearInterval(agentPollTimer);
    agentPollTimer = null;
    activeRunId = null;
  }
}

function disconnectStream(projectId) {
  const slot = runStreams.get(projectId);
  if (slot?.eventSource) slot.eventSource.close();
  runStreams.delete(projectId);
  if (projectId === activeProjectId) {
    eventSource = null;
    stopAgentPoll(projectId);
  }
}

function startAgentPoll(rid) {
  if (agentPollTimer) clearInterval(agentPollTimer);
  activeRunId = rid;
  agentPollTimer = setInterval(async () => {
    if (!activeRunId) return;
    try {
      const run = await api(`/runs/${activeRunId}`);
      if (run.agent_log && activeProjectId === run.project_id) {
        syncAgentLog(run.agent_log, run.status === "running");
      }
      if (run.status !== "running") stopAgentPoll(run.project_id);
    } catch (_) {}
  }, 1500);
}

function connectStream(rid, projectId = activeProjectId) {
  if (!projectId) return;
  const existing = runStreams.get(projectId);
  if (existing?.runId === rid && existing?.eventSource?.readyState === 1) {
    eventSource = existing.eventSource;
    if (projectId === activeProjectId) startAgentPoll(rid);
    return;
  }
  disconnectStream(projectId);

  if (projectId === activeProjectId) startAgentPoll(rid);
  const es = new EventSource(`/api/runs/${rid}/stream`);
  eventSource = es;
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === "complete" || data.type === "error") {
        disconnectStream(projectId);
        loadProjects();
        refreshAgentUsage();
      }
      if (projectId === activeProjectId) handleEvent(data);
    } catch (_) {}
  };
  es.onerror = () => disconnectStream(projectId);
  runStreams.set(projectId, { runId: rid, eventSource: es });
}

async function resumeActiveRuns() {
  try {
    const { runs } = await api("/runs/active");
    for (const r of runs || []) {
      connectStream(r.run_id, r.project_id);
    }
  } catch (_) {}
}

async function loadHealth() {
  try {
    const h = await api("/health");
    pipeline = h.pipeline || [];
    buildTimeline();
    updateAgentSelect(h.agents || []);
  } catch (_) {}
}

function updateAgentSelect(agents) {
  const el = $("#settings-default-agent");
  if (!el || !agents.length) return;
  const current = el.value;
  el.innerHTML = agents
    .map((a) => {
      const local = a.local_auth ? " · local CLI" : "";
      const tag = a.available ? local : " (not installed)";
      return `<option value="${a.id}" ${a.available ? "" : "disabled"}>${esc(a.label)}${tag}</option>`;
    })
    .join("");
  if (current) el.value = current;
  else if (defaultAgent) el.value = defaultAgent;
}

function statusClass(status) {
  const s = String(status || "draft").toLowerCase();
  if (s === "built") return "sf-status-built";
  if (s === "researching") return "sf-status-researching";
  if (s === "error") return "sf-status-error";
  return "sf-status-draft";
}

function projectStatusLabel(p) {
  if (p.run_status === "running" || p.running_run_id) return { text: "Building", cls: "sf-status-running" };
  const s = String(p.status || "draft").toLowerCase();
  if (s === "built") return { text: "Shipped", cls: "sf-status-built" };
  if (s === "researching") return { text: "Building", cls: "sf-status-researching" };
  if (s === "error") return { text: "Error", cls: "sf-status-error" };
  return { text: "Draft", cls: "sf-status-draft" };
}

async function loadProjects() {
  const projects = await api("/projects");
  const ul = $("#project-list");
  if (!ul) return;
  ul.innerHTML = projects.length
    ? projects
        .map((p) => {
          const active = p.id === activeProjectId ? " active" : "";
          const st = projectStatusLabel(p);
          return `<li class="sf-project-item${active}">
        <button type="button" class="sf-project-card" data-id="${p.id}">
          <span class="sf-project-card-top">
            <span class="sf-project-status ${st.cls}">${esc(st.text)}</span>
            <span class="sf-project-agent">${esc(p.agent || "codex")}</span>
          </span>
          <span class="sf-project-name">${esc(p.name || "Untitled")}</span>
        </button>
        <button type="button" class="sf-project-delete" data-delete="${p.id}" aria-label="Delete project" title="Delete">×</button>
      </li>`;
        })
        .join("")
    : '<li class="sf-project-empty">No projects yet — start with an idea.</li>';
  ul.querySelectorAll(".sf-project-card[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => selectProject(btn.dataset.id));
  });
  ul.querySelectorAll(".sf-project-delete[data-delete]").forEach((btn) => {
    btn.addEventListener("click", (e) => deleteProject(btn.dataset.delete, e));
  });
  resumeActiveRuns();
}

function setMaxTurnsUI(enabled, value = "") {
  const toggle = $("#max-turns-toggle");
  const wrap = $("#max-turns-wrap");
  const input = $("#project-max-turns");
  if (toggle) toggle.checked = enabled;
  if (wrap) wrap.classList.toggle("hidden", !enabled);
  if (input) input.value = value ?? "";
  if (enabled && input && !input.value) input.placeholder = String(defaultMaxTurns);
}

function newProject() {
  if (activeProjectId) disconnectStream(activeProjectId);
  activeProjectId = null;
  activeRunId = null;
  $("#loop-prompt").value = "";
  setMaxTurnsUI(false);
  resetTimeline();
  showPage("compose");
  $("#view-settings")?.classList.add("hidden");
  setLoopBtnRunning(false);
  loadProjects();
}

function projectPageForRun(run, project) {
  if (!run) return "compose";
  if (run.status === "running") return "mission";
  if (run.status === "completed" && run.result?.ship_receipt) return "ship";
  if (run.status === "completed" || run.status === "error") return "mission";
  if (project?.status === "built") return run.result?.ship_receipt ? "ship" : "mission";
  if (project?.status === "researching" || project?.running_run_id) return "mission";
  return "compose";
}

async function selectProject(id) {
  if (activeProjectId && activeProjectId !== id) disconnectStream(activeProjectId);
  activeProjectId = id;

  const p = await api(`/projects/${id}`);
  await loadProjects();

  const prompt = $("#loop-prompt");
  if (prompt) prompt.value = p.idea || "";
  setMaxTurnsUI(Boolean(p.max_turn_budget), p.max_turn_budget ?? "");
  const folder = $("#loop-folder");
  if (folder) {
    // Show custom target dirs; hide Creation-managed ones (~/.creation/projects/...).
    const managed = /[\\/]\.creation[\\/]projects[\\/]/.test(p.workdir || "");
    folder.value = p.workdir && !managed ? p.workdir : "";
  }

  resetTimeline();
  showManualPanel(false);

  let page = "compose";
  let latestRun = null;

  if (p.runs?.length) {
    latestRun = p.runs[0];
    try {
      latestRun = await api(`/runs/${latestRun.id}`);
    } catch (_) {}

    applyRun(latestRun);
    if (latestRun?.manual_messages?.length) loadManualMessages(latestRun.manual_messages);

    page = projectPageForRun(latestRun, p);

    if (page === "ship" && latestRun?.result?.ship_receipt) {
      renderShipReceipt(latestRun.result.ship_receipt);
    }

    if (page === "mission") {
      showMissionPanes();
      revealLoop();
      if (latestRun?.status === "running") {
        connectStream(latestRun.id, id);
        setLiveStatus("Running…", true);
        showManualPanel(true);
        setLoopBtnRunning(true);
      } else {
        setLiveStatus(latestRun?.status === "error" ? "Error" : "Complete", false);
        setLoopBtnRunning(false);
      }
    }
  } else {
    setLiveStatus("Idle", false);
    setLoopBtnRunning(false);
  }

  showPage(page);
  await loadFiles(id);
}

async function loadFiles(id) {
  try {
    const files = await api(`/projects/${id}/files`);
    const sec = $("#files-section");
    if (!sec) return;
    if (files.length) {
      sec.classList.remove("hidden");
      const list = $("#file-list");
      if (list) list.innerHTML = files.map((f) => `<li>${esc(f)}</li>`).join("");
    } else {
      sec.classList.add("hidden");
    }
  } catch {
    $("#files-section")?.classList.add("hidden");
  }
}

async function deleteProject(id, e) {
  e?.stopPropagation();
  e?.preventDefault();
  if (
    !confirm("Remove this loop from history?\n\nManaged folders under ~/.creation/projects/ are deleted. Custom folders are kept.")
  ) {
    return;
  }
  try {
    await api(`/projects/${id}/delete`, { method: "POST" });
  } catch (err) {
    appendPlay({ message: err?.message || "Failed to delete project", kind: "error" });
    return;
  }
  if (activeProjectId === id) {
    activeProjectId = null;
    disconnectStream(id);
    newProject();
    return;
  }
  await loadProjects();
}

async function resolveLoopPrompt() {
  const input = $("#loop-prompt");
  let prompt = input?.value?.trim() || "";
  if (prompt) return prompt;
  try {
    const data = await api("/suggest", {
      method: "POST",
      body: JSON.stringify({ seed: "", count: 1 }),
    });
    const pick = data.suggestions?.[0];
    prompt = (pick?.idea || pick?.title || "").trim();
    if (prompt && input) input.value = prompt;
  } catch (_) {}
  if (!prompt) {
    prompt = "Greenfield MVP — research a real gap and ship a small useful product";
    if (input) input.value = prompt;
  }
  return prompt;
}

async function startLoop() {
  const btn = loopBtn();
  if (btn?.classList.contains("running")) return;

  let prompt = $("#loop-prompt")?.value?.trim() || "";
  if (!prompt) {
    setLiveStatus("Ideating…", true);
    if (btn) btn.disabled = true;
    try {
      prompt = await resolveLoopPrompt();
    } finally {
      if (btn && !activeRunId) btn.disabled = false;
    }
  }
  if (!prompt) return;
  const agent = defaultAgent || "codex";
  const template_id = "greenfield";
  const name = prompt.slice(0, 60) || `Loop ${new Date().toLocaleDateString()}`;
  const maxTurnEnabled = $("#max-turns-toggle")?.checked;
  let max_turn_budget = null;
  if (maxTurnEnabled) {
    const raw = $("#project-max-turns")?.value?.trim();
    max_turn_budget = raw ? parseInt(raw, 10) : defaultMaxTurns;
  }
  const workdir = $("#loop-folder")?.value?.trim() || "";
  const payload = { name, idea: prompt, agent, template_id, max_turn_budget, workdir };

  let pid = activeProjectId;
  const projects = await api("/projects");
  const current = pid ? projects.find((p) => p.id === pid) : null;
  if (current?.running_run_id) {
    pid = null;
    activeProjectId = null;
  }
  const existingRunning = pid && projects.find((p) => p.id === pid)?.running_run_id;
  if (existingRunning) {
    showToast("This project is already building");
    connectStream(existingRunning, pid);
    showPage("mission");
    return;
  }

  if (!pid) {
    const p = await api("/projects", { method: "POST", body: JSON.stringify(payload) });
    pid = p.id;
    activeProjectId = pid;
  } else {
    await api(`/projects/${pid}`, { method: "PATCH", body: JSON.stringify(payload) });
  }
  await loadProjects();

  resetTimeline();
  setLiveStatus("Starting…", true);
  setLoopBtnRunning(true);
  try {
    const { run_id } = await api(`/projects/${pid}/run`, {
      method: "POST",
      body: JSON.stringify({ seed: prompt, max_turn_budget }),
    });
    showMissionPanes();
    showPage("mission");
    connectStream(run_id, pid);
  } catch (e) {
    const msg = e?.message || "Failed to start";
    setLiveStatus(msg, false);
    appendPlay({ message: msg, kind: "error" });
    setLoopBtnRunning(false);
  }
}

async function loadSecrets() {
  const s = await api("/secrets");
  const form = $("#secrets-form");
  if (!form) return;
  for (const [k, v] of Object.entries(s)) {
    const el = form.elements.namedItem(k);
    if (el && v !== undefined && v !== null && v !== "") {
      if (el.type === "checkbox") el.checked = !!v;
      else if (el.type === "select-one" && typeof v === "boolean") el.value = v ? "true" : "false";
      else el.value = v;
    }
  }
  const mem0Toggle = form.elements.namedItem("mem0_enabled");
  if (mem0Toggle && s.mem0_enabled !== undefined) mem0Toggle.checked = !!s.mem0_enabled;
  const parallelToggle = form.elements.namedItem("parallel_agents");
  if (parallelToggle && s.parallel_agents !== undefined) parallelToggle.checked = !!s.parallel_agents;
  const subToggle = form.elements.namedItem("subagents_enabled");
  if (subToggle && s.subagents_enabled !== undefined) subToggle.checked = !!s.subagents_enabled;
  defaultAgent = s.default_agent || "codex";
  defaultMaxTurns = s.max_turn_budget || 200;
  const maxTurnsEl = $("#project-max-turns");
  if (maxTurnsEl) maxTurnsEl.placeholder = String(defaultMaxTurns);
  const failoverToggle = form.elements.namedItem("agent_failover_enabled");
  if (failoverToggle && s.agent_failover_enabled !== undefined) failoverToggle.checked = !!s.agent_failover_enabled;
  syncLinearProjectMode();
}

function syncLinearProjectMode() {
  const form = $("#secrets-form");
  if (!form) return;
  const mode = form.elements.namedItem("linear_project_mode")?.value || "create";
  const useExisting = mode === "existing";
  $$(".linear-existing-field").forEach((field) => {
    field.hidden = !useExisting;
    field.querySelectorAll("input").forEach((input) => {
      input.disabled = !useExisting;
    });
  });
}
window.syncLinearProjectMode = syncLinearProjectMode;

const REQUIRED_SECRETS = ["tavily_api_key", "nebius_api_key", "composio_api_key"];
const REQUIRED_INTEGRATIONS = [
  "github_owner",
  "linear_team_id",
  "composio_firecrawl_user_id",
  "gmail_notify_to",
];

async function saveSecrets(e) {
  e.preventDefault();
  const form = e.target;
  const missing = [];
  let checkServer = false;
  for (const name of REQUIRED_SECRETS) {
    const el = form.elements.namedItem(name);
    const val = el?.value?.trim() || "";
    const label = el?.closest("label")?.querySelector("span")?.textContent || name;
    if (!val) missing.push(label);
    else if (val.includes("••••")) checkServer = true;
  }
  for (const name of REQUIRED_INTEGRATIONS) {
    const el = form.elements.namedItem(name);
    const val = el?.value?.trim() || "";
    const label = el?.closest("label")?.querySelector("span")?.textContent || name;
    if (!val) missing.push(label);
  }
  if ((form.elements.namedItem("linear_project_mode")?.value || "create") === "existing") {
    const el = form.elements.namedItem("linear_project_id");
    if (!el?.value?.trim()) missing.push("Existing Linear project ID");
  }
  if (!missing.length && checkServer) {
    const h = await api("/health");
    const ok = {
      tavily_api_key: h.pillars?.tavily,
      nebius_api_key: h.pillars?.nebius,
      composio_api_key: h.pillars?.composio,
    };
    for (const k of REQUIRED_SECRETS) {
      if (!ok[k]) {
        const el = form.elements.namedItem(k);
        missing.push(el?.closest("label")?.querySelector("span")?.textContent || k);
      }
    }
  }
  if (missing.length) {
    $("#secrets-status").textContent = `Required: ${missing.join(", ")}`;
    return;
  }
  const fd = new FormData(form);
  const body = {};
  for (const [k, v] of fd.entries()) {
    if (v !== "" && !String(v).includes("••••")) body[k] = v;
  }
  if (body.memory_budget) body.memory_budget = parseFloat(body.memory_budget);
  if (body.max_turn_budget) body.max_turn_budget = parseInt(body.max_turn_budget, 10);
  if (body.max_concurrent_runs) body.max_concurrent_runs = parseInt(body.max_concurrent_runs, 10);
  if (body.max_subagents) body.max_subagents = parseInt(body.max_subagents, 10);
  if (body.agent_usage_failover_pct) body.agent_usage_failover_pct = parseFloat(body.agent_usage_failover_pct);
  const mem0Toggle = form.elements.namedItem("mem0_enabled");
  if (mem0Toggle) body.mem0_enabled = mem0Toggle.checked;
  const parallelToggle = form.elements.namedItem("parallel_agents");
  if (parallelToggle) body.parallel_agents = parallelToggle.checked;
  const subToggle = form.elements.namedItem("subagents_enabled");
  if (subToggle) body.subagents_enabled = subToggle.checked;
  const failoverToggle = form.elements.namedItem("agent_failover_enabled");
  if (failoverToggle) body.agent_failover_enabled = failoverToggle.checked;
  await api("/secrets", { method: "PUT", body: JSON.stringify(body) });
  $("#secrets-status").textContent = "Saved ✓";
  await loadSecrets();
  loadHealth();
  setTimeout(() => ($("#secrets-status").textContent = ""), 3000);
}

$$(".sf-nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

$("#loop-btn")?.addEventListener("click", startLoop);
$("#loop-prompt")?.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    startLoop();
  }
});
$("#new-project-btn")?.addEventListener("click", newProject);
$("#logo-home")?.addEventListener("click", (e) => {
  e.preventDefault();
  newProject();
});
$("#max-turns-toggle")?.addEventListener("change", (e) => {
  setMaxTurnsUI(e.target.checked);
});
$("#ship-copy-receipt")?.addEventListener("click", copyShipReceipt);
$("#ship-new-project")?.addEventListener("click", newProject);
$("#ship-view-log")?.addEventListener("click", () => showPage("mission"));
$$(".sf-mtab").forEach((btn) => {
  btn.addEventListener("click", () => switchMissionPane(btn.dataset.pane));
});
document.addEventListener("change", (event) => {
  if (event.target?.id === "linear-project-mode") syncLinearProjectMode();
});
$("#secrets-form")?.addEventListener("submit", saveSecrets);
$("#manual-message-form")?.addEventListener("submit", sendManualMessage);

function onboardingComplete(state) {
  if (!state) return false;
  return Boolean(state.complete);
}

function bootDashboard() {
  showPage("compose");
  loadHealth()
    .then(() => {
      loadProjects();
      loadSecrets();
    })
    .catch(() => {
      loadProjects().catch(() => {});
    });
}

async function gateOnboarding() {
  bootDashboard();
  const onboarded = localStorage.getItem("creation-onboarded") === "1";
  const timeoutMs = 5000;
  try {
    const state = await Promise.race([
      api("/composio/onboarding"),
      new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs)),
    ]);
    if (state && onboardingComplete(state)) {
      localStorage.setItem("creation-onboarded", "1");
      return;
    }
    if (!onboarded && state !== null) {
      window.location.replace("/onboarding");
    }
  } catch (_) {
    if (!onboarded) window.location.replace("/onboarding");
  }
}

gateOnboarding();
