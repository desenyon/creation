"""Portfolio queue + scheduled overnight builds."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from creation.config import load_secrets
from creation.orchestrator import run_factory
from creation.store import count_running_runs, create_run, dequeue_next_queued, list_queue, list_running_runs, peek_queue

logger = logging.getLogger(__name__)

_scheduler_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_next_queued() -> Optional[str]:
    """Start the next queued project if under concurrent run cap. Returns run_id."""
    secrets = load_secrets()
    if count_running_runs() >= max(secrets.max_concurrent_runs, 1):
        return None
    item = dequeue_next_queued()
    if not item:
        return None
    run = create_run(item["project_id"])
    try:
        run_factory(run, secrets, item.get("seed") or "")
        return run.id
    except Exception:
        logger.exception("scheduled run failed project=%s", item["project_id"])
        return run.id


def tick() -> None:
    secrets = load_secrets()
    if not secrets.schedule_enabled:
        return
    if count_running_runs() >= max(secrets.max_concurrent_runs, 1):
        return
    # Simple interval: schedule_interval_hours (0 = disabled via schedule_enabled)
    last_path = secrets.schedule_state_file()
    try:
        import json
        from pathlib import Path

        state = json.loads(last_path.read_text()) if last_path.exists() else {}
        last = state.get("last_run_at")
        hours = max(secrets.schedule_interval_hours, 1)
        if last:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if elapsed < hours:
                return
        rid = run_next_queued()
        if rid:
            last_path.parent.mkdir(parents=True, exist_ok=True)
            last_path.write_text(json.dumps({"last_run_at": _now(), "last_run_id": rid}))
    except Exception:
        logger.exception("scheduler tick failed")


def _loop() -> None:
    while not _stop.is_set():
        try:
            tick()
        except Exception:
            logger.exception("scheduler loop error")
        _stop.wait(60)


def start_scheduler() -> None:
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _stop.clear()
    _scheduler_thread = threading.Thread(target=_loop, name="creation-scheduler", daemon=True)
    _scheduler_thread.start()
    logger.info("Creation scheduler started")


def stop_scheduler() -> None:
    _stop.set()


def queue_status() -> dict:
    sec = load_secrets()
    running = list_running_runs()
    return {
        "enabled": sec.schedule_enabled,
        "interval_hours": sec.schedule_interval_hours,
        "max_concurrent_runs": sec.max_concurrent_runs,
        "running_count": len(running),
        "running_project": running[0]["project_id"] if running else None,
        "running_runs": running,
        "queue": list_queue(),
    }
