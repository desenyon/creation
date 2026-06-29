const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

let step = 0;
const total = 6;
const CORE_REQUIRED = ["tavily_api_key", "nebius_api_key", "composio_api_key", "composio_user_id"];
const AUTH_FIELDS = {
  github: "composio_github_auth_config_id",
  linear: "composio_linear_auth_config_id",
  gmail: "composio_gmail_auth_config_id",
  firecrawl: "composio_firecrawl_auth_config_id",
};

function renderSteps() {
  const el = $("#ob-steps");
  if (!el) return;
  el.innerHTML = Array.from({ length: total }, (_, i) => {
    const cls = i === step ? "active" : i < step ? "done" : "";
    return `<span class="${cls}" aria-hidden="true"></span>`;
  }).join("");
}

function showStep(n) {
  step = Math.max(0, Math.min(total - 1, n));
  $$(".ob-panel").forEach((panel) => {
    panel.classList.toggle("hidden", Number(panel.dataset.step) !== step);
  });
  renderSteps();
  if (step === 4 && typeof refreshMemoryDetection === "function") refreshMemoryDetection();
}

async function api(path, opts = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) {}
  if (!response.ok) throw new Error(data.detail || text || `Request failed (${response.status})`);
  return data;
}

function formBody(form) {
  const body = {};
  for (const [key, value] of new FormData(form).entries()) {
    const input = form.elements.namedItem(key);
    if (input?.type === "checkbox") continue;
    if (value !== "" && !String(value).includes("••••")) body[key] = String(value).trim();
  }
  const mem0Toggle = form.elements.namedItem("mem0_enabled");
  if (mem0Toggle) body.mem0_enabled = mem0Toggle.checked;
  return body;
}

function missingFields(form, names) {
  return names.flatMap((name) => {
    const input = form.elements.namedItem(name);
    const value = input?.value?.trim() || "";
    if (value) return [];
    return [input?.closest("label")?.querySelector("span")?.textContent || name];
  });
}

function authConfigErrors(form) {
  const errors = [];
  for (const [toolkit, name] of Object.entries(AUTH_FIELDS)) {
    const value = form.elements.namedItem(name)?.value?.trim() || "";
    if (!value) errors.push(`${toolkit} Auth Config ID`);
    else if (!value.startsWith("ac_")) errors.push(`${toolkit} ID must start with ac_`);
  }
  return errors;
}

async function loadAgents() {
  try {
    const h = await api("/health");
    const sel = $("#ob-default-agent");
    if (!sel || !h.agents?.length) return;
    const current = sel.value;
    sel.innerHTML = h.agents
      .map((a) => {
        const local = a.local_auth;
        const tag = a.available ? (local ? " · local CLI" : "") : " (not installed)";
        return `<option value="${a.id}" ${a.available ? "" : "disabled"}>${a.label}${tag}</option>`;
      })
      .join("");
    if (current) sel.value = current;
  } catch (_) {}
}

async function loadExisting() {
  try {
    const secrets = await api("/secrets");
    for (const [key, value] of Object.entries(secrets)) {
      const input = document.querySelector(`[name="${key}"]`);
      if (!input) continue;
      if (input.type === "checkbox") input.checked = !!value;
      else if (value !== undefined && value !== null && value !== "") input.value = value;
    }
  } catch (_) {}
}

function renderConnectionStatus(state) {
  for (const [toolkit, item] of Object.entries(state.connections || {})) {
    const status = document.querySelector(`[data-composio-status="${toolkit}"]`);
    const button = document.querySelector(`[data-composio-connect="${toolkit}"]`);
    if (!status) continue;
    status.classList.toggle("is-connected", Boolean(item.connected));
    status.classList.toggle("is-error", item.status === "ERROR" || item.status === "FAILED");
    status.textContent = item.connected ? "Connected" : item.status === "ERROR" ? (item.error || "Connection check failed") : "Not connected";
    if (button) button.textContent = item.connected ? `Reconnect ${toolkit}` : `Connect ${toolkit}`;
  }
  return Boolean(state.ready);
}

async function refreshConnections() {
  try {
    return renderConnectionStatus(await api("/composio/connections"));
  } catch (error) {
    const status = $("#ob-connections-status");
    if (status) status.textContent = error.message;
    return false;
  }
}

async function saveConnectionConfig() {
  const form = $("#ob-connections-form");
  const errors = authConfigErrors(form);
  if (errors.length) throw new Error(`Required: ${errors.join(", ")}`);
  await api("/secrets", { method: "PUT", body: JSON.stringify(formBody(form)) });
}

