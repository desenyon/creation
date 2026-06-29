from pathlib import Path

from creation.integrations import git_sync


def test_commit_workdir_fails_when_staging_fails(monkeypatch):
    calls = []

    def fake_run(cmd, cwd, on_line=None):
        calls.append(cmd)
        return False, "git add failed"

    monkeypatch.setattr(git_sync, "_run", fake_run)

    assert git_sync.commit_workdir(Path("."), "turn") is False
    assert calls == [["git", "add", "-A"]]


def test_push_workdir_stops_when_commit_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(git_sync, "_ensure_git", lambda *args, **kwargs: True)
    monkeypatch.setattr(git_sync, "commit_workdir", lambda *args, **kwargs: False)

    def fake_run(cmd, cwd, on_line=None):
        calls.append(cmd)
        return True, ""

    monkeypatch.setattr(git_sync, "_run", fake_run)

    assert git_sync.push_workdir(Path("."), "https://github.com/acme/repo", "turn") is False
    assert calls == []


def test_commit_workdir_accepts_clean_tree(monkeypatch):
    responses = iter([(True, ""), (False, "nothing to commit, working tree clean")])
    monkeypatch.setattr(git_sync, "_run", lambda *args, **kwargs: next(responses))

    assert git_sync.commit_workdir(Path("."), "turn") is True


def test_push_workdir_pushes_current_complete_tree_to_main(monkeypatch):
    calls = []
    monkeypatch.setattr(git_sync, "_ensure_git", lambda *args, **kwargs: True)
    monkeypatch.setattr(git_sync, "commit_workdir", lambda *args, **kwargs: True)

    def fake_run(cmd, cwd, on_line=None):
        calls.append(cmd)
        return True, ""

    monkeypatch.setattr(git_sync, "_run", fake_run)

    assert git_sync.push_workdir(Path("."), "https://github.com/acme/repo", "ship")
    assert calls == [["git", "push", "-u", "origin", "HEAD:main"]]
