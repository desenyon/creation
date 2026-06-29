"""Targeting Creation at any directory — existing-repo detection and safety."""

import pytest

from creation.nebius_client import ProductBrand
from creation.integrations.project_tracker import TrackState
from creation.orchestrator import _initial_agent_prompt
from creation.store import create_project, init_db
from creation.templates import apply_template
from creation.workdir import has_existing_sources


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    return tmp_path


# ── has_existing_sources ──────────────────────────────────────────────


def test_empty_dir_is_not_existing(tmp_path):
    assert has_existing_sources(tmp_path) is False


def test_missing_dir_is_not_existing(tmp_path):
    assert has_existing_sources(tmp_path / "nope") is False


def test_only_creation_artifacts_is_not_existing(tmp_path):
    (tmp_path / "RESEARCH.md").write_text("x")
    (tmp_path / "BUILD_PLAN.md").write_text("x")
    (tmp_path / "PRODUCT.md").write_text("x")
    (tmp_path / "TEMPLATE.md").write_text("x")
    assert has_existing_sources(tmp_path) is False


def test_files_in_skipped_dirs_are_ignored(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / ".creation" / "qa").mkdir(parents=True)
    (tmp_path / ".creation" / "qa" / "meta.json").write_text("{}")
    assert has_existing_sources(tmp_path) is False


def test_source_file_marks_existing(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')")
    assert has_existing_sources(tmp_path) is True


def test_nested_source_file_marks_existing(tmp_path):
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "index.ts").write_text("export const x = 1")
    assert has_existing_sources(tmp_path) is True


# ── apply_template preserves existing repos ───────────────────────────


def test_template_preserve_existing_skips_scaffold(tmp_path):
    (tmp_path / "main.py").write_text("# existing")
    hint = apply_template(tmp_path, "cli", "an idea", preserve_existing=True)
    # No scaffolding written over the existing project.
    assert not (tmp_path / "pyproject.toml").exists()
    assert "Existing codebase" in hint


def test_template_scaffolds_when_not_preserving(tmp_path):
    apply_template(tmp_path, "cli", "an idea", preserve_existing=False)
    assert (tmp_path / "pyproject.toml").exists()


def test_greenfield_never_writes_files(tmp_path):
    hint = apply_template(tmp_path, "greenfield", "idea", preserve_existing=True)
    assert "Greenfield" in hint
    assert list(tmp_path.iterdir()) == []


# ── create_project honours an external workdir ────────────────────────


def test_create_project_uses_external_workdir(isolated_store, tmp_path):
    repo = tmp_path / "my-existing-repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1")
    p = create_project(name="existing", idea="add a feature", workdir=str(repo))
    assert p.workdir == str(repo.resolve())
    # Creation must not relocate it under the managed projects dir.
    assert ".creation" not in p.workdir or str(repo) in p.workdir
    assert (repo / "app.py").exists()


def test_create_project_default_workdir_is_managed(isolated_store):
    p = create_project(name="fresh", idea="build something")
    assert str(isolated_store) in p.workdir


# ── prompt adapts to existing repos ───────────────────────────────────


def _prompt(existing):
    return _initial_agent_prompt(
        "Add OAuth login",
        "## plan",
        "## context",
        TrackState(),
        ProductBrand.from_idea("Add OAuth login"),
        existing_repo=existing,
    )


def test_existing_repo_prompt_instructs_in_place_edit():
    out = _prompt(True)
    assert "EXISTING CODEBASE" in out
    assert "change request" in out
    assert "Scaffold MVP" not in out


def test_greenfield_prompt_scaffolds():
    out = _prompt(False)
    assert "Scaffold MVP" in out
    assert "EXISTING CODEBASE" not in out
