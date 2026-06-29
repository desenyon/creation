"""Inbound human-in-the-loop poller — Gmail replies + Linear comments."""

from creation.config import UserSecrets
from creation.inbound import InboundPoller
from creation.integrations.composio_ops import OpsResult


class FakeInboundOps:
    demo = False

    def __init__(self, gmail=None, linear=None):
        self._gmail = gmail or {}
        self._linear = linear or {}

    def run_action(self, slug, arguments):
        if slug == "GMAIL_FETCH_EMAILS":
            return OpsResult(True, slug, self._gmail)
        if slug in ("LINEAR_LIST_LINEAR_COMMENTS", "LINEAR_GET_LINEAR_COMMENTS"):
            return OpsResult(True, slug, self._linear)
        return OpsResult(False, slug)


def _collect():
    received = []
    return received, (lambda text, source: received.append((source, text)))


def test_linear_comment_becomes_steering():
    ops = FakeInboundOps(
        linear={"comments": [{"id": "c1", "body": "Please use dark mode"}]}
    )
    received, on_msg = _collect()
    poller = InboundPoller(ops, "run1", on_message=on_msg, linear_issue_id="issue1")
    n = poller.poll_once()
    assert n == 1
    assert received[0] == ("linear:c1", "Please use dark mode")


def test_gmail_reply_becomes_steering_and_skips_sent():
    ops = FakeInboundOps(
        gmail={
            "messages": [
                {"id": "m1", "snippet": "Add Stripe billing", "labelIds": ["INBOX"]},
                {"id": "m2", "snippet": "our own email", "labelIds": ["SENT"]},
            ]
        }
    )
    received, on_msg = _collect()
    poller = InboundPoller(ops, "run1", on_message=on_msg, gmail_subject="MyApp")
    poller.poll_once()
    sources = {s for s, _ in received}
    assert "gmail:m1" in sources
    assert "gmail:m2" not in sources  # SENT (our own) skipped


def test_dedupes_across_polls():
    ops = FakeInboundOps(linear={"comments": [{"id": "c1", "body": "Same comment"}]})
    received, on_msg = _collect()
    poller = InboundPoller(ops, "run1", on_message=on_msg, linear_issue_id="issue1")
    assert poller.poll_once() == 1
    assert poller.poll_once() == 0  # already seen
    assert len(received) == 1


def test_disabled_in_demo():
    poller = InboundPoller(
        type("Demo", (), {"demo": True})(),
        "run1",
        on_message=lambda *a: None,
        linear_issue_id="issue1",
    )
    assert poller.enabled is False
    poller.start()  # no-op
    poller.stop()
