"""Forge — Creation planning brain (replaces external orchestration LLMs)."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from creation.account.store import AccountStore
from creation.config import UserSecrets

logger = logging.getLogger(__name__)

PLAN_SYSTEM = """You are the lead planner for an autonomous agent company building software around the clock.
You receive a hard turn budget — the build MUST reach a shippable MVP within that many loop turns.
Output a numbered build plan (5-8 steps) sized to the turn budget:
- ≤5 turns: ruthlessly minimal MVP (core path only, defer polish)
- 6-15 turns: focused MVP with tests and one differentiator
- 16+ turns: fuller MVP with QA-ready polish
Be specific. Branding/naming is handled separately — focus on engineering steps only."""


EDIT_PLAN_SYSTEM = """You plan surgical edits to an EXISTING codebase — not a greenfield MVP.
The user gave a specific change request. Output a numbered plan (3-6 steps) sized to the turn budget:
- Understand affected files and conventions first (read before write)
- Make the smallest change set that fully delivers the request
- Extend or fix tests for touched areas only
- Update README/docs only where the change affects usage
Do NOT plan scaffolding, rebranding, or unrelated features. Be specific about files/areas to touch."""


BRAND_SYSTEM = """You name and brand new software products for an autonomous factory.
Output JSON only (no markdown fences) with exactly these keys:
- product_name: short memorable product name (2-4 words, not a literal feature list)
- repo_slug: GitHub repo name, lowercase kebab-case, max 18 chars, catchy not descriptive
- tagline: one-line value prop under 80 chars
- linear_project_name: clean project title for Linear (max 48 chars)

Good repo_slug examples: "jl", "mdcraft", "neural-kit", "shipcli"
Bad repo_slug examples: "cli-that-connects-to-the-creation-frontend", "tool-for-converting-files"

Pick names that feel like real startup products — not sentence fragments from the idea."""


EMAIL_SYSTEM = """You write concise progress emails for an autonomous software factory owner.
The user message includes an iteration_note with concrete facts from this turn — use those specifics; do NOT replace them with generic template language.

Use plain text with short sections and bullet points. Include:
- What happened this turn (concrete files, tests, agent actions — from iteration_note and agent excerpt)
- Current build health (on track / blocked) with evidence
- Linear tracker snapshot if provided
- What to focus on next (one sentence, specific)
- Full URLs for Linear and GitHub at the end

Never write filler like "here is your progress update" or "no significant changes" unless true.
Keep under 400 words. Friendly, specific, no hype."""

LINEAR_BOARD_SYSTEM = """You manage a Linear kanban board for an autonomous software factory.
Output JSON only (no markdown fences):
{
  "active_step_index": 1,
  "step_states": [{"index": 1, "state": "todo"|"in_progress"|"done"}],
  "new_issues": [{"title": "short issue title", "description": "details", "category": "test|qa|bug|task", "state": "todo"|"in_progress"}],
  "board_summary": "2-4 sentences: what is in progress, what passed/failed in tests, browser QA highlights"
}

Rules:
- NEVER create generic issues like "Turn 27: errors". Use concrete titles from test failures and browser findings.
- Plan-step issues map to step_states by index (1-based).
- Mark exactly one plan step in_progress when work remains; mark done only when evidence supports it.
- new_issues: one per failing test (title starts with "Test:") and one per browser QA problem (title starts with "QA:").
- board_summary is shown on the Linear project updates feed."""


FOLLOWUP_SYSTEM = """You orchestrate a multi-turn autonomous software build with a fixed turn budget.
You know the current turn, max turns, and turns remaining — plan accordingly.

Signals (in order): turn budget pressure, Linear kanban plan-step states, test run results, browser QA review, workdir files, coding agent output.
You have browser QA context — treat UI/console errors as blocking until fixed.

When ALL plan-step issues are Done AND tests pass AND browser QA has no error-severity findings AND the MVP is shippable, respond with exactly:
DONE

If turns remaining ≤ 2 and MVP is close, prefer DONE over perfection when core flows work.
If turns remaining ≤ 1, ship the best MVP possible — no new scope.

Otherwise respond with exactly one line starting with:
FOLLOW_UP: <specific instruction — cite failing tests, QA URLs, or open plan steps>

