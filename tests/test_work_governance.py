"""Phase 3/4: audit log, playbook memory, and the approval gate."""

from pathlib import Path
from typing import Callable, Optional

import pytest

from creation.config import UserSecrets
from creation.store import init_db
from creation.work import audit, playbook
from creation.work import store as wstore
from creation.work.models import AgentDef, EvidencePack, Ticket
from creation.work.prompt import build_ticket_prompt
from creation.work.review import approve_ticket, reject_ticket
from creation.work.worker import run_ticket


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    audit.init_audit_db()
    playbook.init_playbook_db()
    return tmp_path


class FakeRunner:
    def __init__(self, *, success: bool = True, risks: str = "none"):
        self.success = success
        self.risks = risks

    def run(self, prompt: str, workdir: Path, on_line: Optional[Callable[[str], None]] = None):
        self.last_prompt = prompt
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "f.py").write_text("x = 1\n")

        outer = self

        class R:
            output = (
                "EVIDENCE_BEGIN\nPLAN: did it\nCHANGED: f.py\n"
                f"RISKS: {outer.risks}\nCONFIDENCE: 0.8\nEVIDENCE_END"
            )
            success = outer.success
            command = "fake"

        return R()


# ── audit ──────────────────────────────────────────────────────────────


def test_audit_record_and_query(isolated_store):
    audit.record("ticket.assigned", "ticket", "tkt_1", detail={"agent": "a"})
    audit.record("run.completed", "ticket", "tkt_1")
    audit.record("run.completed", "ticket", "tkt_2")
    assert len(audit.list_events(entity_id="tkt_1")) == 2
    assert len(audit.list_events(action="run.completed")) == 2
    # newest first
    assert audit.list_events()[0].entity_id == "tkt_2"


def test_worker_records_run_audit_event(isolated_store, tmp_path):
    a = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=False))
    t = wstore.create_ticket(Ticket(title="x", repo=str(tmp_path / "r")))
    run_ticket(t, a, tmp_path / "r", UserSecrets(), runner=FakeRunner())
    events = audit.list_events(entity_id=t.id, action="run.completed")
    assert len(events) == 1
    assert events[0].actor_type == "agent"


# ── playbook ─────────────────────────────────────────────────────────────


def test_record_from_evidence_captures_risks(isolated_store):
    t = wstore.create_ticket(Ticket(title="touch auth", repo="acme/api"))
    ev = EvidencePack(ticket_id=t.id, run_id="r1", risks=["modifies auth tokens"])
    lesson = playbook.record_from_evidence(ev, t, "security", "in_review")
    assert lesson is not None
    assert "auth tokens" in lesson.lesson


def test_record_from_evidence_none_when_no_signal(isolated_store):
    t = wstore.create_ticket(Ticket(title="trivial"))
    ev = EvidencePack(ticket_id=t.id, run_id="r1")  # no risks, not blocked
    assert playbook.record_from_evidence(ev, t, "code", "done") is None


def test_blocked_run_records_lesson(isolated_store):
    t = wstore.create_ticket(Ticket(title="hard", repo="acme/api"))
    ev = EvidencePack(ticket_id=t.id, run_id="r1", reasoning_summary="line1\nfailed to build")
    lesson = playbook.record_from_evidence(ev, t, "code", "blocked")
    assert lesson is not None
    assert lesson.outcome == "blocked"


def test_relevant_lessons_prioritizes_repo_and_blocked(isolated_store):
    t = wstore.create_ticket(Ticket(title="x", repo="acme/api"))
    playbook.add_lesson(playbook.Lesson(kind="code", repo="acme/api", lesson="repo lesson", outcome="done"))
    playbook.add_lesson(playbook.Lesson(kind="code", repo="", lesson="kind lesson", outcome="blocked"))
    lessons = playbook.relevant_lessons(t, "code")
    assert lessons[0].lesson == "repo lesson"  # same-repo wins
    block = playbook.lessons_block(lessons)
    assert "Playbook" in block


def test_lessons_injected_into_prompt(isolated_store, tmp_path):
    # seed a lesson, then a run on the same repo should include it in the prompt
    repo = str(tmp_path / "r")
    playbook.add_lesson(playbook.Lesson(kind="code", repo=repo, lesson="watch the migrations table", outcome="blocked"))
    a = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=False))
    t = wstore.create_ticket(Ticket(title="x", repo=repo))
    runner = FakeRunner()
    run_ticket(t, a, tmp_path / "r", UserSecrets(), runner=runner)
    assert "watch the migrations table" in runner.last_prompt


def test_build_prompt_lessons_section_optional(isolated_store):
    a = AgentDef(name="A", kind="code")
    t = Ticket(title="x")
    assert "Playbook" not in build_ticket_prompt(t, a)
    assert "Playbook" in build_ticket_prompt(t, a, lessons="## Playbook\n- be careful")


# ── approval gate ──────────────────────────────────────────────────────────


def test_approve_in_review_ticket(isolated_store):
    t = wstore.create_ticket(Ticket(title="x", status="in_review"))
    res = approve_ticket(t.id)
    assert res.status == "done"
    assert wstore.get_ticket(t.id).status == "done"
    assert len(audit.list_events(entity_id=t.id, action="ticket.approved")) == 1


def test_approve_rejects_non_review_ticket(isolated_store):
    t = wstore.create_ticket(Ticket(title="x", status="todo"))
    with pytest.raises(ValueError):
        approve_ticket(t.id)


def test_reject_requeues_with_feedback(isolated_store):
    t = wstore.create_ticket(Ticket(title="x", status="in_review", description="orig"))
    res = reject_ticket(t.id, "use the new API", requeue=True)
    assert res.status == "todo"
    updated = wstore.get_ticket(t.id)
    assert "Reviewer feedback" in updated.description
    assert "use the new API" in updated.description
    assert len(audit.list_events(entity_id=t.id, action="ticket.rejected")) == 1


def test_reject_can_block(isolated_store):
    t = wstore.create_ticket(Ticket(title="x", status="in_review"))
    res = reject_ticket(t.id, "not safe", requeue=False)
    assert res.status == "blocked"


def test_full_loop_review_then_approve(isolated_store, tmp_path):
    # high-risk run stops at in_review, reviewer approves → done
    a = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=True))
    t = wstore.create_ticket(Ticket(title="risky", repo=str(tmp_path / "r")))
    res = run_ticket(t, a, tmp_path / "r", UserSecrets(), runner=FakeRunner(risks="touches billing"))
    assert res.status == "in_review"
    # a lesson was captured from the risk
    assert any("billing" in ls.lesson for ls in playbook.list_lessons())
    approve_ticket(t.id)
    assert wstore.get_ticket(t.id).status == "done"
