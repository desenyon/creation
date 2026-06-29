(() => {
  const $ = (s) => document.querySelector(s);
  const status = (m) => { $("#status").textContent = m; };

  let apiKey = "";
  let activeProject = null;
  let activeRun = null;

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (apiKey) h["X-API-Key"] = apiKey;
    return h;
  }

  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { ...headers(), ...(opts.headers || {}) } });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  document.querySelectorAll(".studio-nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".studio-nav button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".studio-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`panel-${btn.dataset.panel}`).classList.add("active");
    });
  });

  async function loadAccount() {
    try {
      const sec = await api("/api/secrets");
      if (sec.account_token) {
        apiKey = sec.account_token;
        const me = await api("/api/account/me");
        $("#account-signed-out").classList.add("hidden");
        $("#account-signed-in").classList.remove("hidden");
        $("#account-email").textContent = me.email;
        $("#account-key").textContent = me.api_key;
        $("#account-credits").textContent = me.credits;
        $("#credits").textContent = `Credits ${me.credits}`;
      }
    } catch (e) {
      status("Account not loaded");
    }
  }

  async function loadProjects() {
    const projects = await api("/api/projects");
    const ul = $("#project-list");
    ul.innerHTML = "";
    projects.forEach((p) => {
      const li = document.createElement("li");
      li.textContent = (p.name || p.idea || "Project").slice(0, 48);
      li.innerHTML += `<span class="studio-badge">${p.status || "idle"}</span>`;
      li.onclick = () => { activeProject = p.id; streamLatestRun(p.id); };
      ul.appendChild(li);
    });
  }

  async function streamLatestRun(projectId) {
    const proj = await api(`/api/projects/${projectId}`);
    const runs = proj.runs || [];
    if (!runs.length) return;
    activeRun = runs[0].id;
    const log = $("#event-log");
    log.textContent = "";
    const es = new EventSource(`/api/runs/${activeRun}/stream`);
    es.onmessage = (ev) => {
      if (ev.data === "[DONE]") { es.close(); return; }
      try {
        const e = JSON.parse(ev.data);
        if (e.type === "agent_line") log.textContent += e.line + "\n";
        else if (e.message) log.textContent += `· ${e.message}\n`;
        else log.textContent += JSON.stringify(e).slice(0, 200) + "\n";
        log.scrollTop = log.scrollHeight;
      } catch { log.textContent += ev.data + "\n"; }
    };
  }

  $("#btn-login").onclick = async () => {
    const body = { email: $("#login-email").value, password: $("#login-password").value };
    await api("/api/account/login", { method: "POST", body: JSON.stringify(body) });
    await loadAccount();
    status("Signed in");
  };

  $("#btn-register").onclick = async () => {
    const body = { email: $("#login-email").value, password: $("#login-password").value };
    await api("/api/account/register", { method: "POST", body: JSON.stringify(body) });
    await loadAccount();
    status("Account created");
  };

  $("#start-build").onclick = async () => {
    const idea = $("#idea").value.trim();
    if (!idea) return status("Enter an idea");
    status("Starting build…");
    const body = { idea };
    const wd = $("#workdir").value.trim();
    if (wd) body.workdir = wd;
    const p = await api("/api/projects", { method: "POST", body: JSON.stringify(body) });
    const run = await api(`/api/projects/${p.id}/run`, { method: "POST", body: "{}" });
    activeProject = p.id;
    activeRun = run.run_id;
    document.querySelector('[data-panel="runs"]').click();
    await loadProjects();
    streamLatestRun(p.id);
    status(`Build ${String(run.run_id).slice(0, 8)} started`);
  };

  $("#relay-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    await api("/api/account/credentials", { method: "PUT", body: JSON.stringify(body) });
    status("Relay credentials saved");
  };

  async function loadAgents() {
    const agents = await api("/api/agents/usage");
    const sel = $("#default-agent");
    sel.innerHTML = "";
    (agents.agents || []).forEach((a) => {
      const o = document.createElement("option");
      o.value = a.name;
      o.textContent = `${a.name} ${a.available ? "✓" : "—"}`;
      sel.appendChild(o);
    });
  }

  $("#save-agent").onclick = async () => {
    await api("/api/secrets", { method: "PUT", body: JSON.stringify({ default_agent: $("#default-agent").value }) });
    status("Agent saved");
  };

  (async () => {
    await loadAccount();
    await loadProjects();
    await loadAgents();
    status("Studio ready");
  })();
})();
