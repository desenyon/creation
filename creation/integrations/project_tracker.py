"""Composio-backed project tracking — Linear, GitHub, Gmail."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from creation.config import UserSecrets
from creation.integrations.composio_ops import ComposioOps, OpsResult
from creation.integrations.git_sync import (
    create_pull_request,
    push_feature_branch,
    push_workdir,
    workdir_diff,
)
from creation.nebius_client import (
    ProductBrand,
    generate_linear_board_sync,
    generate_pr_body,
    generate_progress_email,
)
from creation.review.qa import QABundle

logger = logging.getLogger(__name__)

PlayCallback = Callable[[Dict[str, Any]], None]


@dataclass
class LinearIssueRef:
    id: str
    title: str
    identifier: str = ""
    state: str = "backlog"
    turn: int = 0
    step_index: int = 0
    category: str = ""  # epic | plan | test | qa | task


@dataclass
class TrackState:
    linear_project_id: str = ""
    linear_project_name: str = ""
    linear_project_url: str = ""
    linear_issues: List[LinearIssueRef] = field(default_factory=list)
    github_owner: str = ""
    github_repo: str = ""
    github_url: str = ""
    plan_issue_id: str = ""

    def to_context_block(self) -> str:
        lines = ["## Project tracking (Composio)"]
        if self.linear_project_url:
            lines.append(f"**Linear project:** {self.linear_project_url}")
        if self.github_url:
            lines.append(f"**GitHub repo:** {self.github_url}")
        if self.linear_issues:
            lines.append("\n### Kanban board")
            buckets: Dict[str, List[LinearIssueRef]] = {
                "In progress": [],
                "Todo": [],
                "Done": [],
            }
            for iss in self.linear_issues:
                if iss.category == "epic":
                    continue
                st = iss.state.lower()
                if st in ("done", "completed", "complete"):
                    buckets["Done"].append(iss)
                elif st in ("in progress", "started"):
                    buckets["In progress"].append(iss)
                else:
                    buckets["Todo"].append(iss)
            for label, items in buckets.items():
                if items:
                    lines.append(f"\n**{label}**")
                    for iss in items[:12]:
                        tag = f"[{iss.category}] " if iss.category else ""
                        ident = iss.identifier or iss.id[:8]
                        lines.append(f"- [{ident}] {tag}{iss.title}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["linear_issues"] = [asdict(i) for i in self.linear_issues]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackState":
        issues = [LinearIssueRef(**i) for i in data.get("linear_issues", [])]
        return cls(
            linear_project_id=data.get("linear_project_id", ""),
            linear_project_name=data.get("linear_project_name", ""),
            linear_project_url=data.get("linear_project_url", ""),
            linear_issues=issues,
            github_owner=data.get("github_owner", ""),
            github_repo=data.get("github_repo", ""),
            github_url=data.get("github_url", ""),
            plan_issue_id=data.get("plan_issue_id", ""),
        )


_SKIP_SYNC_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
}
_SYNC_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".sh",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".ini",
    ".sql",
    ".xml",
    ".env.example",
}
_MAX_COMPOSIO_SYNC_FILES = 120
_EXTRA_SYNC_NAMES = {
    "README.md",
    "LICENSE",
    "Dockerfile",
    "Makefile",
    "CREATION_STATUS.md",
    "BUILD_PLAN.md",
    "RESEARCH.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
}


def _slugify(text: str, max_len: int = 18) -> str:
    s = re.sub(r"[^a-z0-9-]", "-", text.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len].rstrip("-") or "creation-app")


def parse_plan_steps(plan: str) -> List[str]:
    steps: List[str] = []
    for line in plan.splitlines():
        line = line.strip()
        if re.match(r"^\d+[\.\)]\s+", line):
            steps.append(re.sub(r"^\d+[\.\)]\s+", "", line))
        elif line.startswith("- ") and len(line) > 3:
            steps.append(line[2:].strip())
    return steps or [plan[:200]]


def _dig(obj: Any, *keys: str, default: Any = "") -> Any:
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur if cur is not None else default


class ProjectTracker:
    """Linear project + GitHub repo + Gmail progress for one Creation build."""

    def __init__(self, ops: ComposioOps, secrets: UserSecrets, on_play: Optional[PlayCallback] = None):
        self.ops = ops
        self.secrets = secrets
        self.on_play = on_play
        self.state = TrackState()
        self.brand = ProductBrand()
        self._plan = ""
        self._plan_steps: List[str] = []
        self._state_name_to_id: Dict[str, str] = {}
        self._done_state_cache: Optional[str] = None
        # True when we attached to a pre-existing GitHub repo (created or local
        # remote) rather than creating a fresh one — drives "reuse" messaging and
        # branch-safe shipping (push a creation branch + PR, never clobber main).
        self.reused_repo = False
        # Honest ship outcomes — only set when an action *actually* succeeded, so
        # the receipt reports "live" rather than "configured".
        self.outcomes: Dict[str, Any] = {
            "github_repo": False,
            "github_pushed": False,
            "github_reused": False,
            "commits": 0,
            "gmail_ok": False,
            "linear_ok": False,
            "pr_url": "",
        }

    def _play(self, message: str, *, kind: str = "info", url: str = "") -> None:
        if not self.on_play:
            return
        payload: Dict[str, Any] = {
            "message": message,
            "kind": kind,
            "url": url,
            "linear_url": self.state.linear_project_url,
            "github_url": self.state.github_url,
            "linear_project": self.state.linear_project_name,
        }
        self.on_play(payload)

    def bootstrap(
        self,
        idea: str,
        plan: str,
        project_id: str,
        project_name: str,
        brand: Optional[ProductBrand] = None,
        *,
        workdir: Optional[Path] = None,
        existing_repo: bool = False,
    ) -> TrackState:
        team_id = self.ops.resolve_linear_team_id()
        if not team_id and not self.ops.demo:
            logger.warning("No Linear team — connect Linear in Composio dashboard")

        self.brand = brand or ProductBrand.from_idea(idea)
        self._plan = plan
        pname = self.brand.linear_project_name or project_name[:48] or idea[:48] or "Creation build"
        self.state.linear_project_name = pname

        # GitHub repo first — reuse existing remote when editing in place
        used_existing_remote = False
        if existing_repo and workdir:
            from creation.integrations.git_sync import resolve_github_from_workdir

            owner, repo, url = resolve_github_from_workdir(workdir)
            if url:
                self.state.github_owner = owner
                self.state.github_repo = repo
                self.state.github_url = url
                used_existing_remote = True
                self.reused_repo = True
                self._play(
                    f"Using existing repo · {owner}/{repo}",
                    kind="github",
                    url=url,
                )
            else:
                self._ensure_github_repo(idea, project_id, repo_slug=self.brand.repo_slug)
        else:
            self._ensure_github_repo(idea, project_id, repo_slug=self.brand.repo_slug)
        self.outcomes["github_repo"] = bool(self.state.github_url)
        self.outcomes["github_reused"] = self.reused_repo
        if self.state.github_url and not used_existing_remote:
            verb = "Using existing repo" if self.reused_repo else "GitHub repo created"
            self._play(
                f"{verb} · {self.state.github_owner}/{self.state.github_repo}",
                kind="github",
                url=self.state.github_url,
            )
        elif not self.state.github_url:
            self._play(
                "GitHub via Composio not connected — agent can use gh repo create locally",
                kind="github",
            )

        use_existing_linear = (
            self.secrets.linear_project_mode == "existing" and bool(self.secrets.linear_project_id.strip())
        )
        if team_id or self.ops.demo or use_existing_linear:
            self._ensure_linear_project(pname, idea, team_id)
            self._create_plan_issues(plan, team_id, idea)
            self.outcomes["linear_ok"] = bool(self.state.linear_project_id)
            self._play(
                f"Linear project · {pname}",
                kind="linear",
                url=self.state.linear_project_url,
            )

        kickoff_body = self._compose_email(
            kind="kickoff",
            idea=idea,
            turn=0,
            agent_ok=True,
            agent_excerpt=plan[:2000],
            linear_summary=self.state.to_context_block(),
        )
        gmail = self._notify(
            subject=f"[Creation] Started — {self.brand.product_name or pname}",
            body=self._email_body(kickoff_body),
            kind="started",
        )
        self.outcomes["gmail_ok"] = self.outcomes["gmail_ok"] or bool(gmail.success)
        self._play(f"Kickoff email sent · {gmail.detail[:80]}", kind="gmail")
        return self.state

    def after_turn(
        self,
        turn: int,
        idea: str,
        agent_ok: bool,
        workdir: Path,
        agent_summary: str = "",
        qa: Optional[QABundle] = None,
        on_line: Optional[Callable[[str], None]] = None,
    ) -> OpsResult:
        team_id = self.secrets.linear_team_id.strip() or self.ops.resolve_linear_team_id()
        qa_bundle = qa or QABundle()
        linear_ctx = self.refresh_linear_status()

        board_summary = self._sync_linear_kanban(
            turn, idea, team_id, agent_summary, qa_bundle, linear_ctx
        )

        self._post_project_update(
            turn,
            board_summary
            or (
                f"**Turn {turn}** — {'on track' if agent_ok else 'blocked'}\n\n"
                f"{qa_bundle.tests.to_context_block()}\n\n"
                f"{qa_bundle.browser.to_context_block()}\n\n"
                f"{agent_summary[:1200]}"
            ),
            health="onTrack" if agent_ok and qa_bundle.tests.failed == 0 else "atRisk",
        )
        commit_msg = self._commit_message(turn, agent_summary)
        ship_mode = getattr(self.secrets, "ship_mode", "push") or "push"
        # Never clobber a repo we attached to — ship to a creation branch + PR.
        if self.reused_repo:
            ship_mode = "pr"
        branch = f"creation/turn-{turn}"
        if ship_mode == "pr" and self.state.github_url:
            pushed = push_feature_branch(
                workdir, self.state.github_url, branch, commit_msg, on_line
            )
        else:
            pushed = push_workdir(workdir, self.state.github_url, commit_msg, on_line)
        self.sync_workdir_to_github(workdir, turn, idea, composio_fallback=not pushed)
        if pushed:
            self.outcomes["github_pushed"] = True
            self.outcomes["commits"] += 1
            self._play(f"Turn {turn}: git push ({ship_mode}) to GitHub", kind="github", url=self.state.github_url)
        else:
            self._play(f"Turn {turn}: source synced to GitHub via Composio", kind="github", url=self.state.github_url)

        linear_summary = self.refresh_linear_status()
        turn_body = self._compose_email(
            kind="turn",
            idea=idea,
            turn=turn,
            agent_ok=agent_ok,
            agent_excerpt=agent_summary,
            linear_summary=linear_summary,
            qa=qa_bundle,
            board_summary=board_summary,
            workdir=workdir,
            git_pushed=pushed,
        )
        gmail = self._notify(
            subject=f"[Creation] Turn {turn} — {self.brand.product_name or idea[:40]}",
            body=self._email_body(turn_body),
            kind="turn",
            turn=turn,
        )
        self.outcomes["gmail_ok"] = self.outcomes["gmail_ok"] or bool(gmail.success)
        self._play(
            f"Turn {turn}: Linear updated · GitHub synced · progress email sent",
            kind="sync",
            url=self.state.github_url or self.state.linear_project_url,
        )
        return gmail

    def refresh_linear_status(self) -> str:
        if not self.state.linear_project_id or self.ops.demo:
            return self.state.to_context_block()

        r = self.ops.run_action(
            "LINEAR_LIST_LINEAR_ISSUES",
            {"project_id": self.state.linear_project_id, "first": 50},
        )
        issues_raw = (
            _dig(r.data, "issues")
            or _dig(r.data, "data", "issues")
            or _dig(r.data, "data", "items")
            or _dig(r.data, "items")
            or []
        )
        if isinstance(issues_raw, dict):
            issues_raw = issues_raw.get("nodes", []) or issues_raw.get("items", [])
        if isinstance(issues_raw, list):
            updated: List[LinearIssueRef] = []
            for item in issues_raw:
                if not isinstance(item, dict):
                    continue
                st = _dig(item, "state", "name") or _dig(item, "state") or "unknown"
                if isinstance(st, dict):
                    st = st.get("name", "unknown")
                updated.append(
                    LinearIssueRef(
                        id=str(item.get("id", "")),
                        title=str(item.get("title", "")),
                        identifier=str(item.get("identifier", "")),
                        state=str(st),
                        turn=0,
                    )
                )
            if updated:
                meta = {i.id: (i.step_index, i.category) for i in self.state.linear_issues}
                for item in updated:
                    if item.id in meta:
                        item.step_index, item.category = meta[item.id]
                self.state.linear_issues = updated
        return self.state.to_context_block()

    def complete(
        self,
        idea: str,
        turns: int,
        plan: str,
        *,
        workdir: Optional[Path] = None,
        qa: Optional[QABundle] = None,
        build_complete: bool = True,
    ) -> Dict[str, Any]:
        team_id = self.secrets.linear_team_id.strip() or self.ops.resolve_linear_team_id()
        if build_complete and self.state.plan_issue_id and team_id:
            self._mark_issue_done(self.state.plan_issue_id, team_id)

        status_word = "complete" if build_complete else "stopped (incomplete)"
        self._post_project_update(
            turns,
            f"**Build {status_word}** after {turns} turn(s).\n\n{plan[:2000]}",
            health="onTrack" if build_complete else "atRisk",
        )
        if build_complete and self.state.linear_project_id and not self.ops.demo:
            self.ops.run_action(
                "LINEAR_UPDATE_LINEAR_PROJECT",
                {
                    "project_id": self.state.linear_project_id,
                    "description": f"Shipped by Creation.\n\n{idea}\n\nGitHub: {self.state.github_url}",
                },
            )

        done_body = self._compose_email(
            kind="complete" if build_complete else "turn",
            idea=idea,
            turn=turns,
            agent_ok=build_complete,
            agent_excerpt=plan[:2000],
            linear_summary=self.refresh_linear_status(),
        )
        subject_tag = "✅ Done" if build_complete else "⏸ Paused (incomplete)"
        gmail = self._notify(
            subject=f"[Creation] {subject_tag} — {self.brand.product_name or idea[:40]}",
            body=self._email_body(done_body),
            kind="complete",
        )
        self.outcomes["gmail_ok"] = self.outcomes["gmail_ok"] or bool(gmail.success)
        main_pushed = False
        # Only push straight to main for repos Creation created. For a repo we
        # attached to (reused), ship via a PR so existing work is never clobbered.
        if workdir and self.state.github_url and not self.reused_repo:
            main_pushed = push_workdir(
                workdir,
                self.state.github_url,
                f"creation ship after {turns} turns",
                branch="main",
            )
            if main_pushed:
                self.outcomes["github_pushed"] = True
                self._play("Complete source tree pushed to GitHub main", kind="github", url=self.state.github_url)
        finale = "Build complete · final email sent" if build_complete else "Build stopped · status email sent"
        self._play(finale, kind="complete", url=self.state.github_url)
        pr_url = ""
        if not main_pushed and (self.reused_repo or self.secrets.ship_mode == "pr") and self.state.github_owner and self.state.github_repo:
            pr_url = self._open_ship_pr(idea, turns, plan, workdir=workdir, qa_bundle=qa)
        if pr_url:
            self.outcomes["github_pushed"] = True
            self.outcomes["pr_url"] = pr_url

        return {
            "tracking": self.state.to_dict(),
            "final_gmail": gmail.to_dict() if hasattr(gmail, "to_dict") else asdict(gmail),
            "pr_url": pr_url,
            "outcomes": dict(self.outcomes),
        }

    def _open_ship_pr(
        self,
        idea: str,
        turns: int,
        plan: str,
        *,
        workdir: Optional[Path] = None,
        qa_bundle: Optional[QABundle] = None,
    ) -> str:
        owner, repo = self.state.github_owner, self.state.github_repo
        if not owner or not repo:
            return ""
        branch = f"creation/ship-{turns}"
        if workdir and self.state.github_url:
            push_feature_branch(workdir, self.state.github_url, branch, f"creation ship after {turns} turns")
        diff_stat = workdir_diff(workdir) if workdir else ""
        qa = qa_bundle or QABundle()
        body = generate_pr_body(
            self.secrets,
            idea=idea,
            brand=self.brand,
            turns=turns,
            plan=plan,
            qa_context=qa.to_context_block(),
            linear_url=self.state.linear_project_url,
            github_url=self.state.github_url,
            diff_stat=diff_stat,
        )
        title = f"Ship: {self.brand.product_name or idea[:60]}"
        ok, url = create_pull_request(owner, repo, branch, title, body)
        if ok and url:
            self._play(f"PR opened · {title}", kind="github", url=url)
        return url

    def sync_workdir_to_github(self, workdir: Path, turn: int, idea: str, *, composio_fallback: bool = False) -> None:
        """Write status locally; push full tree via git when possible, else Composio upserts all source files."""
        if not self.state.github_owner or not self.state.github_repo:
            return

        status = (
            f"# Creation build status\n\n"
            f"**Product:** {self.brand.product_name or idea}\n\n"
            f"**Tagline:** {self.brand.tagline}\n\n"
            f"**Turn:** {turn}\n\n"
            f"**Linear:** {self.state.linear_project_url}\n\n"
            f"**GitHub:** {self.state.github_url}\n\n"
            f"## Files\n\n" + "\n".join(f"- {f}" for f in self._file_list(workdir).split("\n") if f)
        )
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "CREATION_STATUS.md").write_text(status, encoding="utf-8")
        except OSError as e:
            logger.warning("could not write CREATION_STATUS.md: %s", e)

        if not composio_fallback:
            return

        owner, repo = self.state.github_owner, self.state.github_repo
        for rel in self._collect_sync_files(workdir):
            fp = workdir / rel
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")[:50000]
            except OSError:
                continue
            self.ops.github_upsert_file(owner, repo, rel, text, f"creation turn {turn}: {rel}")

    # ── internals ──

    def _ensure_linear_project(self, name: str, idea: str, team_id: str) -> None:
        existing_id = self.secrets.linear_project_id.strip()
        if self.secrets.linear_project_mode == "existing" and existing_id:
            self.state.linear_project_id = existing_id
            self.state.linear_project_name = self.secrets.linear_project_name.strip() or name
            self.state.linear_project_url = self.secrets.linear_project_url.strip()
            if not self.state.linear_project_url and not self.ops.demo:
                self._resolve_linear_project_url(existing_id)
            return
        self._create_linear_project(name, idea, team_id)

    def _create_linear_project(self, name: str, idea: str, team_id: str) -> None:
        if self.ops.demo:
            self.state.linear_project_id = "demo-project-id"
            self.state.linear_project_url = f"https://linear.app/project/demo-{_slugify(name)}"
            return
        r = self.ops.run_action(
            "LINEAR_CREATE_LINEAR_PROJECT",
            {"name": name[:255], "team_ids": [team_id], "description": idea[:255], "icon": "Rocket"},
        )
        pid = _dig(r.data, "id") or _dig(r.data, "project", "id") or _dig(r.data, "data", "id")
        if pid:
            self.state.linear_project_id = str(pid)
            self._resolve_linear_project_url(str(pid))

    def _create_plan_issues(self, plan: str, team_id: str, idea: str) -> None:
        steps = parse_plan_steps(plan)
        self._plan_steps = steps[:8]
        epic_title = self.brand.product_name or idea[:70]
        epic = self._create_issue(
            team_id,
            f"🚀 {epic_title[:90]}",
            f"Autonomous build tracked by Creation.\n\n{plan[:3000]}",
            project_id=self.state.linear_project_id,
        )
        if epic:
            epic.category = "epic"
            self.state.plan_issue_id = epic.id
            self.state.linear_issues.append(epic)

        for i, step in enumerate(self._plan_steps, 1):
            iss = self._create_issue(
                team_id,
                step[:100],
                step,
                project_id=self.state.linear_project_id,
                parent_id=epic.id if epic else "",
            )
            if iss:
                iss.step_index = i
                iss.category = "plan"
                iss.state = "todo"
                self.state.linear_issues.append(iss)
                self._set_issue_state(iss.id, team_id, "todo")

    def _create_issue(
        self,
        team_id: str,
        title: str,
        description: str,
        *,
        project_id: str = "",
        parent_id: str = "",
    ) -> Optional[LinearIssueRef]:
        if self.ops.demo:
            ref = LinearIssueRef(
                id=f"demo-{len(self.state.linear_issues)}",
                title=title,
                identifier=f"CIR-{len(self.state.linear_issues) + 1}",
            )
            return ref
        if not team_id:
            return None
        args: Dict[str, Any] = {"team_id": team_id, "title": title[:255], "description": description[:5000]}
        if project_id:
            args["project_id"] = project_id
        if parent_id:
            args["parent_id"] = parent_id
        r = self.ops.run_action("LINEAR_CREATE_LINEAR_ISSUE", args)
        iid = _dig(r.data, "id") or _dig(r.data, "issue", "id") or _dig(r.data, "data", "id")
        ident = _dig(r.data, "identifier") or _dig(r.data, "issue", "identifier")
        if not iid:
            return None
        return LinearIssueRef(id=str(iid), title=title, identifier=str(ident or ""))

    def _sync_linear_kanban(
        self,
        turn: int,
        idea: str,
        team_id: str,
        agent_summary: str,
        qa: QABundle,
        linear_ctx: str,
    ) -> str:
        if self.ops.demo or not team_id:
            return qa.to_context_block()

        board_summary = ""
        try:
            sync = generate_linear_board_sync(
                self.secrets,
                idea=idea,
                plan=self._plan,
                turn=turn,
                plan_steps=self._plan_steps,
                qa_context=qa.to_context_block(),
                agent_excerpt=agent_summary,
                linear_context=linear_ctx,
            )
            board_summary = sync.board_summary
            self._apply_step_states(team_id, sync.step_states)
            for spec in sync.new_issues[:12]:
                self._create_board_issue(team_id, spec)
        except Exception as e:
            logger.warning("Nebius Linear board sync failed: %s", e)

        self._create_qa_issues_from_report(team_id, qa)
        self.refresh_linear_status()
        self._play(
            f"Linear kanban updated · turn {turn}",
            kind="linear",
            url=self.state.linear_project_url,
        )
        return board_summary

    def _apply_step_states(self, team_id: str, step_states: List[Dict[str, Any]]) -> None:
        plan_issues = [i for i in self.state.linear_issues if i.category == "plan"]
        for item in step_states:
            if not isinstance(item, dict):
                continue
            idx = int(item.get("index") or 0)
            state = str(item.get("state") or "todo").lower().replace(" ", "_")
            issue = next((i for i in plan_issues if i.step_index == idx), None)
            if issue and issue.id:
                self._set_issue_state(issue.id, team_id, state)

    def _create_board_issue(self, team_id: str, spec: Dict[str, Any]) -> None:
        title = str(spec.get("title") or "").strip()[:255]
        if not title or self._issue_title_exists(title):
            return
        if title.lower().startswith("turn ") and ":" in title.lower():
            return
        desc = str(spec.get("description") or "")[:5000]
        category = str(spec.get("category") or "task")
        state = str(spec.get("state") or "todo").lower().replace(" ", "_")
        iss = self._create_issue(
            team_id,
            title,
            desc,
            project_id=self.state.linear_project_id,
        )
        if iss:
            iss.category = category
            self.state.linear_issues.append(iss)
            self._set_issue_state(iss.id, team_id, state)

    def _create_qa_issues_from_report(self, team_id: str, qa: QABundle) -> None:
        for fail in qa.tests.failures:
            title = f"Test: {fail.test_id}"[:255]
            if self._issue_title_exists(title):
                continue
            iss = self._create_issue(
                team_id,
                title,
                fail.message[:5000],
                project_id=self.state.linear_project_id,
            )
            if iss:
                iss.category = "test"
                self.state.linear_issues.append(iss)
                self._set_issue_state(iss.id, team_id, "todo")

        for finding in qa.browser.findings:
            if finding.severity == "warn" and finding.note.startswith("Console"):
                continue
            title = f"QA: {finding.url.split('/')[-1] or 'page'}"[:200]
            if self._issue_title_exists(title):
                continue
            iss = self._create_issue(
                team_id,
                title,
                f"**URL:** {finding.url}\n**Severity:** {finding.severity}\n\n{finding.note}",
                project_id=self.state.linear_project_id,
            )
            if iss:
                iss.category = "qa"
                self.state.linear_issues.append(iss)
                state = "in_progress" if finding.severity == "error" else "todo"
                self._set_issue_state(iss.id, team_id, state)

    def _issue_title_exists(self, title: str) -> bool:
        t = title.strip().lower()
        return any(i.title.strip().lower() == t for i in self.state.linear_issues)

    def _load_workflow_states(self, team_id: str) -> None:
        if self._state_name_to_id or self.ops.demo:
            return
        r = self.ops.run_action("LINEAR_LIST_LINEAR_STATES", {"team_id": team_id})
        states = (
            _dig(r.data, "states")
            or _dig(r.data, "workflowStates")
            or _dig(r.data, "data", "items")
            or _dig(r.data, "data", "states")
            or _dig(r.data, "data")
            or _dig(r.data, "items")
            or []
        )
        if isinstance(states, dict):
            states = states.get("nodes", []) or states.get("items", [])
        for st in states if isinstance(states, list) else []:
            if not isinstance(st, dict):
                continue
            name = str(st.get("name", "")).lower()
            sid = str(st.get("id", ""))
            if name and sid:
                self._state_name_to_id[name] = sid
                typ = str(st.get("type", "")).lower()
                if typ in ("completed", "done") or name in ("done", "completed", "complete"):
                    self._done_state_cache = sid

    def _set_issue_state(self, issue_id: str, team_id: str, state: str) -> None:
        if self.ops.demo or not issue_id:
            return
        self._load_workflow_states(team_id)
        aliases = {
            "todo": "todo",
            "backlog": "backlog",
            "in_progress": "in progress",
            "inprogress": "in progress",
            "started": "in progress",
            "done": "done",
            "completed": "done",
            "complete": "done",
        }
        key = aliases.get(state.lower().replace(" ", "_"), state.lower())
        state_id = self._state_name_to_id.get(key)
        if not state_id:
            return
        self.ops.run_action("LINEAR_UPDATE_ISSUE", {"issue_id": issue_id, "state_id": state_id})
        for iss in self.state.linear_issues:
            if iss.id == issue_id:
                iss.state = key

    def _mark_issue_done(self, issue_id: str, team_id: str) -> None:
        self._set_issue_state(issue_id, team_id, "done")

    def _resolve_done_state_id(self, team_id: str) -> Optional[str]:
        self._load_workflow_states(team_id)
        return self._done_state_cache

    def _post_project_update(self, turn: int, body: str, health: str = "onTrack") -> None:
        if not self.state.linear_project_id:
            return
        self.ops.run_action(
            "LINEAR_CREATE_PROJECT_UPDATE",
            {"project_id": self.state.linear_project_id, "body": body[:5000], "health": health},
        )

    def _resolve_linear_project_url(self, project_id: str) -> None:
        if self.ops.demo:
            return
        r = self.ops.run_action("LINEAR_GET_LINEAR_PROJECT", {"project_id": project_id})
        url = (
            _dig(r.data, "project", "url")
            or _dig(r.data, "data", "project", "url")
            or _dig(r.data, "url")
        )
        if url:
            self.state.linear_project_url = str(url)

    def _attach_repo(self, owner: str, repo: str, html_url: str = "") -> None:
        self.state.github_owner = owner
        self.state.github_repo = repo
        self.state.github_url = html_url or f"https://github.com/{owner}/{repo}"

    def _attach_from_repo_data(self, data: Dict[str, Any], fallback_owner: str, fallback_repo: str) -> None:
        data = data if isinstance(data, dict) else {}
        full = data.get("full_name") or _dig(data, "data", "full_name")
        html = data.get("html_url") or _dig(data, "data", "html_url")
        if full and "/" in str(full):
            owner, repo = str(full).split("/", 1)
        else:
            owner, repo = fallback_owner or "me", fallback_repo
        self._attach_repo(owner, repo, str(html or ""))

    def _ensure_github_repo(self, idea: str, project_id: str, *, repo_slug: str = "") -> None:
        owner = self.secrets.github_owner.strip()
        # Stable slug from the brand/product name (no random project suffix) so we
        # can detect — and reuse — an existing repo of the same name.
        base = _slugify(repo_slug or self.brand.repo_slug or idea, 30)
        repo = self.secrets.github_repo.strip() or base
        description = self.brand.tagline or idea[:350]

        if self.ops.demo:
            self._attach_repo(owner or "you", repo)
            return

        # If both owner+repo are pinned in config, trust the user's choice.
        if self.secrets.github_owner.strip() and self.secrets.github_repo.strip():
            self._attach_repo(owner, repo)
            self.reused_repo = True
            return

        # Resolve the authenticated owner when not configured.
        if not owner:
            owner = self.ops.resolve_github_owner()

        # Reuse an existing remote repo of this name rather than duplicating it.
        if owner:
            existing = self.ops.get_github_repo(owner, repo)
            if existing.success:
                self._attach_from_repo_data(existing.data, owner, repo)
                self.reused_repo = True
                logger.info("Reusing existing GitHub repo %s/%s", self.state.github_owner, self.state.github_repo)
                return

        r = self.ops.create_github_repo(repo, description, private=True)
        if not r.success:
            # A name collision (repo already exists) can surface as a failure —
            # try once more to reuse it before giving up.
            if owner:
                existing = self.ops.get_github_repo(owner, repo)
                if existing.success:
                    self._attach_from_repo_data(existing.data, owner, repo)
                    self.reused_repo = True
                    return
            logger.warning("GitHub repo create via Composio failed: %s — agent can still use gh repo create", r.detail)
            self.state.github_repo = repo
            self.state.github_owner = owner or "local"
            self.state.github_url = ""
            return
        self._attach_from_repo_data(r.data, owner, repo)

    def _notify(self, subject: str, body: str, kind: str, turn: int = 0) -> OpsResult:
        to = self.secrets.gmail_notify_to.strip() or "me"
        r = self.ops.send_gmail(subject, body, to)
        return r

    def _email_body(self, markdown: str) -> str:
        return markdown

    def _compose_email(
        self,
        *,
        kind: str,
        idea: str,
        turn: int,
        agent_ok: bool,
        agent_excerpt: str,
        linear_summary: str,
        qa: Optional[QABundle] = None,
        board_summary: str = "",
        workdir: Optional[Path] = None,
        git_pushed: bool = False,
    ) -> str:
        qa_bundle = qa or QABundle()
        diff_stat = workdir_diff(workdir) if workdir else ""
        iteration_note = self._iteration_note(
            turn=turn,
            agent_ok=agent_ok,
            agent_excerpt=agent_excerpt,
            qa=qa_bundle,
            board_summary=board_summary,
            diff_stat=diff_stat,
            git_pushed=git_pushed,
        )
        if self.ops.demo:
            return iteration_note + "\n\n" + self._links_block()

        try:
            body = generate_progress_email(
                self.secrets,
                kind=kind,
                idea=idea,
                brand=self.brand,
                turn=turn,
                agent_ok=agent_ok,
                agent_excerpt=agent_excerpt,
                linear_summary=linear_summary,
                github_url=self.state.github_url,
                linear_url=self.state.linear_project_url,
                plan_excerpt=self._plan,
                qa_context=qa_bundle.to_context_block(),
                diff_stat=diff_stat[:3000],
                iteration_note=iteration_note,
            )
            if body and not self._email_looks_generic(body, iteration_note):
                return body
        except Exception as e:
            logger.warning("progress email generation failed: %s", e)

        return iteration_note + "\n\n" + self._links_block()

    def _iteration_note(
        self,
        *,
        turn: int,
        agent_ok: bool,
        agent_excerpt: str,
        qa: QABundle,
        board_summary: str,
        diff_stat: str,
        git_pushed: bool,
    ) -> str:
        title = self.brand.product_name or "Creation build"
        lines = [f"Creation — Turn {turn}: {title}", ""]

        if agent_excerpt.strip():
            lines.append("What happened this iteration:")
            for line in agent_excerpt.strip().splitlines()[-10:]:
                line = line.strip()
                if line:
                    lines.append(f"• {line[:240]}")
            lines.append("")

        if qa.tests.ran:
            lines.append(
                f"Tests: {qa.tests.passed} passed, {qa.tests.failed} failed"
                + (f" — {qa.tests.failures[0].test_id}" if qa.tests.failures else "")
            )
        if qa.browser.findings:
            lines.append(f"Browser QA: {len(qa.browser.findings)} finding(s)")
            for f in qa.browser.findings[:3]:
                lines.append(f"• {f.note[:180]}")
        lines.append(f"Agent status: {'OK' if agent_ok else 'errors — review needed'}")
        lines.append("")

        if board_summary.strip():
            lines.append("Linear board:")
            lines.append(board_summary.strip()[:800])
            lines.append("")

        if diff_stat.strip():
            stat_only = diff_stat.split("\n\n")[0].strip()
            if stat_only:
                lines.append("Code changes pushed:")
                for row in stat_only.splitlines()[:12]:
                    lines.append(f"  {row}")
                lines.append("")

        lines.append(
            "GitHub sync: full workdir commit via git push"
            if git_pushed
            else "GitHub sync: all source files uploaded via Composio (git push unavailable)"
        )
        return "\n".join(lines).strip()

    @staticmethod
    def _email_looks_generic(body: str, iteration_note: str) -> bool:
        lowered = body.lower()
        generic_phrases = (
            "progress update",
            "here is an update",
            "this is an update",
            "automated update",
            "no significant changes",
        )
        if any(p in lowered for p in generic_phrases):
            return True
        # Require at least one concrete line from the iteration note to appear in the LLM body
        for line in iteration_note.splitlines():
            chunk = line.strip().lstrip("• ").strip()
            if len(chunk) > 24 and chunk in body:
                return False
        return len(body.strip()) < 80

    @staticmethod
    def _commit_message(turn: int, agent_summary: str) -> str:
        base = f"creation turn {turn}"
        if not agent_summary.strip():
            return base
        headline = agent_summary.strip().splitlines()[0].strip()
        headline = re.sub(r"\s+", " ", headline)[:72]
        if headline:
            return f"{base}: {headline}"
        return base

    def _links_block(self) -> str:
        parts = []
        if self.state.linear_project_url:
            parts.append(f"Linear project: {self.state.linear_project_url}")
        if self.state.github_url:
            parts.append(f"GitHub repo: {self.state.github_url}")
        return "\n".join(parts) if parts else "(links will appear once Composio connects Linear/GitHub)"

    def _collect_sync_files(self, workdir: Path) -> List[str]:
        if not workdir.exists():
            return []
        code: List[str] = []
        docs: List[str] = []
        for fp in sorted(workdir.rglob("*")):
            if not fp.is_file():
                continue
            rel = fp.relative_to(workdir).as_posix()
            if any(part in _SKIP_SYNC_DIRS for part in fp.relative_to(workdir).parts):
                continue
            suffix = fp.suffix.lower()
            is_doc = suffix == ".md" or fp.name in {"README.md", "CREATION_STATUS.md", "BUILD_PLAN.md", "RESEARCH.md"}
            allowed = suffix in _SYNC_SUFFIXES or fp.name in _EXTRA_SYNC_NAMES
            if not allowed:
                continue
            (docs if is_doc else code).append(rel)
        out = code + docs
        return out[:_MAX_COMPOSIO_SYNC_FILES]

    def _file_list(self, workdir: Path) -> str:
        if not workdir.exists():
            return "(empty)"
        files = sorted(f.relative_to(workdir).as_posix() for f in workdir.rglob("*") if f.is_file())[:30]
        return "\n".join(files) if files else "(no files yet)"
