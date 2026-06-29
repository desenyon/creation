"""Repo Archaeologist — turn a git history into an onboarding brief.

Creation's differentiator (see future.md) is that it *understands the engineering
system*, not just the current file. This module reads a real git repo — churn,
ownership, risk hotspots, test/CI/ownership signals — and synthesizes a
new-engineer onboarding brief plus a handful of *safe starter tasks*.

It is deliberately dependency-free: all signals come from `git` via
``git_sync._run`` (already used elsewhere), and the synthesis step degrades to a
pure-Python heuristic when no Nebius key is configured. Nothing here raises on a
bad/empty repo — it returns a partial brief instead.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from creation.config import UserSecrets
from creation.integrations.git_sync import _run, is_git_repo, resolve_github_from_workdir

logger = logging.getLogger(__name__)

# How far back to measure churn/activity. Long enough to be meaningful, short
# enough to reflect what the team works on *now*.
_CHURN_SINCE = "365 days ago"
_RECENT_SINCE = "90 days ago"
_TOP_FILES = 10

_EXT_LANG = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".cs": "C#", ".swift": "Swift", ".m": "Objective-C", ".scala": "Scala",
    ".sql": "SQL", ".sh": "Shell", ".css": "CSS", ".scss": "CSS", ".html": "HTML",
    ".vue": "Vue", ".svelte": "Svelte", ".dart": "Dart", ".ex": "Elixir", ".clj": "Clojure",
}

ARCHAEOLOGIST_SYSTEM = """You are Creation's Repo Archaeologist. You receive structured
git signals about a real codebase and write a concise onboarding brief for a new
engineer. Be concrete and grounded ONLY in the signals provided — never invent
file names, owners, or incidents.

