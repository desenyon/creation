"""Agent usage tracking and auto-failover when quotas are high."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from creation.agents.registry import AGENT_BY_ID, normalize_agent
from creation.agents.runner import available_agents
from creation.config import CONFIG_DIR, UserSecrets, load_secrets

USAGE_FILE = CONFIG_DIR / "agent_usage.json"
LIMITS_FILE = CONFIG_DIR / "agent_turn_limits.json"

# Estimated monthly agent turns before quota pressure (override via agent_turn_limits.json).
DEFAULT_TURN_LIMITS: Dict[str, int] = {
    "cursor": 500,
    "codex": 800,
    "claude": 800,
    "copilot": 600,
    "gemini": 600,
    "opencode": 400,
}

RATE_LIMIT_RE = re.compile(
    r"(rate.?limit|usage.?limit|quota.?exceeded|too many requests|limit reached|"
    r"exceeded your|usage cap|premium requests|fast requests)",
    re.I,
)


@dataclass
class AgentUsageSnapshot:
    agent: str
    pct: float
    used: int
    limit: int
    source: str
    status: str
    available: bool
    fallback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load_limits() -> Dict[str, int]:
    limits = dict(DEFAULT_TURN_LIMITS)
    if LIMITS_FILE.exists():
        try:
            overrides = json.loads(LIMITS_FILE.read_text())
            if isinstance(overrides, dict):
                for k, v in overrides.items():
                    if isinstance(v, int) and v > 0:
                        limits[str(k).lower()] = v
        except (json.JSONDecodeError, OSError):
            pass
    return limits


def _load_state() -> Dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not USAGE_FILE.exists():
        return {"months": {}, "exhausted": {}}
    try:
        data = json.loads(USAGE_FILE.read_text())
        if isinstance(data, dict):
            data.setdefault("months", {})
            data.setdefault("exhausted", {})
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"months": {}, "exhausted": {}}


def _save_state(state: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(state, indent=2))


def _turn_limit(agent_id: str) -> int:
    return _load_limits().get(agent_id, 200)


def _month_turns(state: Dict[str, Any], agent_id: str) -> int:
    month = _month_key()
    return int(state.get("months", {}).get(month, {}).get(agent_id, 0))


def record_turn(agent: str) -> None:
    agent_id = normalize_agent(agent)
    state = _load_state()
    month = _month_key()
    months = state.setdefault("months", {})
    bucket = months.setdefault(month, {})
    bucket[agent_id] = int(bucket.get(agent_id, 0)) + 1
    _save_state(state)


def mark_exhausted(agent: str, reason: str = "rate_limit") -> None:
    agent_id = normalize_agent(agent)
    state = _load_state()
    exhausted = state.setdefault("exhausted", {})
    exhausted[agent_id] = {"at": datetime.now(timezone.utc).isoformat(), "reason": reason}
    _save_state(state)


def clear_exhausted(agent: str) -> None:
    agent_id = normalize_agent(agent)
    state = _load_state()
    state.get("exhausted", {}).pop(agent_id, None)
    _save_state(state)


def detect_rate_limit(output: str) -> bool:
    return bool(output and RATE_LIMIT_RE.search(output))


def _status_for_pct(pct: float, warn: float, critical: float) -> str:
    if pct >= critical:
        return "critical"
    if pct >= warn:
        return "warn"
    return "ok"


def _probe_codexbar(agent_id: str) -> Optional[float]:
    """Best-effort cost-based usage for Codex / Claude via CodexBar."""
    if agent_id not in ("codex", "claude") or not shutil.which("codexbar"):
        return None
    try:
        proc = subprocess.run(
            ["codexbar", "cost", "--format", "json", "--provider", agent_id],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode != 0:
            return None
        rows = json.loads(proc.stdout or "[]")
        if not isinstance(rows, list) or not rows:
            return None
        # Use most recent day with model breakdown — scale vs soft $20 cap as heuristic.
        latest = rows[-1] if rows else {}
        total = float(latest.get("totalCost") or latest.get("cost") or 0)
        cap = 20.0
        return min(100.0, round((total / cap) * 100, 1)) if cap else None
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _probe_cursor_cli() -> bool:
    if not shutil.which("cursor-agent"):
        return False
    try:
        proc = subprocess.run(
            ["cursor-agent", "status", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout or "{}")
        return bool(data.get("isAuthenticated") or data.get("status") == "authenticated")
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError):
        return False


def probe_agent(agent_id: str, secrets: Optional[UserSecrets] = None) -> AgentUsageSnapshot:
    secrets = secrets or load_secrets()
    agent_id = normalize_agent(agent_id)
    avail_map = {a["id"]: a for a in available_agents()}
    available = bool(avail_map.get(agent_id, {}).get("available"))
    limit = _turn_limit(agent_id)
    state = _load_state()
    used = _month_turns(state, agent_id)
    source = "turns"
    pct = min(100.0, round((used / limit) * 100, 1)) if limit else 0.0

    if agent_id in state.get("exhausted", {}):
        pct = 100.0
        source = state["exhausted"][agent_id].get("reason", "exhausted")

    codexbar_pct = _probe_codexbar(agent_id)
    if codexbar_pct is not None:
        pct = max(pct, codexbar_pct)
        source = "codexbar+turns" if used else "codexbar"

    if agent_id == "cursor" and not _probe_cursor_cli():
        available = False

    status = _status_for_pct(pct, secrets.agent_usage_warn_pct, secrets.agent_usage_critical_pct)
    fallback = secrets.agent_fallback if secrets.agent_failover_enabled else None
    return AgentUsageSnapshot(
        agent=agent_id,
        pct=pct,
        used=used,
        limit=limit,
        source=source,
        status=status,
        available=available,
        fallback=fallback,
    )


def summarize_all(secrets: Optional[UserSecrets] = None) -> List[AgentUsageSnapshot]:
    secrets = secrets or load_secrets()
    installed = [a["id"] for a in available_agents() if a.get("available")]
    primary = normalize_agent(secrets.default_agent)
    agents = list(dict.fromkeys([primary, secrets.agent_fallback, *installed]))
    return [probe_agent(a, secrets) for a in agents if a in AGENT_BY_ID]


def _pick_fallback(primary: str, secrets: UserSecrets) -> Optional[str]:
    fallback = normalize_agent(secrets.agent_fallback or "codex")
    if fallback == primary:
        return None
    snap = probe_agent(fallback, secrets)
    if not snap.available:
        return None
    if snap.pct >= secrets.agent_usage_failover_pct:
        return None
    return fallback


def resolve_agent_for_turn(
    primary: str,
    secrets: UserSecrets,
) -> Tuple[str, Optional[str], AgentUsageSnapshot]:
    """Return agent to use, optional failover source, and usage snapshot."""
    primary = normalize_agent(primary)
    snap = probe_agent(primary, secrets)

    if not secrets.agent_failover_enabled:
        return primary, None, snap

    if snap.pct < secrets.agent_usage_failover_pct and primary not in _load_state().get("exhausted", {}):
        return primary, None, snap

    fallback = _pick_fallback(primary, secrets)
    if fallback:
        fb_snap = probe_agent(fallback, secrets)
        return fallback, primary, fb_snap

    return primary, None, snap


def should_skip_parallel_secondary(secondary: str, secrets: UserSecrets) -> bool:
    snap = probe_agent(normalize_agent(secondary), secrets)
    return snap.pct >= secrets.agent_usage_failover_pct or not snap.available
