"""Creation account — local users, API keys, credits, and connected services."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ACCOUNT_DB = Path.home() / ".creation" / "account.db"
FREE_CREDITS = 500_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


@dataclass
class AccountUser:
    id: str
    email: str
    api_key: str
    credits: int
    github_token: str = ""
    linear_api_key: str = ""
    linear_team_id: str = ""
    notify_email: str = ""


class AccountStore:
    def __init__(self, db_path: Path = ACCOUNT_DB) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    api_key TEXT UNIQUE NOT NULL,
                    credits INTEGER NOT NULL DEFAULT 0,
                    github_token TEXT DEFAULT '',
                    linear_api_key TEXT DEFAULT '',
                    linear_team_id TEXT DEFAULT '',
                    notify_email TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    units INTEGER NOT NULL,
                    detail TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    def register(self, email: str, password: str) -> AccountUser:
        email = email.strip().lower()
        if not email or not password:
            raise ValueError("Email and password required")
        user_id = secrets.token_hex(8)
        api_key = f"crt_live_{secrets.token_urlsafe(24)}"
        salt = secrets.token_hex(16)
        pw_hash = _hash_password(password, salt)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, salt, api_key, credits, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, email, pw_hash, salt, api_key, FREE_CREDITS, _now()),
            )
        return self.get_by_email(email)  # type: ignore[return-value]

    def login(self, email: str, password: str) -> tuple[AccountUser, str]:
        user = self.get_by_email(email.strip().lower())
        if not user:
            raise ValueError("Invalid email or password")
        with self._connect() as conn:
            row = conn.execute("SELECT password_hash, salt FROM users WHERE id = ?", (user.id,)).fetchone()
        if not row or _hash_password(password, row["salt"]) != row["password_hash"]:
            raise ValueError("Invalid email or password")
        session = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (session, user.id, _now(), _now()),
            )
        return user, session

    def get_by_api_key(self, api_key: str) -> Optional[AccountUser]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key.strip(),)).fetchone()
        return self._row_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[AccountUser]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return self._row_user(row) if row else None

    def get_by_session(self, token: str) -> Optional[AccountUser]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.* FROM users u
                JOIN sessions s ON s.user_id = u.id
                WHERE s.token = ?
                """,
                (token.strip(),),
            ).fetchone()
        return self._row_user(row) if row else None

    def update_credentials(
        self,
        user_id: str,
        *,
        github_token: str | None = None,
        linear_api_key: str | None = None,
        linear_team_id: str | None = None,
        notify_email: str | None = None,
    ) -> AccountUser:
        fields: Dict[str, Any] = {}
        if github_token is not None:
            fields["github_token"] = github_token
        if linear_api_key is not None:
            fields["linear_api_key"] = linear_api_key
        if linear_team_id is not None:
            fields["linear_team_id"] = linear_team_id
        if notify_email is not None:
            fields["notify_email"] = notify_email
        if not fields:
            user = self.get_by_id(user_id)
            if not user:
                raise ValueError("User not found")
            return user
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._connect() as conn:
            conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))
        return self.get_by_id(user_id)  # type: ignore[return-value]

    def get_by_id(self, user_id: str) -> Optional[AccountUser]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_user(row) if row else None

    def deduct_credits(self, user_id: str, units: int, service: str, detail: str = "") -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return 0
            new_balance = max(0, int(row["credits"]) - units)
            conn.execute("UPDATE users SET credits = ? WHERE id = ?", (new_balance, user_id))
            conn.execute(
                "INSERT INTO usage (user_id, service, units, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, service, units, detail[:500], _now()),
            )
        return new_balance

    def usage_summary(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT service, units, detail, created_at FROM usage
                WHERE user_id = ? ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_user(row: sqlite3.Row) -> AccountUser:
        return AccountUser(
            id=row["id"],
            email=row["email"],
            api_key=row["api_key"],
            credits=int(row["credits"]),
            github_token=row["github_token"] or "",
            linear_api_key=row["linear_api_key"] or "",
            linear_team_id=row["linear_team_id"] or "",
            notify_email=row["notify_email"] or "",
        )

    def export_profile(self, user: AccountUser) -> Dict[str, Any]:
        return {
            "email": user.email,
            "api_key": user.api_key,
            "credits": user.credits,
            "github_connected": bool(user.github_token),
            "linear_connected": bool(user.linear_api_key),
            "linear_team_id": user.linear_team_id,
            "notify_email": user.notify_email,
            "usage": self.usage_summary(user.id),
        }

    def ensure_local_account(self) -> AccountUser:
        """Bootstrap a default local account for offline / first-run use."""
        existing = self.get_by_email("local@creation.dev")
        if existing:
            return existing
        return self.register("local@creation.dev", secrets.token_urlsafe(16))