Return JSON only, this exact shape:
{
  "summary": "3-4 sentence orientation: what this repo is, its size/age, how active it is, and where the action is.",
  "architecture_notes": ["inference about structure from the directories/languages present", "..."],
  "unwritten_rules": ["a norm a newcomer should respect, inferred from the signals (e.g. high-churn area owned by one person → coordinate with them)", "..."],
  "risky_files": [{"path": "exact path from signals", "why": "why it's risky to touch (churn, bus-factor, no tests, etc.)"}],
  "starter_tasks": [{"title": "a safe, scoped first task", "why": "why it's safe and valuable", "risk": "low|medium"}]
}
Prefer 3-5 items per list. starter_tasks must be genuinely safe for a newcomer."""


# ── signals (pure git, no LLM) ─────────────────────────────────────────────────
@dataclass
class RiskyFile:
    path: str
    churn: int = 0
    authors: int = 0
    risk: str = "low"  # low | medium | high
    owner: str = ""
    why: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RepoSignals:
    repo_path: str = ""
    repo_name: str = ""
    github_url: str = ""
    is_repo: bool = False

    total_commits: int = 0
    recent_commits: int = 0
    contributors: int = 0
    recent_contributors: int = 0
    age_days: int = 0
    first_commit: str = ""
    last_commit: str = ""
    current_branch: str = ""

    languages: List[Tuple[str, int]] = field(default_factory=list)  # (lang, files)
    primary_language: str = ""
    tracked_files: int = 0

    top_contributors: List[Dict[str, Any]] = field(default_factory=list)  # name, commits, pct
    risky_files: List[RiskyFile] = field(default_factory=list)
    ownership: List[Dict[str, str]] = field(default_factory=list)  # area, owner

    has_tests: bool = False
    has_ci: bool = False
    has_codeowners: bool = False
    has_readme: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risky_files"] = [r.to_dict() for r in self.risky_files]
        d["languages"] = [{"lang": l, "files": n} for l, n in self.languages]
        return d


def _git(repo: Path, args: List[str]) -> str:
    ok, out = _run(["git", *args], repo)
    return out if ok else ""


def _count_distinct_authors(repo: Path, path: str) -> Tuple[int, str]:
    """(#distinct authors, primary author) for a path, from full history."""
    out = _git(repo, ["log", "--format=%an", "--", path])
    names = [n for n in out.splitlines() if n.strip()]
    if not names:
        return 0, ""
    counts = Counter(names)
    return len(counts), counts.most_common(1)[0][0]


def _first_commit_date(repo: Path) -> str:
    out = _git(repo, ["log", "--max-parents=0", "--format=%as", "HEAD"])
    # may emit multiple root commits; take the earliest non-empty line
    dates = sorted(d for d in out.splitlines() if d.strip())
    return dates[0] if dates else ""


def _age_days(first: str, last: str) -> int:
    from datetime import date

    def _parse(s: str) -> Optional[date]:
        try:
            y, m, d = (int(x) for x in s.split("-"))
            return date(y, m, d)
        except Exception:
            return None

    a, b = _parse(first), _parse(last)
    if a and b:
        return max((b - a).days, 0)
    return 0


def _detect_paths(repo: Path) -> Tuple[bool, bool, bool, bool]:
    """(has_tests, has_ci, has_codeowners, has_readme)."""
    def ex(*parts: str) -> bool:
        return (repo.joinpath(*parts)).exists()

    has_ci = ex(".github", "workflows") or ex(".gitlab-ci.yml") or ex(".circleci")
    has_codeowners = ex("CODEOWNERS") or ex(".github", "CODEOWNERS") or ex("docs", "CODEOWNERS")
    has_readme = any((repo / f"README{e}").exists() for e in ("", ".md", ".rst", ".txt"))
    has_tests = ex("tests") or ex("test") or ex("spec") or ex("__tests__")
    return has_tests, has_ci, has_codeowners, has_readme


def analyze_repo(path: str | os.PathLike[str]) -> RepoSignals:
    """Read a git repo and produce structured signals. Never raises."""
    repo = Path(path).expanduser().resolve()
    sig = RepoSignals(repo_path=str(repo), repo_name=repo.name)

    if not repo.exists() or not is_git_repo(repo):
        return sig
    sig.is_repo = True

    owner, name, url = resolve_github_from_workdir(repo)
    sig.github_url = url
    if name:
        sig.repo_name = name

    # ── activity & age ──
    sig.current_branch = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    sig.total_commits = _safe_int(_git(repo, ["rev-list", "--count", "HEAD"]))
    sig.recent_commits = _safe_int(
        _git(repo, ["rev-list", "--count", f"--since={_RECENT_SINCE}", "HEAD"])
    )
    sig.last_commit = _git(repo, ["log", "-1", "--format=%as"]).strip()
    sig.first_commit = _first_commit_date(repo)
    sig.age_days = _age_days(sig.first_commit, sig.last_commit)

    # ── contributors (all-time) ──
    all_authors = [n for n in _git(repo, ["log", "--format=%an", "HEAD"]).splitlines() if n.strip()]
    author_counts = Counter(all_authors)
    sig.contributors = len(author_counts)
    total = sum(author_counts.values()) or 1
    sig.top_contributors = [
        {"name": n, "commits": c, "pct": round(100 * c / total)}
        for n, c in author_counts.most_common(6)
    ]
    recent_authors = {
        n for n in _git(repo, ["log", f"--since={_RECENT_SINCE}", "--format=%an", "HEAD"]).splitlines()
        if n.strip()
    }
    sig.recent_contributors = len(recent_authors)

    # ── languages from tracked files ──
    tracked = [f for f in _git(repo, ["ls-files"]).splitlines() if f.strip()]
    sig.tracked_files = len(tracked)
    lang_counts: Counter = Counter()
    for f in tracked:
        lang = _EXT_LANG.get(Path(f).suffix.lower())
        if lang:
            lang_counts[lang] += 1
    sig.languages = lang_counts.most_common(6)
    sig.primary_language = sig.languages[0][0] if sig.languages else ""

    # ── churn → risky files ──
    churn_out = _git(
        repo, ["log", f"--since={_CHURN_SINCE}", "--name-only", "--pretty=format:"]
    )
    churn = Counter(l.strip() for l in churn_out.splitlines() if l.strip())
    risky: List[RiskyFile] = []
    for fpath, count in churn.most_common(_TOP_FILES):
        # skip files that no longer exist (deleted/renamed churn)
        if not (repo / fpath).exists():
            continue
        n_authors, primary = _count_distinct_authors(repo, fpath)
        rf = RiskyFile(path=fpath, churn=count, authors=n_authors, owner=primary)
        rf.risk, rf.why = _score_risk(count, n_authors)
        risky.append(rf)
        if len(risky) >= 8:
            break
    sig.risky_files = risky

    # ── path signals (after risky so risk scoring can use has_tests) ──
    sig.has_tests, sig.has_ci, sig.has_codeowners, sig.has_readme = _detect_paths(repo)

    # ── ownership by top-level area (derived from risky-file owners) ──
    area_owner: Dict[str, Counter] = {}
    for rf in risky:
        area = rf.path.split("/")[0] if "/" in rf.path else "(root)"
        area_owner.setdefault(area, Counter())[rf.owner or "unknown"] += rf.churn
    sig.ownership = [
        {"area": area, "owner": counts.most_common(1)[0][0]}
        for area, counts in sorted(area_owner.items(), key=lambda kv: -sum(kv[1].values()))
    ][:6]

    return sig


def _safe_int(s: str) -> int:
    try:
        return int(s.strip().splitlines()[0])
    except Exception:
        return 0


def _score_risk(churn: int, authors: int) -> Tuple[str, str]:
    reasons = [f"changed {churn}× in the last year"]
    score = 0
    if churn >= 20:
        score += 2
    elif churn >= 8:
        score += 1
    if authors <= 1:
        score += 2
        reasons.append("only one author (bus-factor risk)")
    elif authors >= 6:
        score += 1
        reasons.append(f"{authors} authors (high coordination)")
    tier = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return tier, "; ".join(reasons)


# ── brief (LLM synthesis + heuristic fallback) ────────────────────────────────
@dataclass
class StarterTask:
    title: str
    why: str = ""
    risk: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OnboardingBrief:
    repo_name: str = ""
    repo_path: str = ""
    github_url: str = ""
    summary: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)
    top_contributors: List[Dict[str, Any]] = field(default_factory=list)
    ownership: List[Dict[str, str]] = field(default_factory=list)
    risky_files: List[Dict[str, Any]] = field(default_factory=list)
    architecture_notes: List[str] = field(default_factory=list)
    unwritten_rules: List[str] = field(default_factory=list)
    starter_tasks: List[Dict[str, Any]] = field(default_factory=list)
    generated_by: str = "heuristic"  # heuristic | nebius
    is_repo: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_signals(cls, sig: RepoSignals) -> "OnboardingBrief":
        """Deterministic brief built purely from signals (no LLM)."""
        if not sig.is_repo:
            return cls(
                repo_name=sig.repo_name, repo_path=sig.repo_path, is_repo=False,
                summary="Not a git repository (or git is unavailable), so there is no "
                        "history to mine. Point the archaeologist at a checked-out repo.",
            )

        langs = ", ".join(f"{l} ({n})" for l, n in sig.languages[:3]) or "mixed"
        age_txt = f"{sig.age_days // 365}y" if sig.age_days >= 365 else f"{sig.age_days}d"
        activity = (
            "very active" if sig.recent_commits >= 50
            else "active" if sig.recent_commits >= 10
            else "quiet lately" if sig.recent_commits else "dormant"
        )
        summary = (
            f"{sig.repo_name} is a {age_txt}-old {sig.primary_language or 'multi-language'} "
            f"codebase ({sig.tracked_files} tracked files, {sig.total_commits} commits, "
            f"{sig.contributors} contributors). It's {activity} — {sig.recent_commits} commits "
            f"from {sig.recent_contributors} people in the last 90 days. Primary languages: {langs}."
        )

        notes: List[str] = []
        if sig.languages:
            notes.append(f"Built primarily in {sig.primary_language}; "
                         + ", ".join(l for l, _ in sig.languages[:3]) + " dominate the tree.")
        top_areas = [o["area"] for o in sig.ownership[:3]]
        if top_areas:
            notes.append("Most active areas: " + ", ".join(top_areas) + ".")
        notes.append(
            ("Has a test directory." if sig.has_tests else "No obvious test directory — tread carefully.")
            + (" CI configured." if sig.has_ci else " No CI config found.")
            + (" CODEOWNERS present." if sig.has_codeowners else " No CODEOWNERS — ownership is implicit.")
        )

        rules: List[str] = []
        solo = [rf for rf in sig.risky_files if rf.authors <= 1 and rf.owner]
        if solo:
            owners = sorted({rf.owner for rf in solo})[:3]
            rules.append(
                f"Several hot files are effectively owned by one person ({', '.join(owners)}). "
                "Loop them in before changing those areas."
            )
        if not sig.has_codeowners:
            rules.append("No CODEOWNERS file — ownership is tribal; ask before large refactors.")
        if not sig.has_tests:
            rules.append("No test suite detected — add coverage alongside any change you ship.")
        if sig.current_branch and sig.current_branch != "main":
            rules.append(f"Default work happens on '{sig.current_branch}', not 'main'.")

        tasks = _heuristic_starter_tasks(sig)

        return cls(
            repo_name=sig.repo_name,
            repo_path=sig.repo_path,
            github_url=sig.github_url,
            summary=summary,
            stats={
                "total_commits": sig.total_commits,
                "recent_commits": sig.recent_commits,
                "contributors": sig.contributors,
                "recent_contributors": sig.recent_contributors,
                "age_days": sig.age_days,
                "first_commit": sig.first_commit,
                "last_commit": sig.last_commit,
                "primary_language": sig.primary_language,
                "tracked_files": sig.tracked_files,
                "branch": sig.current_branch,
                "has_tests": sig.has_tests,
                "has_ci": sig.has_ci,
                "has_codeowners": sig.has_codeowners,
                "has_readme": sig.has_readme,
            },
            top_contributors=sig.top_contributors,
            ownership=sig.ownership,
            risky_files=[rf.to_dict() for rf in sig.risky_files],
            architecture_notes=notes,
            unwritten_rules=rules,
            starter_tasks=[t.to_dict() for t in tasks],
            generated_by="heuristic",
        )


