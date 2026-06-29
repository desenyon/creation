export function Footer() {
  return (
    <footer style={{ borderTop: "1px solid var(--border)", marginTop: 80, padding: "32px 0" }}>
      <div className="container muted" style={{ fontSize: "0.85rem", display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <span>Creation · Local builds · Cloud account</span>
        <span>
          <a href="https://github.com/desenyon/creation">GitHub</a>
          {" · "}
          <a href="/api/health">API health</a>
        </span>
      </div>
    </footer>
  );
}
