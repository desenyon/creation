"""Always-on board loop — the server-side heartbeat that runs assigned tickets.

The legacy ``creation.schedule`` scheduler only drives the portfolio queue (full
project builds). This loop is its work-graph counterpart: while
``work_graph_enabled`` and ``work_auto_dispatch`` are on, it periodically calls
the dispatcher so any agent-assigned ``todo`` ticket gets picked up and worked
without anyone clicking "Dispatch". One pass runs to completion before the next
starts, so agents never double-run on the same repo.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from creation.config import load_secrets

logger = logging.getLogger(__name__)

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_running_pass = threading.Event()  # true while a dispatch pass is in flight


def _emit(line: str) -> None:
    """Surface dispatcher progress on the board's SSE stream (best-effort)."""
    try:
        from creation.work.events import emit

        emit("dispatch_log", message=line)
    except Exception:
        pass


def _tick() -> None:
    secrets = load_secrets()
    if not (secrets.work_graph_enabled and secrets.work_auto_dispatch):
        return
    if _running_pass.is_set():
        return  # previous pass still working — don't overlap
    _running_pass.set()
    try:
        from creation.work.dispatcher import dispatch_once

        results = dispatch_once(secrets=secrets, on_line=_emit)
        if results:
            logger.info("work auto-dispatch ran %d ticket(s)", len(results))
    except Exception:
        logger.exception("work auto-dispatch pass failed")
    finally:
        _running_pass.clear()


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("work dispatch loop error")
        interval = 20
        try:
            interval = max(5, int(load_secrets().work_dispatch_interval_secs))
        except Exception:
            pass
        _stop.wait(interval)


def start_work_dispatcher() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="creation-work-dispatch", daemon=True)
    _thread.start()
    logger.info("Creation work dispatcher started")


def stop_work_dispatcher() -> None:
    _stop.set()


def is_pass_running() -> bool:
    return _running_pass.is_set()