def _heuristic_starter_tasks(sig: RepoSignals) -> List[StarterTask]:
    tasks: List[StarterTask] = []
    if not sig.has_ci:
        tasks.append(StarterTask(
            "Add a CI workflow that runs the build + tests on every push",
            "No CI was detected; a basic pipeline is low-risk and immediately useful.", "low"))
    if not sig.has_codeowners:
        tasks.append(StarterTask(
            "Add a CODEOWNERS file capturing the de-facto owners",
            "Ownership is currently implicit; this documents it without touching code.", "low"))
    if not sig.has_readme:
        tasks.append(StarterTask(
            "Write a README with setup + run instructions",
            "Onboarding doc; pure docs, no code risk.", "low"))
    # untested hot file → add tests
    for rf in sig.risky_files:
        if rf.risk in ("high", "medium") and not sig.has_tests:
            tasks.append(StarterTask(
                f"Add unit tests for {rf.path}",
                f"It {rf.why} but has no test coverage — tests make future changes safe.", "low"))
            break
    # read the single most-churned file as an orientation exercise
    if sig.risky_files:
        hot = sig.risky_files[0]
        tasks.append(StarterTask(
            f"Read {hot.path} and write a short design note on what it does",
            "It's the busiest file in the repo — understanding it orients you fast. Read-only.", "low"))
    if len(tasks) < 3 and sig.primary_language:
        tasks.append(StarterTask(
            f"Set up a local dev environment and run the {sig.primary_language} project end-to-end",
            "Confirms your environment works before you change anything.", "low"))
    return tasks[:5]