No other prose. Be concrete — file names, test names, URLs, fixes."""


def _client(secrets: UserSecrets):
    from openai import OpenAI

    key = secrets.forge_api_key.strip() or secrets.account_token.strip()
    if not key:
        key = AccountStore().ensure_local_account().api_key
    base = secrets.forge_base_url.strip() or os.environ.get("CREATION_FORGE_URL", "http://127.0.0.1:8787/api/forge/v1")
    return OpenAI(api_key=key, base_url=base)


@dataclass
class ProductBrand:
    product_name: str = ""
    repo_slug: str = ""
    tagline: str = ""
    linear_project_name: str = ""

    @classmethod
    def from_idea(cls, idea: str) -> "ProductBrand":
        slug = _fallback_slug(idea)
        name = idea[:48].strip() or "Creation build"
        return cls(product_name=name, repo_slug=slug, tagline=idea[:80], linear_project_name=name[:48])

    def to_context_block(self) -> str:
        lines = ["## Product brand (Nebius)"]
        if self.product_name:
            lines.append(f"- **Product name:** {self.product_name}")
        if self.tagline:
            lines.append(f"- **Tagline:** {self.tagline}")
        if self.repo_slug:
            lines.append(f"- **GitHub repo slug:** {self.repo_slug}")
        lines.append("- Use this brand in README, CLI name, package metadata, and user-facing copy.")
        return "\n".join(lines)


def _fallback_slug(text: str, max_len: int = 18) -> str:
    s = re.sub(r"[^a-z0-9-]", "-", text.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len].rstrip("-") or "creation-app")


def _parse_json_blob(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                obj = json.loads(m.group())
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def generate_brand(secrets: UserSecrets, idea: str, plan: str, context_blocks: list[str]) -> ProductBrand:
    client = _client(secrets)
    merged = "\n\n".join(context_blocks)[:8000]
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": BRAND_SYSTEM},
            {"role": "user", "content": f"Idea: {idea}\n\nPlan:\n{plan[:2000]}\n\nResearch:\n{merged}"},
        ],
        max_tokens=300,
    )
    raw = _parse_json_blob((resp.choices[0].message.content or "").strip())
    fallback = ProductBrand.from_idea(idea)
    slug = str(raw.get("repo_slug") or fallback.repo_slug)
    slug = _fallback_slug(slug, 18)
    return ProductBrand(
        product_name=str(raw.get("product_name") or fallback.product_name)[:64],
        repo_slug=slug,
        tagline=str(raw.get("tagline") or fallback.tagline)[:120],
        linear_project_name=str(raw.get("linear_project_name") or raw.get("product_name") or fallback.linear_project_name)[
            :48
        ],
    )


def generate_progress_email(
    secrets: UserSecrets,
    *,
    kind: str,
    idea: str,
    brand: ProductBrand,
    turn: int = 0,
    agent_ok: bool = True,
    agent_excerpt: str = "",
    linear_summary: str = "",
    github_url: str = "",
    linear_url: str = "",
    plan_excerpt: str = "",
    qa_context: str = "",
    diff_stat: str = "",
    iteration_note: str = "",
) -> str:
    client = _client(secrets)
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": EMAIL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Email type: {kind}\n"
                    f"Product: {brand.product_name}\nTagline: {brand.tagline}\n"
                    f"Idea: {idea}\nTurn: {turn}\nAgent OK: {agent_ok}\n\n"
                    f"Iteration note (use these facts):\n{iteration_note[:2500]}\n\n"
                    f"Plan excerpt:\n{plan_excerpt[:1200]}\n\n"
                    f"Linear tracker:\n{linear_summary[:2000]}\n\n"
                    f"QA:\n{qa_context[:1500]}\n\n"
                    f"Git diff stat:\n{diff_stat[:1500]}\n\n"
                    f"Agent output excerpt:\n{agent_excerpt[-2500:]}\n\n"
                    f"Linear URL: {linear_url}\nGitHub URL: {github_url}"
                ),
            },
        ],
        max_tokens=650,
    )
    body = (resp.choices[0].message.content or "").strip()
    if body:
        return body
    return _fallback_email(
        kind,
        brand,
        idea,
        turn,
        agent_ok,
        linear_url,
        github_url,
        iteration_note=iteration_note,
        agent_excerpt=agent_excerpt,
    )


def _fallback_email(
    kind: str,
    brand: ProductBrand,
    idea: str,
    turn: int,
    agent_ok: bool,
    linear_url: str,
    github_url: str,
    *,
    iteration_note: str = "",
    agent_excerpt: str = "",
) -> str:
    if iteration_note.strip():
        return iteration_note.strip()
    title = brand.product_name or idea[:60]
    lines = [f"Creation — {kind}", f"Product: {title}", ""]
    if brand.tagline:
        lines.append(f"Tagline: {brand.tagline}")
    if turn:
        lines.append(f"Turn {turn}: {'success' if agent_ok else 'errors'}")
    if agent_excerpt.strip():
        lines.append("")
        lines.append(agent_excerpt.strip()[:1200])
    lines.append("")
    if linear_url:
        lines.append(f"Linear: {linear_url}")
    if github_url:
        lines.append(f"GitHub: {github_url}")
    return "\n".join(lines)


TURN_PLAN_SYSTEM = """You route each autonomous build turn for an agent company. Tavily + Firecrawl research already ran once at kickoff.
You always know the turn budget — plan to finish inside max_turns.