async function connectToolkit(toolkit) {
  const status = $("#ob-connections-status");
  const popup = window.open("about:blank", "_blank");
  try {
    await saveConnectionConfig();
    if (status) status.textContent = `Creating ${toolkit} Connect Link…`;
    const callback = new URL("/onboarding", window.location.origin);
    callback.searchParams.set("composio", toolkit);
    const result = await api("/composio/connect", {
      method: "POST",
      body: JSON.stringify({ toolkit, callback_url: callback.toString() }),
    });
    if (popup) popup.location = result.redirect_url;
    else window.location.assign(result.redirect_url);
    if (status) status.textContent = `Finish ${toolkit} authentication in the opened tab.`;
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts += 1;
      const ready = await refreshConnections();
      const connected = document.querySelector(`[data-composio-status="${toolkit}"]`)?.classList.contains("is-connected");
      if (ready || connected || attempts >= 90) clearInterval(poll);
    }, 2000);
  } catch (error) {
    popup?.close();
    if (status) status.textContent = error.message;
  }
}

const MEMORY_LABELS = { mem0: "Mem0", supermemory: "Supermemory", off: "Off", auto: "Auto" };

async function refreshMemoryDetection() {
  const hint = $("#ob-memory-detected");
  if (!hint) return;
  try {
    const status = await api("/memory/status");
    const detected = Object.entries(status.available || {})
      .filter(([, ok]) => ok)
      .map(([name]) => MEMORY_LABELS[name] || name);
    const resolved = MEMORY_LABELS[status.resolved] || status.resolved || "none";
    if (detected.length) {
      hint.textContent = `We found ${detected.join(", ")} on your machine — auto resolves to ${resolved}. Keep auto, or pin a provider below.`;
    } else {
      hint.textContent = `No existing memory stack detected — auto resolves to ${resolved}. Add a key below or keep auto.`;
    }
  } catch (_) {
    hint.textContent = "Could not detect your memory stack — auto is a safe default.";
  }
}

$("#ob-memory-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const status = $("#ob-memory-status");
  try {
    await api("/secrets", { method: "PUT", body: JSON.stringify(formBody(form)) });
    status.textContent = "Memory choice saved";
    showStep(step + 1);
  } catch (error) {
    status.textContent = error.message;
  }
});

$$('.ob-next').forEach((button) => button.addEventListener("click", () => showStep(step + 1)));
$$('.ob-back').forEach((button) => button.addEventListener("click", () => showStep(step - 1)));
$$('[data-composio-connect]').forEach((button) => {
  button.addEventListener("click", () => connectToolkit(button.dataset.composioConnect));
});

$("#ob-keys-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const status = $("#ob-keys-status");
  const missing = missingFields(form, CORE_REQUIRED);
  if (missing.length) {
    status.textContent = `Required: ${missing.join(", ")}`;
    return;
  }
  try {
    await api("/secrets", { method: "PUT", body: JSON.stringify(formBody(form)) });
    status.textContent = "Saved";
    showStep(2);
    await refreshConnections();
  } catch (error) {
    status.textContent = error.message;
  }
});

$("#ob-connections-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = $("#ob-connections-status");
  try {
    await saveConnectionConfig();
    const ready = await refreshConnections();
    if (!ready) throw new Error("Connect GitHub, Linear, Gmail, and Firecrawl before continuing.");
    status.textContent = "All integrations connected";
    showStep(3);
  } catch (error) {
    status.textContent = error.message;
  }
});

const callbackToolkit = new URLSearchParams(window.location.search).get("composio");
if (callbackToolkit) showStep(2);
else renderSteps();

function onboardingComplete(state) {
  if (!state) return false;
  if (state.complete) return true;
  if (state.configured) return true;
  if (state.core && Object.values(state.core).every(Boolean)) return true;
  return false;
}

async function maybeSkipOnboarding() {
  try {
    const state = await api("/composio/onboarding");
    await loadExisting();
    if (onboardingComplete(state)) {
      localStorage.setItem("creation-onboarded", "1");
      if (state.complete) {
        window.location.replace("/dashboard");
        return;
      }
      const authDone = state.auth_configs && Object.values(state.auth_configs).every(Boolean);
      showStep(authDone ? 3 : 2);
    }
    await refreshConnections();
  } catch (_) {
    await refreshConnections();
  }
}

Promise.all([loadAgents(), loadExisting(), refreshMemoryDetection()]).then(maybeSkipOnboarding);
