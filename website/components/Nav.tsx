import Link from "next/link";

export function Nav() {
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        background: "rgba(9,9,11,0.85)",
        backdropFilter: "blur(8px)",
        position: "sticky",
        top: 0,
        zIndex: 50,
      }}
    >
      <div
        className="container"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 0",
        }}
      >
        <Link href="/" className="mono accent" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
          <img src="/assets/img/icon.svg" alt="" width={24} height={24} />
          CREATION
        </Link>
        <nav style={{ display: "flex", gap: 20, alignItems: "center", fontSize: "0.9rem" }}>
          <Link href="/#how">How it works</Link>
          <Link href="/account">Account</Link>
          <Link href="/docs">Docs</Link>
          <a href="https://github.com/desenyon/creation" target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
          <Link href="/#install" className="btn btn-primary" style={{ padding: "8px 14px", fontSize: "0.85rem" }}>
            Install
          </Link>
        </nav>
      </div>
    </header>
  );
}