Output JSON only:
{
  "done": false,
  "refresh_research": false,
  "run_agent": true,
  "run_qa": true,
  "follow_up": "one concrete coding instruction when run_agent is true",
  "subtasks": [],
  "reason": "short UI status (8-15 words)"
}

Rules:
- turns_remaining ≤ 3: cut scope, fix blockers only, prioritize ship.
- turns_remaining ≤ 1: done=true if MVP works at all; else one minimal fix follow_up.
- refresh_research: true ONLY when blocked on external APIs, new libraries, or a major product pivot. Default false.
- run_qa: true when code changed or tests might fail; false only for rare metadata-only turns with no code edits expected.
- run_agent: false only if done is true.
- done: true when Linear plan steps are done, tests pass, browser QA clean, MVP shippable.
- follow_up must cite specific files, tests, or features — never 'continue building'.
- subtasks: leave EMPTY [] by default. Only when subagents are allowed (the user message states a subagent budget > 0) AND this turn has genuinely independent, parallelizable work, return 2 or more concrete instructions — one per concurrent subagent. Each subtask MUST own a disjoint slice of the codebase (different files/dirs/layers) so the agents never edit the same files. Cap the list at the stated budget. Prefer subtasks early/mid-build for breadth (e.g. separate frontend, backend/API, tests/CI, docs); avoid them in the final ship turns. When you return subtasks, still set a short follow_up summarizing the combined goal."""


@dataclass
class TurnPlan:
    done: bool = False
    refresh_research: bool = False
    run_agent: bool = True
    run_qa: bool = True
    follow_up: str = ""
    subtasks: List[str] = field(default_factory=list)
    reason: str = ""

    @classmethod
    def default_continue(cls, turn: int) -> "TurnPlan":
        return cls(
            follow_up=f"Continue build — address open Linear issues and failing tests (turn {turn}).",
            reason="Default build turn",
        )


def generate_turn_plan(
    secrets: UserSecrets,
    *,
    idea: str,
    plan: str,
    turn: int,
    max_turns: int = 200,
    linear_context: str,
    workdir_summary: str,
    qa_context: str = "",
    last_follow_up: str = "",
    max_subagents: int = 0,
) -> TurnPlan:
    client = _client(secrets)
    remaining = max(max_turns - turn, 0)
    if max_subagents and max_subagents > 1:
        subagent_note = (
            f"Subagent budget: up to {max_subagents} concurrent subagents this turn. "
            "Use 'subtasks' to fan out when the work is genuinely parallelizable; otherwise leave it []."
        )
    else:
        subagent_note = "Subagent budget: 0 — always return subtasks: []."
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": TURN_PLAN_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Turn {turn} of {max_turns} ({remaining} remaining)\nIdea: {idea}\n\nPlan:\n{plan[:2500]}\n\n"
                    f"{subagent_note}\n\n"
                    f"Last follow-up: {last_follow_up[:800]}\n\n"
                    f"Linear:\n{linear_context[:3500]}\n\n"
                    f"Workdir:\n{workdir_summary[:2500]}\n\n"
                    f"Last QA:\n{qa_context[:1500]}"
                ),
            },
        ],
        max_tokens=550,
    )
    raw = _parse_json_blob((resp.choices[0].message.content or "").strip())
    cap = max(max_subagents, 0)
    raw_subtasks = raw.get("subtasks") if isinstance(raw.get("subtasks"), list) else []
    subtasks = [str(s).strip() for s in raw_subtasks if str(s).strip()][:cap] if cap > 1 else []
    return TurnPlan(
        done=bool(raw.get("done")),
        refresh_research=bool(raw.get("refresh_research")),
        run_agent=bool(raw.get("run_agent", True)),
        run_qa=bool(raw.get("run_qa", True)),
        follow_up=str(raw.get("follow_up") or "").strip(),
        subtasks=subtasks,
        reason=str(raw.get("reason") or "Routing turn")[:120],
    )


def generate_plan(secrets: UserSecrets, idea: str, context_blocks: list[str], *, max_turns: int = 200) -> str:
    merged = "\n\n".join(context_blocks)[:14000]
    if secrets.forge_offline:
        from creation.services.forge.engine import heuristic_plan

        return heuristic_plan(idea, max_turns)
    try:
        client = _client(secrets)
        resp = client.chat.completions.create(
            model=secrets.forge_model or "creation-forge-v1",
            messages=[
                {"role": "system", "content": PLAN_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Turn budget: {max_turns} loop turns total (plan must fit this budget).\n"
                        f"Idea: {idea}\n\nResearch:\n{merged}"
                    ),
                },
            ],
            max_tokens=900,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("Forge plan failed: %s", exc)
    from creation.services.forge.engine import heuristic_plan

    return heuristic_plan(idea, max_turns)


def generate_edit_plan(
    secrets: UserSecrets, task: str, context_blocks: list[str], *, max_turns: int = 50
) -> str:
    merged = "\n\n".join(context_blocks)[:14000]
    if secrets.forge_offline:
        from creation.services.forge.engine import heuristic_plan

        return heuristic_plan(task, max_turns, edit=True)
    try:
        client = _client(secrets)
        resp = client.chat.completions.create(
            model=secrets.forge_model or "creation-forge-v1",
            messages=[
                {"role": "system", "content": EDIT_PLAN_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Turn budget: {max_turns} loop turns total.\n"
                        f"Change request: {task}\n\nRepo context:\n{merged}"
                    ),
                },
            ],
            max_tokens=700,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("Forge edit plan failed: %s", exc)
    from creation.services.forge.engine import heuristic_plan

    return heuristic_plan(task, max_turns, edit=True)


@dataclass
class LinearBoardSync:
    active_step_index: int = 1
    step_states: List[Dict[str, Any]] = field(default_factory=list)
    new_issues: List[Dict[str, Any]] = field(default_factory=list)
    board_summary: str = ""


def generate_linear_board_sync(
    secrets: UserSecrets,
    *,
    idea: str,
    plan: str,
    turn: int,
    plan_steps: List[str],
    qa_context: str,
    agent_excerpt: str,
    linear_context: str,
) -> LinearBoardSync:
    client = _client(secrets)
    steps_txt = "\n".join(f"{i}. {s}" for i, s in enumerate(plan_steps[:8], 1))
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": LINEAR_BOARD_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Turn {turn}\nIdea: {idea}\n\nPlan steps:\n{steps_txt}\n\n"
                    f"QA (tests + browser):\n{qa_context[:5000]}\n\n"
                    f"Agent excerpt:\n{agent_excerpt[-2500:]}\n\n"
                    f"Current Linear board:\n{linear_context[:4000]}"
                ),
            },
        ],
        max_tokens=700,
    )
    raw = _parse_json_blob((resp.choices[0].message.content or "").strip())
    return LinearBoardSync(
        active_step_index=int(raw.get("active_step_index") or 1),
        step_states=list(raw.get("step_states") or []),
        new_issues=list(raw.get("new_issues") or []),
        board_summary=str(raw.get("board_summary") or "")[:2000],
    )


def generate_follow_up(
    secrets: UserSecrets,
    *,
    idea: str,
    plan: str,
    turn: int,
    max_turns: int = 200,
    compressed_context: str,
    workdir_summary: str,
    agent_output: str,
    project_tracking: str = "",
    qa_context: str = "",
) -> Tuple[str, bool]:
    """Return (follow_up_prompt, is_done)."""
    client = _client(secrets)
    remaining = max(max_turns - turn, 0)
    tracking_block = f"\n\nLinear / GitHub tracking:\n{project_tracking[:6000]}\n" if project_tracking else ""
    qa_block = f"\n\nTests + browser QA:\n{qa_context[:4000]}\n" if qa_context else ""
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": FOLLOWUP_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Turn {turn} of {max_turns} ({remaining} remaining)\nIdea: {idea}\n\nPlan:\n{plan}\n\n"
                    f"Compressed context:\n{compressed_context[:8000]}\n\n"
                    f"Workdir:\n{workdir_summary[:6000]}\n\n"
                    f"Last agent output:\n{agent_output[-5000:]}"
                    f"{qa_block}"
                    f"{tracking_block}"
                ),
            },
        ],
        max_tokens=500,
    )
    text = (resp.choices[0].message.content or "").strip()
    upper = text.upper()
    if upper.startswith("DONE") or upper == "DONE":
        return "", True
    if "FOLLOW_UP:" in text.upper():
        idx = text.upper().index("FOLLOW_UP:")
        return text[idx + len("FOLLOW_UP:") :].strip(), False
    return text.strip(), False


PR_BODY_SYSTEM = """Write a GitHub pull request description for an autonomous factory build.
Include: summary, what changed this build, test results, Linear link, browser QA notes, next steps for reviewers.
Markdown format, under 500 words."""


def generate_pr_body(
    secrets: UserSecrets,
    *,
    idea: str,
    brand: ProductBrand,
    turns: int,
    plan: str,
    qa_context: str,
    linear_url: str,
    github_url: str,
    diff_stat: str = "",
) -> str:
    if not secrets.forge_api_key.strip():
        return _fallback_pr_body(idea, brand, turns, plan, qa_context, linear_url, github_url, diff_stat)
    client = _client(secrets)
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": PR_BODY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Product: {brand.product_name}\nIdea: {idea}\nTurns: {turns}\n\n"
                    f"Plan:\n{plan[:2000]}\n\nQA:\n{qa_context[:2000]}\n\n"
                    f"Linear: {linear_url}\nGitHub: {github_url}\n\nDiff:\n{diff_stat[:3000]}"
                ),
            },
        ],
        max_tokens=700,
    )
    return (resp.choices[0].message.content or "").strip() or _fallback_pr_body(
        idea, brand, turns, plan, qa_context, linear_url, github_url, diff_stat
    )


def _fallback_pr_body(
    idea: str,
    brand: ProductBrand,
    turns: int,
    plan: str,
    qa_context: str,
    linear_url: str,
    github_url: str,
    diff_stat: str,
) -> str:
    lines = [
        f"## {brand.product_name or 'Creation build'}",
        "",
        idea,
        "",
        f"Built in **{turns}** autonomous turns.",
        "",
        "### Plan",
        plan[:1500],
        "",
        "### QA",
        qa_context[:1000] or "See CI / local tests.",
        "",
    ]
    if diff_stat:
        lines.extend(["### Diff stat", "```", diff_stat[:800], "```", ""])
    if linear_url:
        lines.append(f"**Linear:** {linear_url}")
    if github_url:
        lines.append(f"**Repo:** {github_url}")
    lines.append("\n---\n*Opened by Creation.*")
    return "\n".join(lines)


PRODUCT_MD_SYSTEM = """Write a PRODUCT.md one-pager for a newly built software product.
Sections: Overview, Target user, Core features, Quick start, Roadmap (3 bullets). Under 400 words. Markdown."""


def generate_product_md(secrets: UserSecrets, idea: str, plan: str, brand: ProductBrand) -> str:
    if not secrets.forge_api_key.strip():
        return f"# {brand.product_name or 'Product'}\n\n{brand.tagline or idea}\n\n## Plan\n{plan[:2000]}"
    client = _client(secrets)
    resp = client.chat.completions.create(
        model=secrets.forge_model,
        messages=[
            {"role": "system", "content": PRODUCT_MD_SYSTEM},
            {
                "role": "user",
                "content": f"Name: {brand.product_name}\nTagline: {brand.tagline}\nIdea: {idea}\n\nPlan:\n{plan[:2500]}",
            },
        ],
        max_tokens=600,
    )
    return (resp.choices[0].message.content or "").strip() or f"# {brand.product_name}\n\n{idea}"
