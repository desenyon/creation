"""Skills memory + autosuggest."""

from pathlib import Path

from creation.skills import (
    ensure_factory_skills,
    ensure_project_skills,
    load_skill_blocks,
    record_turn_lesson,
    skills_status,
)
from creation.suggest import _demo_suggestions, _parse_suggestions, suggest_products
from creation.config import UserSecrets


def test_factory_skills_created(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.skills.CONFIG_DIR", tmp_path)
    path = ensure_factory_skills()
    assert path.exists()
    assert "factory" in path.read_text().lower()


def test_project_skills_and_lessons(tmp_path):
    wd = tmp_path / "proj"
    ensure_project_skills(wd)
    record_turn_lesson(wd, 1, "Kickoff", qa_summary="0 failures", follow_up="Add tests")
    record_turn_lesson(wd, 2, "Polish UI", follow_up="Fix nav")
    blocks = load_skill_blocks(wd)
    assert any("Project skills" in b for b in blocks)
    assert any("Turn 2" in b or "Recent lessons" in b for b in blocks)
    st = skills_status(wd)
    assert st["lesson_count"] >= 2


def test_parse_suggestions_json():
    raw = '[{"title":"X","idea":"do y","pitch":"because","score":0.9,"signals":["a"]}]'
    items = _parse_suggestions(raw)
    assert len(items) == 1
    assert items[0].title == "X"
    assert items[0].score == 0.9


def test_suggest_products_demo():
    secrets = UserSecrets()
    ideas, bundle = suggest_products(secrets, "devtools", demo=True, count=3)
    assert len(ideas) == 3
    assert bundle.query
    assert ideas[0].title


def test_suggest_api():
    from fastapi.testclient import TestClient

    from creation.server import app

    client = TestClient(app)
    r = client.post("/api/suggest", json={"seed": "CLI tools", "count": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data["suggestions"]) >= 1
    assert "idea" in data["suggestions"][0]
