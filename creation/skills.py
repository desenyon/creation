"""Compounding skills memory — factory + per-project lessons."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

from creation.config import CONFIG_DIR

FACTORY_SKILLS_NAME = "FACTORY_SKILLS.md"
PROJECT_SKILLS_NAME = "PROJECT_SKILLS.md"
LESSONS_NAME = "LESSONS.md"
CREATION_DIR = ".creation"

_DEFAULT_FACTORY = """# Creation factory skills

Patterns that work across projects:

- Scaffold with README, tests, and a single clear entrypoint before features.
- Push all source files each turn — not just markdown logs.
- Prefer small, shippable increments mapped to Linear plan steps.
- When tests fail, fix the named test before adding features.
- Browser QA errors are blocking until resolved or explicitly waived.
"""

_DEFAULT_PROJECT = """# Project skills

Agent-maintained conventions for this repo (update as you learn):

- **Stack:** (fill on turn 1)
- **Test command:** `pytest` or `npm test`
- **Run command:** (fill when known)
- **Deploy:** (fill when known)
"""


def factory_skills_path() -> Path:
    return CONFIG_DIR / FACTORY_SKILLS_NAME


def ensure_factory_skills() -> Path:
    path = factory_skills_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_DEFAULT_FACTORY, encoding="utf-8")
    return path


def ensure_project_skills(workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / PROJECT_SKILLS_NAME
    if not path.exists():
        path.write_text(_DEFAULT_PROJECT, encoding="utf-8")
    (workdir / CREATION_DIR).mkdir(parents=True, exist_ok=True)
    return path


def load_skill_blocks(workdir: Path, *, max_chars: int = 9000) -> List[str]:
    """Blocks for SuperCompress / agent context."""
    ensure_factory_skills()
    ensure_project_skills(workdir)
    blocks: List[str] = []
    used = 0

    def _add(label: str, path: Path) -> None:
        nonlocal used
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return
        chunk = text[: max_chars - used]
        if not chunk:
            return
        blocks.append(f"## {label}\n{chunk}")
        used += len(chunk)

    _add("Factory skills (reuse across projects)", factory_skills_path())
    _add("Project skills", workdir / PROJECT_SKILLS_NAME)
    lessons = workdir / LESSONS_NAME
    if lessons.exists() and used < max_chars:
        lines = lessons.read_text(encoding="utf-8").strip().splitlines()
        tail = "\n".join(lines[-40:])
        if tail:
            chunk = tail[: max_chars - used]
            blocks.append(f"## Recent lessons\n{chunk}")

    return blocks


def record_turn_lesson(
    workdir: Path,
    turn: int,
    reason: str,
    *,
    qa_summary: str = "",
    follow_up: str = "",
) -> None:
    """Append a compact lesson after each routed turn."""
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / LESSONS_NAME
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [f"### Turn {turn} · {ts}", f"- Route: {reason[:200]}"]
    if follow_up:
        parts.append(f"- Next: {follow_up[:300]}")
    if qa_summary:
        parts.append(f"- QA: {qa_summary[:400]}")
    entry = "\n".join(parts) + "\n\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def skills_status(workdir: Path) -> dict:
    ensure_factory_skills()
    ensure_project_skills(workdir)
    lessons = workdir / LESSONS_NAME
    return {
        "factory_skills": str(factory_skills_path()),
        "project_skills": str(workdir / PROJECT_SKILLS_NAME),
        "lessons": str(lessons),
        "lesson_count": len(lessons.read_text(encoding="utf-8").split("### Turn")) - 1 if lessons.exists() else 0,
    }