def _signals_context(sig: RepoSignals) -> str:
    """Compact, model-friendly rendering of the signals."""
    lines = [
        f"repo: {sig.repo_name}",
        f"github: {sig.github_url or '(local only)'}",
        f"branch: {sig.current_branch}",
        f"commits: {sig.total_commits} total, {sig.recent_commits} in last 90d",
        f"contributors: {sig.contributors} total, {sig.recent_contributors} recent",
        f"age_days: {sig.age_days}  first: {sig.first_commit}  last: {sig.last_commit}",
        f"languages: " + ", ".join(f"{l}:{n}" for l, n in sig.languages),
        f"tracked_files: {sig.tracked_files}",
        f"has_tests={sig.has_tests} has_ci={sig.has_ci} has_codeowners={sig.has_codeowners} has_readme={sig.has_readme}",
        "top_contributors: " + ", ".join(f"{c['name']}({c['pct']}%)" for c in sig.top_contributors),
        "ownership_by_area: " + ", ".join(f"{o['area']}→{o['owner']}" for o in sig.ownership),
        "hot_files:",
    ]
    for rf in sig.risky_files:
        lines.append(f"  - {rf.path} (churn={rf.churn}, authors={rf.authors}, owner={rf.owner}, risk={rf.risk})")
    return "\n".join(lines)


