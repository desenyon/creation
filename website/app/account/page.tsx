"use client";

import { useEffect, useState } from "react";

type Profile = {
  email: string;
  api_key: string;
  credits: number;
  github_connected: boolean;
  linear_connected: boolean;
};

export default function AccountPage() {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const path = mode === "register" ? "/api/account/register" : "/api/account/login";
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setProfile(data);
      if (data.api_key) localStorage.setItem("creation_api_key", data.api_key);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadMe() {
    const key = localStorage.getItem("creation_api_key");
    if (!key) return;
    const res = await fetch("/api/account/me", { headers: { Authorization: `Bearer ${key}` } });
    if (res.ok) setProfile(await res.json());
  }

  useEffect(() => {
    loadMe();
  }, []);

  return (
    <div className="container" style={{ padding: "48px 0 80px", maxWidth: 520 }}>
      <h1 style={{ marginBottom: 8 }}>Creation Cloud account</h1>
      <p className="muted" style={{ marginBottom: 24 }}>
        Sign up for an API key and credits. Use the same account in the CLI with{" "}
        <code>creation login</code>.
      </p>

      {profile ? (
        <div className="card">
          <p>
            Signed in as <strong>{profile.email}</strong>
          </p>
          <p style={{ marginTop: 12 }}>
            Credits: <span className="accent">{profile.credits.toLocaleString()}</span>
          </p>
          <label>API key</label>
          <code
            style={{
              display: "block",
              padding: 12,
              background: "#000",
              borderRadius: 8,
              marginTop: 6,
              wordBreak: "break-all",
              fontSize: "0.8rem",
            }}
          >
            {profile.api_key}
          </code>
          <p className="muted" style={{ marginTop: 16, fontSize: "0.85rem" }}>
            Add to <code>~/.creation/config.json</code> as <code>account_token</code> or run{" "}
            <code>creation login</code> locally.
          </p>
          <p style={{ marginTop: 12 }}>
            Relay GitHub: {profile.github_connected ? "connected" : "optional"} · Linear:{" "}
            {profile.linear_connected ? "connected" : "optional"}
          </p>
        </div>
      ) : (
        <form className="card" onSubmit={submit}>
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            <button
              type="button"
              className={`btn ${mode === "register" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode("register")}
            >
              Register
            </button>
            <button
              type="button"
              className={`btn ${mode === "login" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode("login")}
            >
              Sign in
            </button>
          </div>
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
          {error && <p style={{ color: "#f87171", marginTop: 12 }}>{error}</p>}
          <button type="submit" className="btn btn-primary" style={{ marginTop: 20 }} disabled={loading}>
            {loading ? "…" : mode === "register" ? "Create account" : "Sign in"}
          </button>
        </form>
      )}
    </div>
  );
}
