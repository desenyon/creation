/** Flat dashboard shell and Composio connection interactions. */

(() => {
  const sidebar = document.querySelector("#project-sidebar");
  const toggle = document.querySelector("#sidebar-toggle");
  const close = document.querySelector("#sidebar-close");
  const runWorkspace = document.querySelector("#run-workspace");
  const runHeading = document.querySelector(".sf-run-heading > div");
  const logo = document.querySelector(".sf-topbar-logo");

  if (logo) {
    logo.style.setProperty("background", "transparent", "important");
    logo.style.setProperty("border", "0", "important");
    logo.style.setProperty("border-radius", "0", "important");
    logo.style.setProperty("box-shadow", "none", "important");
  }

  async function request(path, options = {}) {
    const response = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) {}
    if (!response.ok) throw new Error(data.detail || text || `Request failed (${response.status})`);
    return data;
  }

  function onboardingComplete(state) {
    if (!state) return false;
    return Boolean(state.complete);
  }

  request("/composio/onboarding").then((state) => {
    if (onboardingComplete(state)) {
      localStorage.setItem("creation-onboarded", "1");
    }
  }).catch(() => {});

  function connectionMarkup(toolkit, label, field) {
    return `<div class="sf-connection-row">
      <label class="sf-key-field"><span>${label} Auth Config ID</span><input name="${field}" type="text" required placeholder="ac_..." /></label>
      <button type="button" class="sf-btn sf-btn-secondary" data-composio-connect="${toolkit}">Connect</button>
      <span class="sf-connection-status" data-composio-status="${toolkit}">Not connected</span>
    </div>`;
  }

  function prepareConnectionsUI() {
    const form = document.querySelector("#secrets-form");
    const owner = form?.elements.namedItem("github_owner");
    const section = owner?.closest(".sf-keys-card") || document.querySelector("#composio-connections-card");
    if (!form || !section) return;

    if (!section.id) {
      section.id = "composio-connections-card";
      section.innerHTML = `<div>
          <h2>Composio connections</h2>
          <p class="sf-keys-desc">Paste each <code>ac_...</code> Auth Config ID, then connect the account Creation should use.</p>
        </div>
        <div class="sf-keys-grid sf-connections-grid">
          ${connectionMarkup("github", "GitHub", "composio_github_auth_config_id")}
          ${connectionMarkup("linear", "Linear", "composio_linear_auth_config_id")}
          ${connectionMarkup("gmail", "Gmail", "composio_gmail_auth_config_id")}
          ${connectionMarkup("firecrawl", "Firecrawl", "composio_firecrawl_auth_config_id")}
          <label class="sf-key-field"><span>Linear project</span><select name="linear_project_mode" id="linear-project-mode"><option value="create">Create automatically</option><option value="existing">Use existing project</option></select></label>
          <label class="sf-key-field linear-existing-field" hidden><span>Existing Linear project ID</span><input name="linear_project_id" type="text" placeholder="project_…" disabled /></label>
          <label class="sf-key-field linear-existing-field" hidden><span>Existing Linear project URL</span><input name="linear_project_url" type="url" placeholder="https://linear.app/…" disabled /></label>
          <label class="sf-key-field linear-existing-field" hidden><span>Existing Linear project name</span><input name="linear_project_name" type="text" placeholder="optional display name" disabled /></label>
          <p id="settings-connections-status" class="sf-keys-status"></p>
        </div>
        <input type="hidden" name="github_owner" value="__composio__" />
        <input type="hidden" name="github_repo" value="__composio__" />
        <input type="hidden" name="linear_team_id" value="__composio__" />
        <input type="hidden" name="composio_firecrawl_user_id" value="__composio__" />
        <input type="hidden" name="gmail_notify_to" value="me" />`;
      bindConnectionButtons();
      window.syncLinearProjectMode?.();
    }
    const userId = form.elements.namedItem("composio_user_id");
    if (userId) userId.required = true;
  }

  function formPayload() {
    const form = document.querySelector("#secrets-form");
    const body = {};
    for (const [key, value] of new FormData(form).entries()) {
      if (value !== "" && !String(value).includes("••••")) body[key] = String(value).trim();
    }
    if (body.memory_budget) body.memory_budget = Number(body.memory_budget);
    if (body.max_turn_budget) body.max_turn_budget = Number(body.max_turn_budget);
    return body;
  }

  function renderConnectionStatus(state) {
    for (const [toolkit, item] of Object.entries(state.connections || {})) {
      const status = document.querySelector(`[data-composio-status="${toolkit}"]`);
      if (!status) continue;
      status.classList.toggle("is-connected", Boolean(item.connected));
      status.classList.toggle("is-error", item.status === "ERROR" || item.status === "FAILED");
      status.textContent = item.connected ? "Connected" : item.status === "ERROR" ? (item.error || "Check failed") : "Not connected";
    }
  }

  async function refreshConnections() {
    try {
      renderConnectionStatus(await request("/composio/connections"));
    } catch (error) {
      const status = document.querySelector("#settings-connections-status");
      if (status) status.textContent = error.message;
    }
  }

  async function connectToolkit(toolkit) {
    const status = document.querySelector("#settings-connections-status");
    const popup = window.open("about:blank", "_blank");
    try {
      await request("/secrets", { method: "PUT", body: JSON.stringify(formPayload()) });
      const callback = new URL("/dashboard", window.location.origin);
      callback.searchParams.set("composio", toolkit);
      const result = await request("/composio/connect", {
        method: "POST",
        body: JSON.stringify({ toolkit, callback_url: callback.toString() }),
      });
      if (popup) popup.location = result.redirect_url;
      else window.location.assign(result.redirect_url);
      if (status) status.textContent = `Finish ${toolkit} authentication in the opened tab.`;
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts += 1;
        await refreshConnections();
        const connected = document.querySelector(`[data-composio-status="${toolkit}"]`)?.classList.contains("is-connected");
        if (connected || attempts >= 90) clearInterval(poll);
      }, 2000);
    } catch (error) {
      popup?.close();
      if (status) status.textContent = error.message;
    }
  }

  function bindConnectionButtons() {
    document.querySelectorAll("[data-composio-connect]").forEach((button) => {
      button.addEventListener("click", () => connectToolkit(button.dataset.composioConnect));
    });
  }

  function prepareFolderPicker() {
    const input = document.querySelector("#loop-folder");
    const reset = document.querySelector("#loop-folder-clear");
    if (!input || !reset || document.querySelector("#loop-folder-choose")) return;

    input.readOnly = true;
    input.placeholder = "Choose a project folder";
    reset.textContent = "Default";

    const choose = document.createElement("button");
    choose.type = "button";
    choose.id = "loop-folder-choose";
    choose.className = "sf-text-btn";
    choose.textContent = "Choose folder";
    reset.before(choose);
    choose.addEventListener("click", async () => {
      choose.disabled = true;
      choose.textContent = "Opening...";
      try {
        const result = await request("/composio/folder", { method: "POST" });
        if (result.path) input.value = result.path;
      } catch (error) {
        window.alert(error.message);
      } finally {
        choose.disabled = false;
        choose.textContent = "Choose folder";
      }
    });
    reset.addEventListener("click", () => { input.value = ""; updateFolderHint(); });
    input.addEventListener("change", updateFolderHint);
    function updateFolderHint() {
      const hint = document.querySelector("#loop-folder-hint");
      if (!hint) return;
      if (input.value.trim()) {
        hint.innerHTML =
          "Existing repo mode — Creation will make <strong>scoped edits in place</strong> on a safe <code>creation/&lt;slug&gt;</code> branch. Describe the exact change above.";
      } else {
        hint.innerHTML =
          'Leave on Default for a fresh build under <code>~/.creation</code>, or choose an existing repo to make scoped edits in place.';
      }
    }
    updateFolderHint();
  }

  if (runHeading && !document.querySelector("#turn-badge")) {
    const turnBadge = document.createElement("span");
    turnBadge.id = "turn-badge";
    turnBadge.className = "sf-turn-badge hidden";
    runHeading.appendChild(turnBadge);
  }

  function setSidebar(open) {
    if (!sidebar || !toggle) return;
    sidebar.classList.toggle("is-open", open);
    sidebar.setAttribute("aria-hidden", String(!open));
    toggle.setAttribute("aria-expanded", String(open));
  }

  toggle?.addEventListener("click", () => setSidebar(!sidebar?.classList.contains("is-open")));
  close?.addEventListener("click", () => setSidebar(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setSidebar(false); });

  document.addEventListener("click", (event) => {
    if (event.target.closest(".sf-project-card[data-id]")) {
      runWorkspace?.classList.remove("hidden");
      setSidebar(false);
    }
    if (event.target.closest(".sf-nav-btn[data-view='settings']")) {
      setSidebar(false);
      prepareConnectionsUI();
      setTimeout(() => { prepareConnectionsUI(); refreshConnections(); }, 250);
    }
  });

  document.querySelector("#secrets-form")?.addEventListener("submit", prepareConnectionsUI, true);
  prepareConnectionsUI();
  prepareFolderPicker();
})();