def synthesize_brief(
    secrets: UserSecrets, sig: RepoSignals, *, demo: bool = False
) -> OnboardingBrief:
    """Synthesize the brief. Uses Nebius when a key is set, else heuristic."""
    base = OnboardingBrief.from_signals(sig)
    if not sig.is_repo or demo or not secrets.nebius_api_key.strip():
        return base

    try:
        from creation.nebius_client import _client, _parse_json_blob

        client = _client(secrets)
        resp = client.chat.completions.create(
            model=secrets.nebius_model,
            messages=[
                {"role": "system", "content": ARCHAEOLOGIST_SYSTEM},
                {"role": "user", "content": "Signals:\n" + _signals_context(sig)},
            ],
            max_tokens=1100,
        )
        raw = _parse_json_blob((resp.choices[0].message.content or "").strip())
    except Exception:
        logger.exception("archaeology synthesis failed; using heuristic brief")
        return base

    if not raw:
        return base

    if raw.get("summary"):
        base.summary = str(raw["summary"])[:1200]
    base.architecture_notes = _str_list(raw.get("architecture_notes")) or base.architecture_notes
    base.unwritten_rules = _str_list(raw.get("unwritten_rules")) or base.unwritten_rules

    valid_paths = {rf["path"] for rf in base.risky_files}
    rf_out = []
    for item in raw.get("risky_files") or []:
        if isinstance(item, dict) and str(item.get("path")) in valid_paths:
            match = next(r for r in base.risky_files if r["path"] == str(item["path"]))
            rf_out.append({**match, "why": str(item.get("why") or match["why"])[:300]})
    if rf_out:
        base.risky_files = rf_out

    tasks = []
    for item in raw.get("starter_tasks") or []:
        if isinstance(item, dict) and item.get("title"):
            risk = str(item.get("risk") or "low").lower()
            tasks.append({
                "title": str(item["title"])[:160],
                "why": str(item.get("why") or "")[:300],
                "risk": risk if risk in ("low", "medium", "high") else "low",
            })
    if tasks:
        base.starter_tasks = tasks[:6]

    base.generated_by = "nebius"
    return base


def explore_repo(secrets: UserSecrets, path: str, *, demo: bool = False) -> OnboardingBrief:
    """One-shot: analyze a repo and synthesize an onboarding brief."""
    return synthesize_brief(secrets, analyze_repo(path), demo=demo)


def _str_list(v: Any, limit: int = 6) -> List[str]:
    if not isinstance(v, list):
        return []
    return [str(x)[:300] for x in v[:limit] if str(x).strip()]
