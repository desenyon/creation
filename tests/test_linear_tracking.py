from types import SimpleNamespace

from creation.config import UserSecrets
from creation.integrations.composio_ops import ComposioOps, OpsResult
from creation.integrations.project_tracker import ProjectTracker


class FakeTools:
    def __init__(self, payload):
        self.payload = payload

    def execute(self, *args, **kwargs):
        return SimpleNamespace(successful=True, data=self.payload)


class FakeComposio:
    def __init__(self, payload):
        self.tools = FakeTools(payload)


def test_nested_linear_project_response_is_normalized(monkeypatch):
    payload = {
        "data": {
            "projectCreate": {
                "project": {
                    "id": "project-real-123",
                    "name": "Real project",
                    "url": "https://linear.app/acme/project/real-project-abc123",
                }
            }
        }
    }
    ops = ComposioOps(UserSecrets(linear_api_key="lin_test"))
    monkeypatch.setattr(ops, "_linear_query", lambda q, v=None: payload)

    result = ops.run_action("LINEAR_CREATE_LINEAR_PROJECT", {"name": "Real project", "team_id": "t1"})

    assert result.success is True
    assert result.data["id"] == "project-real-123"
    assert result.data["url"] == "https://linear.app/acme/project/real-project-abc123"


class RecordingOps:
    demo = False

    def __init__(self):
        self.calls = []

    def run_action(self, slug, arguments):
        self.calls.append((slug, arguments))
        if slug == "LINEAR_CREATE_LINEAR_PROJECT":
            return OpsResult(
                True,
                slug,
                {
                    "id": "project-real-123",
                    "url": "https://linear.app/acme/project/real-project-abc123",
                },
            )
        if slug == "LINEAR_GET_LINEAR_PROJECT":
            return OpsResult(
                True,
                slug,
                {"project": {"id": "project-real-123", "url": "https://linear.app/acme/project/real-project-abc123"}},
            )
        if slug == "LINEAR_CREATE_LINEAR_ISSUE":
            return OpsResult(True, slug, {"id": "issue-1", "identifier": "ENG-1"})
        return OpsResult(True, slug, {})


def test_tracker_keeps_real_url_and_updates_same_linear_project():
    ops = RecordingOps()
    tracker = ProjectTracker(ops, UserSecrets())

    tracker._create_linear_project("Real project", "Build it", "team-1")
    issue = tracker._create_issue(
        "team-1",
        "Implement feature",
        "Details",
        project_id=tracker.state.linear_project_id,
    )
    tracker._post_project_update(1, "Turn completed", health="onTrack")

    assert tracker.state.linear_project_id == "project-real-123"
    assert tracker.state.linear_project_url == "https://linear.app/acme/project/real-project-abc123"
    assert issue is not None and issue.identifier == "ENG-1"
    issue_call = next(args for slug, args in ops.calls if slug == "LINEAR_CREATE_LINEAR_ISSUE")
    update_call = next(args for slug, args in ops.calls if slug == "LINEAR_CREATE_PROJECT_UPDATE")
    assert issue_call["project_id"] == "project-real-123"
    assert update_call["project_id"] == "project-real-123"


def test_tracker_reuses_user_supplied_linear_project():
    ops = RecordingOps()
    secrets = UserSecrets(
        linear_project_mode="existing",
        linear_project_id="project-existing-123",
        linear_project_url="https://linear.app/acme/project/existing-123",
        linear_project_name="Existing Project",
    )
    tracker = ProjectTracker(ops, secrets)

    tracker._ensure_linear_project("New project", "Build it", "team-1")
    issue = tracker._create_issue(
        "team-1",
        "Implement feature",
        "Details",
        project_id=tracker.state.linear_project_id,
    )

    assert tracker.state.linear_project_id == "project-existing-123"
    assert tracker.state.linear_project_url == "https://linear.app/acme/project/existing-123"
    assert tracker.state.linear_project_name == "Existing Project"
    assert issue is not None
    assert not any(slug == "LINEAR_CREATE_LINEAR_PROJECT" for slug, _ in ops.calls)
    issue_call = next(args for slug, args in ops.calls if slug == "LINEAR_CREATE_LINEAR_ISSUE")
    assert issue_call["project_id"] == "project-existing-123"


def test_tracker_creates_project_when_existing_project_not_selected():
    ops = RecordingOps()
    secrets = UserSecrets(
        linear_project_mode="create",
        linear_project_id="project-existing-123",
        linear_project_url="https://linear.app/acme/project/existing-123",
        linear_project_name="Existing Project",
    )
    tracker = ProjectTracker(ops, secrets)

    tracker._ensure_linear_project("New project", "Build it", "team-1")

    assert tracker.state.linear_project_id == "project-real-123"
    assert tracker.state.linear_project_url == "https://linear.app/acme/project/real-project-abc123"
    assert any(slug == "LINEAR_CREATE_LINEAR_PROJECT" for slug, _ in ops.calls)
