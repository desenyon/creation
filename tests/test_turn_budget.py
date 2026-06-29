"""Turn budget resolution tests."""

from creation.config import UserSecrets
from creation.orchestrator import resolve_max_turns
from creation.store import Project


def test_resolve_max_turns_run_override():
    secrets = UserSecrets(max_turn_budget=200)
    project = Project(id="p1", name="x", max_turn_budget=50)
    assert resolve_max_turns(secrets, project, 12) == 12


def test_resolve_max_turns_project_override():
    secrets = UserSecrets(max_turn_budget=200)
    project = Project(id="p1", name="x", max_turn_budget=30)
    assert resolve_max_turns(secrets, project, None) == 30


def test_resolve_max_turns_global_default():
    secrets = UserSecrets(max_turn_budget=75)
    project = Project(id="p1", name="x", max_turn_budget=None)
    assert resolve_max_turns(secrets, project, None) == 75
