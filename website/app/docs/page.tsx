import Link from "next/link";

export default function DocsPage() {
  return (
    <div className="container" style={{ padding: "48px 0 80px", maxWidth: 720 }}>
      <h1 style={{ marginBottom: 16 }}>Documentation</h1>
      <p className="muted" style={{ marginBottom: 32 }}>
        Creation splits work between Creation Cloud (account + Forge) and your local machine (agents + builds).
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: "1.1rem", marginBottom: 8 }}>Install</h2>
        <pre style={{ overflow: "auto", fontSize: "0.85rem" }}>curl -fsSL https://creation.dev/install | bash</pre>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: "1.1rem", marginBottom: 8 }}>Cloud API</h2>
        <ul className="muted" style={{ paddingLeft: 20, fontSize: "0.9rem" }}>
          <li>
            <code>POST /api/account/register</code> — create account
          </li>
          <li>
            <code>POST /api/account/login</code> — sign in
          </li>
          <li>
            <code>GET /api/account/me</code> — profile (Bearer API key)
          </li>
          <li>
            <code>POST /api/forge/v1/chat/completions</code> — Forge planning
          </li>
          <li>
            <code>GET /api/health</code> — service status
          </li>
        </ul>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: "1.1rem", marginBottom: 8 }}>Local CLI</h2>
        <pre style={{ overflow: "auto", fontSize: "0.85rem", lineHeight: 1.6 }}>
{`creation setup          # setup wizard
creation login          # sync cloud account locally
creation serve          # Studio at :8787
creation build "idea"   # full build loop
creation doctor         # check agents & Relay`}
        </pre>
      </div>

      <div className="card">
        <h2 style={{ fontSize: "1.1rem", marginBottom: 8 }}>Environment</h2>
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          <code>CREATION_CLOUD_URL</code> — cloud API base (default: https://creation.dev)
          <br />
          <code>OPENAI_API_KEY</code> — optional Forge backend on Vercel
          <br />
          Link <strong>Vercel KV</strong> in the project for persistent accounts in production.
        </p>
      </div>

      <p style={{ marginTop: 24 }}>
        Full reference on{" "}
        <Link href="https://github.com/desenyon/creation/blob/main/README.md">GitHub README</Link>.
      </p>
    </div>
  );
}
