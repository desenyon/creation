"""Work-graph event bus for live SSE streaming to the board.

Unlike the per-run bus in ``creation.events``, this is a single broadcast channel: any
mutation anywhere in the work graph (a ticket created, a status change, a run
completing, a trigger firing) is pushed to every connected board.

Thread-safe by design: the dispatcher/worker run in background threads while SSE
consumers live in the event loop, so we publish via ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Tuple

# (loop, queue) per connected client.
_subscribers: List[Tuple[asyncio.AbstractEventLoop, "asyncio.Queue[str]"]] = []


def _safe_put(q: "asyncio.Queue[str]", payload: str) -> None:
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        pass  # slow client; drop — the board re-fetches full state on any event


def publish(event: Dict[str, Any]) -> None:
    """Broadcast an event to all connected boards. Safe to call from any thread."""
    if not _subscribers:
        return
    payload = json.dumps(event, default=str)
    for loop, q in list(_subscribers):
        try:
            loop.call_soon_threadsafe(_safe_put, q, payload)
        except RuntimeError:
            # loop closed / shutting down — drop this subscriber silently
            pass


def emit(kind: str, **fields: Any) -> None:
    """Convenience wrapper: publish a typed event."""
    publish({"type": kind, **fields})


async def subscribe() -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    q: "asyncio.Queue[str]" = asyncio.Queue(maxsize=512)
    _subscribers.append((loop, q))
    try:
        yield json.dumps({"type": "hello"})
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield msg
            except asyncio.TimeoutError:
                yield json.dumps({"type": "ping"})  # heartbeat keeps the stream open
    finally:
        _subscribers[:] = [(lp, qq) for (lp, qq) in _subscribers if qq is not q]


def subscriber_count() -> int:
    return len(_subscribers)
