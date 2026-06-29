import Link from "next/link";

const features = [
  { title: "Autonomous loop", desc: "Research once, then code → QA → ship until done." },
  { title: "Your agents", desc: "Codex, Claude, Cursor, Gemini — whatever is on your PATH." },
  { title: "Cloud account", desc: "One login, API key, and credits on Creation Cloud." },
  { title: "Honest receipts", desc: "Ship proof that only claims what actually happened." },
  { title: "Studio + TUI", desc: "Browser dashboard or full shell control locally." },
  { title: "Demo mode", desc: "Try the full loop without live Relay credentials." },
];

const stack = [
  { name: "Account", desc: "Auth, API keys, credits" },
  { name: "Forge", desc: "Planning & routing (cloud)" },
  { name: "Lens", desc: "Research on your machine" },
  { name: "Prism", desc: "Memory & compression" },
  { name: "Relay", desc: "GitHub & Linear" },
  { name: "Pulse", desc: "Notifications on ship" },
];

export default function HomePage() {
  return (
    <>
      <section style={{ position: "relative", padding: "72px 0 48px", overflow: "hidden" }}>
        <div className="hero-glow" aria-hidden />
        <div className="container" style={{ position: "relative" }}>
          <img src="/assets/img/logo.svg" alt="Creation" width={72} height={72} style={{ marginBottom: 24 }} />
          <h1 style={{ fontSize: "clamp(2.2rem, 5vw, 3.4rem)", lineHeight: 1.1, maxWidth: "16ch", marginBottom: 16 }}>
            Turn ideas into shipped software.
          </h1>
          <p className="muted" style={{ fontSize: "1.15rem", maxWidth: "52ch", marginBottom: 32 }}>
            Creation is a local-first agent OS. Your coding agents run on your machine. Account, Forge planning, and
            credits live on Creation Cloud — one login, no vendor patchwork.
          </p>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Link href="/#install" className="btn btn-primary">
              Install Creation
            </Link>
            <Link href="/account" className="btn btn-ghost">
              Create account
            </Link>
          </div>
        </div>
      </section>

      <section className="container" style={{ padding: "48px 0" }}>
        <div className="grid grid-3">
          {features.map((f) => (
            <div key={f.title} className="card">
              <h3 className="mono accent" style={{ fontSize: "0.95rem", marginBottom: 8 }}>
                {f.title}
              </h3>
              <p className="muted" style={{ fontSize: "0.9rem" }}>
                {f.desc}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section id="how" className="container" style={{ padding: "48px 0" }}>
        <h2 style={{ marginBottom: 12 }}>How it works</h2>
        <p className="muted" style={{ maxWidth: "60ch", marginBottom: 24 }}>
          Cloud handles identity and Forge. Your laptop runs the build loop, agents, Prism memory, and Relay shipping.
        </p>
        <pre
          className="card"
          style={{
            overflow: "auto",
            fontSize: "0.8rem",
            lineHeight: 1.5,
            color: "var(--muted)",
          }}
        >
{`  Your idea
      │
      ▼
  Creation Cloud ── Account · Forge · API key
      │
      ▼
  Local machine ── Lens · Prism · Agents · Relay · Pulse
      │
      ▼
  GitHub · Linear · ship receipt`}
        </pre>
      </section>

      <section className="container" style={{ padding: "48px 0" }}>
        <h2 className="mono muted" style={{ fontSize: "0.85rem", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 16 }}>
          Built-in stack
        </h2>
        <div className="grid grid-3">
          {stack.map((s) => (
            <div key={s.name} className="card">
              <strong className="accent">{s.name}</strong>
              <p className="muted" style={{ fontSize: "0.9rem", marginTop: 6 }}>
                {s.desc}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section id="install" className="container" style={{ padding: "48px 0 80px" }}>
        <h2 style={{ marginBottom: 12 }}>One-command install</h2>
        <p className="muted" style={{ marginBottom: 16 }}>
          Installs the CLI, links to Creation Cloud, and launches the setup wizard.
        </p>
        <pre
          className="card"
          style={{ padding: 20, overflow: "auto", fontSize: "0.85rem" }}
        >
          curl -fsSL https://creation.dev/install | bash
        </pre>
        <p className="muted" style={{ marginTop: 16, fontSize: "0.9rem" }}>
          Or: <code>pip install git+https://github.com/desenyon/creation.git</code> then <code>creation setup</code>
        </p>
      </section>
    </>
  );
}
