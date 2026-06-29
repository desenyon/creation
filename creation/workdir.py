"""Workdir introspection for Nebius review."""

from __future__ import annotations

from pathlib import Path

SKIP = {".git", "__pycache__", ".venv", "node_modules", ".creation"}
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".html", ".css", ".toml", ".yaml", ".yml", ".sh"}

# Files Creation writes into the workdir itself — ignored when deciding whether a
# directory is a pre-existing repo (versus an empty workdir Creation scaffolds).
CREATION_ARTIFACTS = {"RESEARCH.md", "BUILD_PLAN.md", "PRODUCT.md", "TEMPLATE.md"}


def has_existing_sources(workdir: Path) -> bool:
    """True when the workdir already holds project files (an existing repo).

    Ignores VCS/tooling dirs (``SKIP``) and Creation's own top-level artifacts so a
    freshly created or Creation-managed directory reads as empty, while a directory
    pointed at a real codebase reads as existing. Returns on the first match so
    it stays cheap even on large repos.
    """
    if not workdir.exists():
        return False
    for f in workdir.rglob("*"):
        if not f.is_file():
            continue
        if any(part in SKIP for part in f.relative_to(workdir).parts):
            continue
        if f.parent == workdir and f.name in CREATION_ARTIFACTS:
            continue
        return True
    return False


def workdir_summary(workdir: Path, max_files: int = 25) -> str:
    if not workdir.exists():
        return "(empty workdir)"
    lines: list[str] = []
    files = sorted(
        [f for f in workdir.rglob("*") if f.is_file() and not any(p in SKIP for p in f.parts)],
        key=lambda p: str(p),
    )
    for f in files[:max_files]:
        rel = f.relative_to(workdir)
        if f.suffix.lower() in TEXT_EXT and f.stat().st_size < 80_000:
            try:
                body = f.read_text(errors="replace")[:1200]
                lines.append(f"### {rel}\n```\n{body}\n```")
            except OSError:
                lines.append(f"### {rel}\n(unreadable)")
        else:
            lines.append(f"### {rel}\n({f.stat().st_size} bytes)")
    if len(files) > max_files:
        lines.append(f"\n… and {len(files) - max_files} more files")
    return "\n\n".join(lines) if lines else "(no files yet)"
