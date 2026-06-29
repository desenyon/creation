"""Existing GitHub repo detection + reuse (no duplicate repos)."""

from creation.config import UserSecrets
from creation.integrations.composio_ops import OpsResult
from creation.integrations.project_tracker import ProjectTracker


class FakeRepoOps:
    demo = False

    def __init__(self, existing=("octocat", "neurobeest")):
        self.existing = existing
        self.created = []

    def resolve_github_owner(self):
        return "octocat"

    def get_github_repo(self, owner, repo):
        if self.existing and (owner, repo) == self.existing:
            full = f"{owner}/{repo}"
            return OpsResult(True, f"{full} exists", {
                "full_name": full,
                "html_url": f"https://github.com/{full}",
            })
        return OpsResult(False, "repo not found")

    def create_github_repo(self, name, description="", private=True):
        self.created.append(name)
        return OpsResult(True, "created", {
            "full_name": f"octocat/{name}",
            "html_url": f"https://github.com/octocat/{name}",
        })


def test_reuses_existing_repo_instead_of_creating():
    ops = FakeRepoOps(existing=("octocat", "neurobeest"))
    tracker = ProjectTracker(ops, UserSecrets())

    tracker._ensure_github_repo("Build neurobeest", "proj1234", repo_slug="neurobeest")

    assert tracker.reused_repo is True
    assert tracker.state.github_owner == "octocat"
    assert tracker.state.github_repo == "neurobeest"
    assert tracker.state.github_url == "https://github.com/octocat/neurobeest"
    assert ops.created == []  # never created a duplicate


def test_creates_repo_when_none_exists():
    ops = FakeRepoOps(existing=None)
    tracker = ProjectTracker(ops, UserSecrets())

    tracker._ensure_github_repo("Brand new thing", "proj9999", repo_slug="brand-new-thing")

    assert tracker.reused_repo is False
    assert ops.created == ["brand-new-thing"]
    assert tracker.state.github_url == "https://github.com/octocat/brand-new-thing"


def test_create_collision_falls_back_to_reuse():
    class CollisionOps(FakeRepoOps):
        def __init__(self):
            super().__init__(existing=("octocat", "neurobeest"))
            self._first = True

        def get_github_repo(self, owner, repo):
            # First lookup (pre-create) says missing; post-failure lookup finds it.
            if self._first:
                self._first = False
                return OpsResult(False, "not found")
            return super().get_github_repo(owner, repo)

        def create_github_repo(self, name, description="", private=True):
            self.created.append(name)
            return OpsResult(False, "name already exists")

    ops = CollisionOps()
    tracker = ProjectTracker(ops, UserSecrets())
    tracker._ensure_github_repo("Neurobeest", "p", repo_slug="neurobeest")

    assert tracker.reused_repo is True
    assert tracker.state.github_repo == "neurobeest"


def test_pinned_owner_and_repo_are_trusted():
    ops = FakeRepoOps(existing=None)
    secrets = UserSecrets(github_owner="me", github_repo="myrepo")
    tracker = ProjectTracker(ops, secrets)
    tracker._ensure_github_repo("Anything", "p", repo_slug="anything")

    assert tracker.reused_repo is True
    assert tracker.state.github_url == "https://github.com/me/myrepo"
    assert ops.created == []
