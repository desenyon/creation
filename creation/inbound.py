"""Inbound human-in-the-loop — poll Gmail replies + Linear comments as steering.

During a live run, a background poller watches for new Gmail replies to the
kickoff thread and new Linear comments on the project's epic. Each new item is
fed back into the run via ``manual_takeover.add_message`` so it enters the
normal steering path (``drain_for_turn``) on the next turn. Items are de-duped
by their source id so the same reply is never applied twice.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from creation.integrations.composio_ops import ComposioOps

logger = logging.getLogger(__name__)

OnMessage = Callable[[str, str], None]  # (text, source) -> None


def _walk(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


class InboundPoller:
    """Background poller turning email replies + Linear comments into steering."""

    def __init__(
        self,
        ops: ComposioOps,
        run_id: str,
        *,
        on_message: OnMessage,
        linear_issue_id: str = "",
        gmail_subject: str = "",
        interval_secs: int = 30,
        enabled: bool = True,
    ) -> None:
        self.ops = ops
        self.run_id = run_id
        self.on_message = on_message
        self.linear_issue_id = linear_issue_id
        self.gmail_subject = gmail_subject
        self.interval = max(int(interval_secs), 10)
        self.enabled = enabled and not ops.demo
        self._seen: set[str] = set()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ──
    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name=f"creation-inbound-{self.run_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> "InboundPoller":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # ── polling ──
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # pragma: no cover - defensive, never kill the run
                logger.exception("inbound poll failed")
            self._stop.wait(self.interval)

    def poll_once(self) -> int:
        """Fetch new items and dispatch them; returns count of new messages."""
        count = 0
        for text, src_id in list(self._gmail_replies()) + list(self._linear_comments()):
            if not text.strip() or src_id in self._seen:
                continue
            self._seen.add(src_id)
            try:
                self.on_message(text.strip()[:2000], src_id)
                count += 1
            except Exception:  # pragma: no cover - defensive
                logger.exception("inbound dispatch failed")
        return count

    def _gmail_replies(self) -> List[Tuple[str, str]]:
        if not self.gmail_subject:
            return []
        query = "subject:Creation newer_than:1d"
        r = self.ops.run_action("GMAIL_FETCH_EMAILS", {"query": query, "max_results": 10})
        if not r.success:
            return []
        out: List[Tuple[str, str]] = []
        for node in _walk(r.data):
            mid = node.get("messageId") or node.get("id")
            if not mid or not isinstance(mid, str):
                continue
            labels = node.get("labelIds") or node.get("labels") or []
            if isinstance(labels, list) and any(str(l).upper() == "SENT" for l in labels):
                continue  # our own outgoing mail, not a reply
            text = (
                node.get("messageText")
                or node.get("snippet")
                or node.get("preview")
                or node.get("body")
                or node.get("text")
            )
            if isinstance(text, str) and text.strip():
                out.append((text, f"gmail:{mid}"))
        return out

    def _linear_comments(self) -> List[Tuple[str, str]]:
        if not self.linear_issue_id:
            return []
        result: List[Tuple[str, str]] = []
        for slug in ("LINEAR_LIST_LINEAR_COMMENTS", "LINEAR_GET_LINEAR_COMMENTS"):
            r = self.ops.run_action(slug, {"issue_id": self.linear_issue_id})
            if not r.success:
                continue
            for node in _walk(r.data):
                cid = node.get("id")
                body = node.get("body") or node.get("bodyData") or node.get("comment")
                if cid and isinstance(cid, str) and isinstance(body, str) and body.strip():
                    result.append((body, f"linear:{cid}"))
            if result:
                break
        return result
