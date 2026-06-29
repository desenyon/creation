"""Tests for auto-branch safety helpers in git_sync."""

import shutil
import subprocess
from pathlib import Path

import pytest

from creation.integrations import git_sync

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _init_repo(path: Path) -> None:
    """Init a git repo at path with one commit."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    # Ensure a deterministic base branch name across git versions.
    subprocess.run(["git", "checkout", "-b", "main"], cwd=str(path), capture_output=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(path), check=True, capture_output=True
    )


# ── slug sanitization (no git needed) ──


def test_sanitize_slug_basic():
    assert git_sync._sanitize_slug("My Cool App") == "my-cool-app"


def test_sanitize_slug_underscores_and_repeats():
    assert git_sync._sanitize_slug("Foo__Bar  Baz") == "foo-bar-baz"


def test_sanitize_slug_strips_punctuation_and_edges():
    assert git_sync._sanitize_slug("--Hello, World!--") == "hello-world"


def test_sanitize_slug_fallback_for_empty():
    assert git_sync._sanitize_slug("") == "build"
    assert git_sync._sanitize_slug("!!!") == "build"


# ── repo detection (no git needed for the negative case) ──


def test_is_git_repo_false_on_empty_dir(tmp_path):
    assert git_sync.is_git_repo(tmp_path) is False


def test_has_commits_false_on_empty_dir(tmp_path):
    assert git_sync.has_commits(tmp_path) is False


def test_ensure_working_branch_none_for_non_git_dir(tmp_path):
    assert git_sync.ensure_working_branch(tmp_path, "anything") is None


# ── real git interactions ──


@requires_git
def test_is_git_repo_and_has_commits_after_commit(tmp_path):
    assert git_sync.is_git_repo(tmp_path) is False
    assert git_sync.has_commits(tmp_path) is False
    _init_repo(tmp_path)
    assert git_sync.is_git_repo(tmp_path) is True
    assert git_sync.has_commits(tmp_path) is True


@requires_git
def test_current_branch_reports_checked_out_branch(tmp_path):
    _init_repo(tmp_path)
    assert git_sync.current_branch(tmp_path) == "main"


@requires_git
def test_ensure_working_branch_creates_and_switches(tmp_path):
    _init_repo(tmp_path)
    branch = git_sync.ensure_working_branch(tmp_path, "My Cool App")
    assert branch == "creation/my-cool-app"
    assert git_sync.current_branch(tmp_path) == "creation/my-cool-app"


@requires_git
def test_ensure_working_branch_idempotent(tmp_path):
    _init_repo(tmp_path)
    first = git_sync.ensure_working_branch(tmp_path, "My Cool App")
    # Re-run while already on a creation/ branch → returns it unchanged.
    second = git_sync.ensure_working_branch(tmp_path, "My Cool App")
    assert first == second == "creation/my-cool-app"
    assert git_sync.current_branch(tmp_path) == "creation/my-cool-app"


@requires_git
def test_ensure_working_branch_checks_out_existing_branch(tmp_path):
    _init_repo(tmp_path)
    # Pre-create the creation branch, then switch back to main.
    subprocess.run(
        ["git", "checkout", "-b", "creation/my-cool-app"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "main"], cwd=str(tmp_path), check=True, capture_output=True
    )
    assert git_sync.current_branch(tmp_path) == "main"

    branch = git_sync.ensure_working_branch(tmp_path, "My Cool App")
    assert branch == "creation/my-cool-app"
    assert git_sync.current_branch(tmp_path) == "creation/my-cool-app"


@requires_git
def test_ensure_working_branch_skips_repo_without_commits(tmp_path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    assert git_sync.is_git_repo(tmp_path) is True
    assert git_sync.has_commits(tmp_path) is False
    assert git_sync.ensure_working_branch(tmp_path, "anything") is None
