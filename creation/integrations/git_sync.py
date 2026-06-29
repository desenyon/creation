"""Git push + PR workflow for GitHub shipping."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

LineCallback = Callable[[str], None]


def _run(cmd: list[str], cwd: Path, on_line: Optional[LineCallback] = None) -> Tuple[bool, str]:
    if on_line:
        on_line(f"$ {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if on_line and out:
            on_line(out)
        return r.returncode == 0, out
    except Exception as e:
        if on_line:
            on_line(str(e))
        return False, str(e)


def _ensure_git(workdir: Path, github_url: str, on_line: Optional[LineCallback] = None) -> bool:
    if not github_url or not shutil.which("git"):
        return False
    workdir.mkdir(parents=True, exist_ok=True)
    if not (workdir / ".git").exists():
        if not _run(["git", "init"], workdir, on_line)[0]:
            return False
        _run(["git", "branch", "-M", "main"], workdir, on_line)
    remote = github_url.rstrip("/")
    remote_url = remote if remote.endswith(".git") else remote + ".git"
    if _run(["git", "remote", "get-url", "origin"], workdir, on_line)[0]:
        _run(["git", "remote", "set-url", "origin", remote_url], workdir, on_line)
    else:
        _run(["git", "remote", "add", "origin", remote_url], workdir, on_line)
    return True


def commit_workdir(workdir: Path, message: str, on_line: Optional[LineCallback] = None) -> bool:
    if not _run(["git", "add", "-A"], workdir, on_line)[0]:
        return False
    ok, output = _run(["git", "commit", "-m", message], workdir, on_line)
    if ok:
        return True
    no_changes = "nothing to commit" in output.lower() or "no changes added to commit" in output.lower()
    return no_changes


def workdir_diff(workdir: Path, *, staged: bool = False) -> str:
    if not (workdir / ".git").exists() or not shutil.which("git"):
        return ""
    args = ["git", "diff", "--stat"]
    if staged:
        args.append("--cached")
    try:
        r = subprocess.run(args, cwd=str(workdir), capture_output=True, text=True, timeout=30)
        stat = (r.stdout or "").strip()
        r2 = subprocess.run(
            ["git", "diff"] + (["--cached"] if staged else []),
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        body = (r2.stdout or "").strip()
        combined = stat
        if body:
            combined += "\n\n" + body[:12000]
        return combined[:14000]
    except Exception:
        return ""


def push_workdir(
    workdir: Path,
    github_url: str,
    message: str,
    on_line: Optional[LineCallback] = None,
    *,
    branch: str = "main",
) -> bool:
    """Commit the complete worktree and make it the remote branch contents."""
    if not _ensure_git(workdir, github_url, on_line):
        return False
    if not commit_workdir(workdir, message, on_line):
        return False
    refspec = f"HEAD:{branch}"
    if _run(["git", "push", "-u", "origin", refspec], workdir, on_line)[0]:
        return True
    _run(["git", "fetch", "origin", branch], workdir, on_line)
    return _run(["git", "push", "-u", "origin", refspec, "--force-with-lease"], workdir, on_line)[0]


def push_feature_branch(
    workdir: Path,
    github_url: str,
    branch: str,
    message: str,
    on_line: Optional[LineCallback] = None,
) -> bool:
    if not _ensure_git(workdir, github_url, on_line):
        return False
    if not _run(["git", "checkout", "-B", branch], workdir, on_line)[0]:
        return False
    if not commit_workdir(workdir, message, on_line):
        return False
    return _run(["git", "push", "-u", "origin", branch], workdir, on_line)[0]


def create_pull_request(
    owner: str,
    repo: str,
    branch: str,
    title: str,
    body: str,
    on_line: Optional[LineCallback] = None,
) -> Tuple[bool, str]:
    """Open PR via gh CLI when available."""
    if not shutil.which("gh"):
        if on_line:
            on_line("gh CLI not found — push only")
        return False, ""
    ok, out = _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            f"{owner}/{repo}",
            "--head",
            branch,
            "--base",
            "main",
            "--title",
            title[:200],
            "--body",
            body[:6000],
        ],
        Path.cwd(),
        on_line,
    )
    url = ""
    for line in out.splitlines():
        if line.startswith("http"):
            url = line.strip()
    return ok, url


def is_git_repo(workdir: Path) -> bool:
    """True if workdir is inside a git work tree."""
    if not shutil.which("git"):
        return False
    return _run(["git", "rev-parse", "--is-inside-work-tree"], workdir)[0]


def has_commits(workdir: Path) -> bool:
    """True if the repo has at least one commit (HEAD resolves)."""
    if not shutil.which("git"):
        return False
    return _run(["git", "rev-parse", "HEAD"], workdir)[0]


def current_branch(workdir: Path) -> str:
    """Current branch name, or empty string if unavailable."""
    if not shutil.which("git"):
        return ""
    ok, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], workdir)
    return out.strip() if ok else ""


_GH_REMOTE_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.\s]+)",
    re.IGNORECASE,
)


def resolve_github_from_workdir(workdir: Path) -> tuple[str, str, str]:
    """Return (owner, repo, html_url) from git origin, or empty strings."""
    if not shutil.which("git") or not is_git_repo(workdir):
        return "", "", ""
    ok, out = _run(["git", "remote", "get-url", "origin"], workdir)
    if not ok or not out.strip():
        return "", "", ""
    match = _GH_REMOTE_RE.search(out.strip())
    if not match:
        return "", "", ""
    owner = match.group("owner")
    repo = match.group("repo").removesuffix(".git")
    return owner, repo, f"https://github.com/{owner}/{repo}"


def _sanitize_slug(slug: str) -> str:
    """Reduce slug to [a-z0-9-]; spaces/underscores → '-', collapse repeats."""
    s = (slug or "").lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "build"


def ensure_working_branch(
    workdir: Path, slug: str, on_line: Optional[LineCallback] = None
) -> Optional[str]:
    """Create/check out a dedicated `creation/<slug>` branch on an existing repo.

    Best-effort and safe: returns the branch name on success, or None if skipped
    (git missing, not a repo, no commits) or on any failure. Never raises.
    """
    try:
        if not shutil.which("git"):
            return None
        if not is_git_repo(workdir) or not has_commits(workdir):
            return None

        branch = f"creation/{_sanitize_slug(slug)}"

        cur = current_branch(workdir)
        if cur.startswith("creation/"):
            return cur

        # Branch already exists → check it out; otherwise create it.
        exists = _run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], workdir
        )[0]
        if exists:
            ok = _run(["git", "checkout", branch], workdir, on_line)[0]
        else:
            ok = _run(["git", "checkout", "-b", branch], workdir, on_line)[0]
        return branch if ok else None
    except Exception:
        logger.exception("ensure_working_branch failed")
        return None
