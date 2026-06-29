const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

let step = 0;
const total = 4;

function renderDots() {
  const el = $("#dots");
  if (!el) return;
  el.innerHTML = Array.from({ length: total }, (_, i) => {
    const cls = i === step ? "active" : i < step ? "done" : "";
    return `<span class="${cls}"></span>`;
  }).join("");
}

function showStep(n) {
  step = Math.max(0, Math.min(total - 1, n));
  $$(".ob-step").forEach((panel) => {
    panel.classList.toggle("active", Number(panel.dataset.step) === step);
  });
  renderDots();
  if (step === 1) refreshAccount();
  if (step === 2) loadAgents();
}

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) {}
  if (!res.ok) throw new Error(data.detail || text || `Request failed (${res.status})`);
  return data;
}

async function refreshAccount() {
  try {
    const me = await api("/account/me");
    $("#acct-out")?.classList.add("hidden");
    $("#acct-in")?.classList.remove("hidden");
    if ($("#acct-email")) $("#acct-email").textContent = me.email || "—";
    if ($("#acct-credits")) $("#acct-credits").textContent = String(me.credits ?? "—");
  } catch {
    $("#acct-out")?.classList.remove("hidden");
    $("#acct-in")?.classList.add("hidden");
  }
}

async function loadAgents() {
  try {
    const h = await api("/health");
    const sel = $("#ob-agent");
    if (!sel || !h.agents?.length) return;
    sel.innerHTML = h.agents.map((a) => `<option value="${a}">${a}</option>`).join("");
    const sec = await api("/secrets");
    if (sec.default_agent) sel.value = sec.default_agent;
  } catch (_) {}
}

$("#ob-login")?.addEventListener("click", async () => {
  const status = $("#acct-status");
  try {
    await api("/account/login", {
      method: "POST",
      body: JSON.stringify({ email: $("#ob-email").value, password: $("#ob-password").value }),
    });
    await refreshAccount();
    if (status) status.textContent = "";
  } catch (e) {
    if (status) status.textContent = e.message;
  }
});

$("#ob-register")?.addEventListener("click", async () => {
  const status = $("#acct-status");
  try {
    await api("/account/register", {
      method: "POST",
      body: JSON.stringify({ email: $("#ob-email").value, password: $("#ob-password").value }),
    });
    await refreshAccount();
    if (status) status.textContent = "";
  } catch (e) {
    if (status) status.textContent = e.message;
  }
});

$("#relay-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {};
  for (const [k, v] of new FormData(e.target).entries()) {
    if (v && !String(v).includes("••••")) body[k] = String(v).trim();
  }
  try {
    await api("/secrets", { method: "PATCH", body: JSON.stringify(body) });
    showStep(3);
  } catch (err) {
    alert(err.message);
  }
});

$("#ob-skip-relay")?.addEventListener("click", () => showStep(3));

$$("[data-next]").forEach((btn) => btn.addEventListener("click", () => showStep(step + 1)));
$$("[data-back]").forEach((btn) => btn.addEventListener("click", () => showStep(step - 1)));

renderDots();
