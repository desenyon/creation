"""Creation orchestrator — smart routed multi-turn build loop."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from creation.agents.runner import CodingAgentRunner, available_agents
from creation.agents.registry import normalize_agent
from creation.agents.usage import (
    detect_rate_limit,
    mark_exhausted,
    record_turn,
    resolve_agent_for_turn,
    should_skip_parallel_secondary,
)
from creation.config import UserSecrets, get_settings
from creation.events import publish
from creation.integrations.composio_ops import ComposioOps
from creation.integrations.marketing import (
    MarketingResult,
    build_launch_email_html,
    build_launch_social_post,
    launch_marketing,
)
from creation.integrations.project_tracker import ProjectTracker, TrackState
from creation.manual_takeover import (
    add_message,
    drain_for_turn,
    steering_summary,
    to_context_block as manual_takeover_block,
)
from creation.inbound import InboundPoller
from creation.preflight import (
    build_needs_input_email,
    clarifying_questions,
    missing_integrations,
    needs_input,
)
from creation.memory import build_memory_bridge, compress_with_memory_stack, provider_label
from creation.nebius_client import (
    ProductBrand,
    TurnPlan,
    generate_brand,
    generate_edit_plan,
    generate_plan,
    generate_product_md,
    generate_turn_plan,
)
from creation.templates import apply_template
from creation.webhooks import fire_webhook
from creation.integrations.git_sync import (
    ensure_working_branch,
    has_commits,
    is_git_repo,
    resolve_github_from_workdir,
    workdir_diff,
)
from creation.research.firecrawl import FirecrawlResearch
from creation.research.tavily import TavilyBundle, TavilyResearch
from creation.review.qa import QABundle, run_qa_suite
from creation.skills import load_skill_blocks, record_turn_lesson, skills_status
from creation.ship_receipt import build_ship_receipt
from creation.sponsors import build_sponsor_integrations
from creation.store import Run, append_agent_log, get_project, update_project, update_run
from creation.validate import RunValidationError, validate_live_run
from creation.workdir import has_existing_sources, workdir_summary

logger = logging.getLogger(__name__)

SAFETY_MAX_TURNS = 200


def resolve_max_turns(secrets: UserSecrets, project, override: int | None = None) -> int:
    raw = override
    if raw is None:
        raw = getattr(project, "max_turn_budget", None)
    if raw is None:
        raw = secrets.max_turn_budget
    return min(SAFETY_MAX_TURNS, max(int(raw or 1), 1))

PIPELINE = [
    ("lens", "Lens", "Web research (once)"),
    ("scrape", "Lens", "Deep scrape (once)"),
    ("relay", "Relay", "Connect ship targets"),
    ("plan", "Forge", "Build plan"),
    ("brand", "Forge", "Product name & repo"),
    ("ops", "Relay", "Ship notification"),
]

SETUP_PHASES = {"lens", "scrape", "relay", "plan", "brand", "relay-setup", "tavily", "firecrawl", "composio", "composio-setup"}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_best_idea(tavily: TavilyBundle, seed: str) -> str:
    if seed.strip():
        return seed.strip()
    if tavily.answer:
        return tavily.answer.split(".")[0][:200]
    if tavily.hits:
        return tavily.hits[0].title
    return "Local-first developer automation tool"


def _integration_block(tracking: TrackState) -> str:
    lines = ["## GitHub & Composio (sponsor stack)"]
    if tracking.github_url:
        lines.append(
            f"- **GitHub repo:** {tracking.github_url}\n"
            "  - Commit and push all code each turn (`git add -A && commit && push`)."
        )
    if tracking.linear_project_url:
        lines.append(f"- **Linear project:** {tracking.linear_project_url}")
    return "\n".join(lines)


def _brand_block(brand: ProductBrand) -> str:
    if not brand.product_name and not brand.repo_slug:
        return ""
    return f"""## Brand (Nebius)
- **Product:** {brand.product_name}
- **Tagline:** {brand.tagline}
- Use in README, CLI, and user-facing copy.
"""


def _initial_agent_prompt(
    idea: str,
    plan: str,
    compressed: str,
    tracking: TrackState,
    brand: ProductBrand,
    existing_repo: bool = False,
) -> str:
    if existing_repo:
        instructions = """## Instructions
- You are working INSIDE AN EXISTING CODEBASE at the project root — this is not a greenfield build.
- Read the current files and match the project's existing structure, stack, and conventions first.
- Modify the codebase in place to deliver the task above. Do NOT scaffold a new project or overwrite unrelated files.
- Add or extend tests and update the README where it makes sense.
- Push all changed source code to GitHub — not just markdown.
- Nebius routes later turns — research will not repeat unless explicitly refreshed.

Make the change now."""
    else:
        instructions = """## Instructions
- Scaffold MVP. Include README + tests.
- Push all source code to GitHub — not just markdown.
- Nebius routes later turns — research will not repeat unless explicitly refreshed.

Build now."""
    heading = "task / change request" if existing_repo else "Product idea"
    return f"""# Creation — build turn 1

## {heading}
{idea}

{_brand_block(brand)}

## Build plan
{plan}

## Context (compressed)
{compressed}

{_integration_block(tracking)}

{instructions}
"""


def _followup_agent_prompt(
    turn: int,
    follow_up: str,
    compressed: str,
    tracking: TrackState,
    brand: ProductBrand,
    existing_repo: bool = False,
) -> str:
    deploy_note = "Do not add deployment plumbing unless the repo already has it and the task explicitly asks for it."
    return f"""# Creation — build turn {turn}

## Task
{follow_up}

{_brand_block(brand)}

## Context (this turn only — research from kickoff omitted)
{compressed}

{_integration_block(tracking)}

Commit and push all code files when done. Do not restart from scratch.
{deploy_note}
"""


def _compress_blocks(
    *,
    turn: int,
    query: str,
    research_blocks: List[str],
    turn_blocks: List[str],
    plan: str,
    brand: ProductBrand,
    tracking: TrackState,
    follow_up: str,
    include_research: bool,
    budget: float,
    mem0_block: str = "",
    mem0_count: int = 0,
) -> Tuple[str, Any, Dict[str, Any]]:
    core = [
        f"## Plan\n{plan}",
        brand.to_context_block(),
        tracking.to_context_block(),
    ]
    if turn > 1 and follow_up:
        core.append(f"## Current task\n{follow_up}")
    blocks = (research_blocks if include_research else []) + core + turn_blocks[-8:]
    compressed, mem, stack = compress_with_memory_stack(
        blocks,
        query,
        budget,
        mem0_block,
        mem0_count=mem0_count,
    )
    return compressed, mem, stack


class RunContext:
    def __init__(
        self,
        run: Run,
        phases: List[Dict[str, Any]],
        on_event: Callable[[Dict[str, Any]], None] | None = None,
    ):
        self.run = run
        self.phases = phases
        self.agent_log = ""
        self._on_event = on_event

    def emit(self, event: Dict[str, Any]) -> None:
        event.setdefault("ts", _ts())
        publish(self.run.id, event)
        if self._on_event:
            self._on_event(event)

    def start_phase(self, phase_id: str, tool: str, detail: str, *, stage: str = "loop") -> None:
        entry = {
            "phase": phase_id,
            "tool": tool,
            "detail": detail,
            "status": "running",
            "ts": _ts(),
            "stage": stage,
        }
        self.phases.append(entry)
        update_run(self.run.id, status="running", current_phase=phase_id, phases=self.phases)
        self.emit(
            {
                "type": "phase",
                "phase": phase_id,
                "tool": tool,
                "status": "running",
                "detail": detail,
                "stage": stage,
            }
        )

    def finish_phase(self, phase_id: str, detail: str, **extra: Any) -> None:
        for p in reversed(self.phases):
            if p["phase"] == phase_id and p["status"] == "running":
                p["status"] = "done"
                p["detail"] = detail
                p.update(extra)
                break
        update_run(self.run.id, phases=self.phases)
        stage = extra.get("stage", "loop")
        self.emit(
            {
                "type": "phase",
                "phase": phase_id,
                "status": "done",
                "detail": detail,
                "stage": stage,
                **{k: v for k, v in extra.items() if k != "stage"},
            }
        )

    def agent_line(self, line: str) -> None:
        self.agent_log += line + "\n"
        append_agent_log(self.run.id, line)
        self.emit({"type": "agent_line", "line": line})

    def emit_tracking(self, tracker: ProjectTracker, detail: str = "") -> None:
        s = tracker.state
        self.emit(
            {
                "type": "tracking",
                "linear_url": s.linear_project_url,
                "github_url": s.github_url,
                "linear_project": s.linear_project_name,
                "detail": detail,
            }
        )


def _maybe_refresh_research(
    ctx: RunContext,
    secrets: UserSecrets,
    composio: ComposioOps,
    idea: str,
    query: str,
    demo: bool,
    research_blocks: List[str],
    workdir: Path,
) -> List[str]:
    ctx.start_phase("research-refresh", "Tavily", f"Targeted refresh: {query[:80]}…", stage="loop")
    bundle = TavilyResearch(secrets, demo=demo).search_ideas(query or idea)
    urls = [h.url for h in bundle.hits[:3] if h.url.startswith("http")]
    crawl = FirecrawlResearch(secrets, composio=composio, demo=demo).scrape_urls(urls)
    block = f"## Research refresh\n{bundle.to_context_block()}\n\n{crawl.to_context_block()}"
    research_blocks.append(block)
    (workdir / "RESEARCH.md").write_text("\n\n---\n\n".join(research_blocks))
    ctx.finish_phase("research-refresh", f"+{len(crawl.pages)} pages", stage="loop")
    ctx.emit({"type": "play_by_play", "message": "Research refresh (targeted)", "kind": "tavily"})
    return research_blocks


def _run_preflight_gate(
    ctx: "RunContext",
    run: Run,
    secrets: UserSecrets,
    composio: ComposioOps,
    idea_seed: str,
    existing_repo: bool,
) -> Tuple[bool, str]:
    """Gate the build on connected integrations + clarifying answers.

    Returns ``(proceed, answers_text)``. When something is missing/ambiguous the
    run pauses (status ``awaiting_input``), emails the user, and block-polls for a
    reply via the manual-takeover queue (which the inbound poller also feeds).
    """
    missing = missing_integrations(secrets)
    questions = clarifying_questions(idea_seed, secrets=secrets, existing_repo=existing_repo)
    if not needs_input(missing, questions):
        return True, ""

    ctx.start_phase("preflight", "Preflight", "Checking integrations + scope…", stage="setup")
    update_run(run.id, status="awaiting_input")
    ctx.emit(
        {
            "type": "needs_input",
            "run_id": run.id,
            "missing_integrations": missing,
            "questions": questions,
        }
    )
    ctx.emit(
        {
            "type": "play_by_play",
            "message": f"Paused — needs input ({len(missing)} integration(s), {len(questions)} question(s))",
            "kind": "preflight",
        }
    )

    body = build_needs_input_email(
        product="", idea=idea_seed, missing=missing, questions=questions, run_id=run.id
    )
    try:
        composio.send_gmail(
            f"[Creation] Action needed before I build — {idea_seed[:50]}",
            body,
            secrets.gmail_notify_to.strip() or "me",
        )
    except Exception:  # pragma: no cover - email is best-effort
        logger.warning("preflight email failed", exc_info=True)

    deadline = time.monotonic() + max(secrets.preflight_timeout_secs, 0)
    poll = min(max(secrets.inbound_poll_secs, 5), 30)
    answers: List[str] = []
    while time.monotonic() < deadline:
        msgs = drain_for_turn(run.id, 0)
        if msgs:
            answers = [m["text"] for m in msgs]
            break
        missing = missing_integrations(secrets)
        if not questions and not missing:
            break
        time.sleep(poll)

    answer_text = "\n".join(a for a in answers if a.strip()).strip()
    still_missing = missing_integrations(secrets)
    if answer_text:
        ctx.emit({"type": "input_received", "run_id": run.id, "answers": answers})
        ctx.finish_phase("preflight", "Input received — resuming", stage="setup")
        update_run(run.id, status="running")
        return True, answer_text
    if still_missing:
        ctx.finish_phase(
            "preflight", f"Timed out — {len(still_missing)} integration(s) still missing", stage="setup"
        )
        ctx.emit(
            {
                "type": "play_by_play",
                "message": "Preflight timed out with integrations still missing — stopping cleanly",
                "kind": "preflight",
            }
        )
        return False, ""
    ctx.finish_phase("preflight", "Proceeding with safe defaults", stage="setup")
    update_run(run.id, status="running")
    return True, ""


def run_factory(
    run: Run,
    secrets: UserSecrets,
    seed: str = "",
    *,
    max_turn_budget: int | None = None,
    on_event: Callable[[Dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    demo = settings.creation_demo
    ctx = RunContext(run, list(run.phases), on_event=on_event)
    project = get_project(run.project_id)
    if not project:
        raise ValueError("project not found")

    agent_kind = project.agent  # type: ignore
    if not demo:
        validate_live_run(secrets, agent_kind)  # type: ignore

    workdir = Path(project.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    # Detect a pre-existing codebase before any scaffolding/artifacts are written
    # so Creation modifies it in place instead of treating it as a greenfield build.
    existing_repo = has_existing_sources(workdir)
    template_id = getattr(project, "template_id", "greenfield") or "greenfield"
    template_hint = apply_template(
        workdir, template_id, project.idea or seed, preserve_existing=existing_repo
    )
    if template_hint:
        (workdir / "TEMPLATE.md").write_text(template_hint, encoding="utf-8")
    update_run(run.id, status="running", agent_log="")
    max_turns = resolve_max_turns(secrets, project, max_turn_budget)
    ctx.emit(
        {
            "type": "started",
            "project_id": project.id,
            "agent": agent_kind,
            "completion_mode": "linear",
            "orchestration": "smart_router",
            "max_turns": max_turns,
            "workdir": str(workdir),
            "existing_repo": existing_repo,
        }
    )
    if existing_repo:
        ctx.agent_line(f"📂 Targeting existing repo at {workdir} — working in place, no scaffold.")

    composio = ComposioOps(secrets, demo=demo or not secrets.composio_api_key.strip())
    memory = build_memory_bridge(secrets, demo=demo)
    mem_label = provider_label(memory.name)
    ctx.emit(
        {
            "type": "memory",
            "provider": memory.name,
            "label": mem_label,
            "enabled": memory.enabled,
        }
    )

    def _on_play(payload: Dict[str, Any]) -> None:
        ctx.emit({"type": "play_by_play", **payload})
        if payload.get("linear_url") or payload.get("github_url"):
            ctx.emit(
                {
                    "type": "tracking",
                    "linear_url": payload.get("linear_url", ""),
                    "github_url": payload.get("github_url", ""),
                    "linear_project": payload.get("linear_project", ""),
                    "detail": payload.get("message", ""),
                }
            )

    tracker = ProjectTracker(composio, secrets, on_play=_on_play)
    build_complete = False
    inbound_poller: Optional[InboundPoller] = None

    try:
        # ── One-time setup (never repeated per turn) ──
        user_task = (project.idea or seed or "").strip()

        # ── Preflight gate: finish onboarding + ask questions before building ──
        if secrets.preflight_enabled and not demo:
            proceed, answers = _run_preflight_gate(
                ctx, run, secrets, composio, user_task, existing_repo
            )
            if not proceed:
                update_run(
                    run.id,
                    status="awaiting_input",
                    current_phase="",
                    finished_at=_ts(),
                    result={"stopped_reason": "awaiting_input", "project_id": project.id},
                )
                ctx.emit({"type": "stopped", "status": "awaiting_input", "reason": "missing_integrations"})
                return {"status": "awaiting_input", "reason": "missing_integrations"}
            if answers:
                seed = f"{seed}\n\nUser answers:\n{answers}".strip() if seed else answers
                user_task = f"{user_task}\n\n{answers}".strip()

        ctx.start_phase("tavily", "Tavily", "Web research (one-time)…", stage="setup")
        if existing_repo and user_task:
            bundle = TavilyResearch(secrets, demo=demo).search_ideas(user_task)
            idea = user_task
            ctx.finish_phase("tavily", f"Scoped edit: {idea[:120]}", sources=len(bundle.hits), stage="setup")
        else:
            bundle = TavilyResearch(secrets, demo=demo).search_ideas(seed or project.idea)
            idea = _pick_best_idea(bundle, seed or project.idea)
            ctx.finish_phase("tavily", f"Idea: {idea[:120]}", sources=len(bundle.hits), stage="setup")

        ctx.start_phase("composio", "Composio", "Checking integrations…", stage="setup")
        app_blocks = composio.gather_context()
        ctx.finish_phase("composio", f"{len(app_blocks)} toolkits ready", stage="setup")

        ctx.start_phase("firecrawl", "Firecrawl", "Deep scrape (one-time)…", stage="setup")
        urls = [h.url for h in bundle.hits[:5] if h.url.startswith("http")]
        crawl = FirecrawlResearch(secrets, composio=composio, demo=demo).scrape_urls(urls)
        ctx.finish_phase("firecrawl", f"{len(crawl.pages)} pages scraped", stage="setup")

        research_blocks = [bundle.to_context_block(), crawl.to_context_block(), *app_blocks]
        turn_blocks: List[str] = load_skill_blocks(workdir)
        ctx.emit({"type": "skills_loaded", **skills_status(workdir)})
        (workdir / "RESEARCH.md").write_text("\n\n---\n\n".join(research_blocks))
        update_project(project.id, idea=idea, name=idea[:80] or project.name, status="researching")

        ctx.start_phase("plan", "Nebius", "Build plan…", stage="setup")
        if demo:
            plan = (
                f"1. Read existing codebase\n2. {idea}\n3. Add/adjust tests\n4. Verify"
                if existing_repo
                else f"1. Scaffold MVP for: {idea}\n2. README + tests\n3. Core feature\n4. Polish"
            )
        elif existing_repo:
            plan = generate_edit_plan(secrets, idea, research_blocks, max_turns=max_turns)
        else:
            plan = generate_plan(secrets, idea, research_blocks, max_turns=max_turns)
        (workdir / "BUILD_PLAN.md").write_text(plan)
        ctx.finish_phase("plan", "Plan ready", stage="setup")

        ctx.start_phase("brand", "Nebius", "Naming & brand…", stage="setup")
        if existing_repo:
            gh_owner, gh_repo, _ = resolve_github_from_workdir(workdir)
            slug = gh_repo or workdir.name
            brand = ProductBrand(
                product_name=slug.replace("-", " ").title(),
                repo_slug=slug[:18],
                tagline=idea[:80],
                linear_project_name=f"Edit: {slug}"[:48],
            )
        elif demo:
            brand = ProductBrand.from_idea(idea)
        else:
            brand = generate_brand(secrets, idea, plan, research_blocks)
        ctx.finish_phase("brand", f"{brand.product_name} · {brand.repo_slug}", stage="setup")
        turn_blocks.append(brand.to_context_block())
        if not demo:
            product_md = generate_product_md(secrets, idea, plan, brand)
            (workdir / "PRODUCT.md").write_text(product_md, encoding="utf-8")

        ctx.start_phase("composio-setup", "Composio", "Linear · GitHub · kickoff email…", stage="setup")
        tracker.bootstrap(
            idea,
            plan,
            project.id,
            project.name or idea[:80],
            brand=brand,
            workdir=workdir,
            existing_repo=existing_repo,
        )
        turn_blocks.append(tracker.state.to_context_block())
        ctx.finish_phase(
            "composio-setup",
            "Tracking live",
            linear_url=tracker.state.linear_project_url,
            github_url=tracker.state.github_url,
            stage="setup",
        )
        ctx.emit({"type": "setup_complete", "linear_url": tracker.state.linear_project_url})
        ctx.emit_tracking(tracker, "Setup complete — entering build loop")

        # ── Inbound human-in-the-loop ──
        # Poll Gmail replies + Linear comments and feed them in as steering.
        if secrets.inbound_hitl_enabled and not demo:

            def _on_inbound(text: str, source: str) -> None:
                try:
                    add_message(run.id, text)
                except Exception:  # pragma: no cover - defensive
                    logger.warning("inbound add_message failed", exc_info=True)
                    return
                ctx.emit({"type": "inbound_message", "run_id": run.id, "source": source, "text": text[:280]})
                ctx.emit(
                    {
                        "type": "play_by_play",
                        "message": f"Inbound steering · {source}",
                        "kind": "manual",
                    }
                )

            inbound_poller = InboundPoller(
                composio,
                run.id,
                on_message=_on_inbound,
                linear_issue_id=tracker.state.plan_issue_id,
                gmail_subject=brand.product_name or idea[:50],
                interval_secs=secrets.inbound_poll_secs,
                enabled=secrets.inbound_hitl_enabled,
            )
            inbound_poller.start()
        memory.store_setup(
            project_id=project.id,
            run_id=run.id,
            idea=idea,
            plan=plan,
            product_name=brand.product_name,
        )

        # ── Auto-branch safety ──
        # When pointed at an existing repo with commits, build on a dedicated
        # `creation/<slug>` branch so the user's current/main branch stays clean.
        working_branch: Optional[str] = None
        if secrets.auto_branch and is_git_repo(workdir) and has_commits(workdir):
            branch_slug = brand.repo_slug or idea or project.name or "build"
            working_branch = ensure_working_branch(
                workdir, branch_slug, on_line=ctx.agent_line
            )
            if working_branch:
                ctx.emit({"type": "working_branch", "branch": working_branch})
                ctx.agent_line(f"🌿 Working on safety branch: {working_branch} (your base branch stays clean)")

        runner = CodingAgentRunner(agent_kind, secrets)  # type: ignore
        last_memory: Dict[str, Any] = {}
        # Aggregate token-preservation across every compressed turn for the receipt.
        memory_totals: Dict[str, Any] = {
            "original_tokens": 0,
            "kept_tokens": 0,
            "mem0_recalled": 0,
            "turns_compressed": 0,
        }
        agent_ok = True
        turns_completed = 0
        next_follow_up = ""
        last_qa = QABundle()
        pending_plan: Optional[TurnPlan] = None

        turn = 0
        while turn < max_turns:
            turn += 1
            turns_completed = turn
            ctx.emit({"type": "turn_started", "turn": turn, "max_turns": max_turns})

            steering_msgs = drain_for_turn(run.id, turn)
            if steering_msgs:
                turn_blocks.append(manual_takeover_block(steering_msgs))
                ctx.emit({"type": "manual_takeover", "turn": turn, "messages": steering_msgs})
                ctx.emit(
                    {
                        "type": "play_by_play",
                        "message": f"Manual takeover · {len(steering_msgs)} message(s) applied",
                        "kind": "manual",
                    }
                )
                steer = steering_summary(steering_msgs)
                next_follow_up = f"{steer}\n\n{next_follow_up}".strip() if next_follow_up else steer

            if pending_plan and pending_plan.done:
                build_complete = True
                break

            turn_plan = pending_plan or TurnPlan(
                run_agent=True,
                run_qa=True,
                follow_up=next_follow_up,
                reason="Kickoff build turn" if turn == 1 else TurnPlan.default_continue(turn).reason,
            )
            pending_plan = None
            if turn_plan.follow_up:
                next_follow_up = turn_plan.follow_up

            if turn_plan.refresh_research and not demo:
                research_blocks = _maybe_refresh_research(
                    ctx, secrets, composio, idea, next_follow_up, demo, research_blocks, workdir
                )

            agent_result = None
            qa_bundle = QABundle()

            if turn == 1 or turn_plan.run_agent:
                query = idea if turn == 1 else f"Turn {turn}: {next_follow_up}"
                include_research = turn == 1
                ctx.start_phase(f"mem0-{turn}", mem_label, "Recalling persistent memory…", stage="loop")
                mem0_recall = memory.recall(query, project_id=project.id, run_id=run.id)
                mem0_block = memory.to_context_block(mem0_recall)
                ctx.finish_phase(
                    f"mem0-{turn}",
                    f"{mem0_recall.count} memories" if mem0_recall.enabled else "off",
                    mem0={
                        "recalled": mem0_recall.count,
                        "enabled": mem0_recall.enabled,
                        "demo": mem0_recall.demo,
                    },
                    stage="loop",
                )
                ctx.start_phase(f"compress-{turn}", "SuperCompress", "Compressing turn context…", stage="loop")
                compressed, mem, mem_stack = _compress_blocks(
                    turn=turn,
                    query=query,
                    research_blocks=research_blocks,
                    turn_blocks=turn_blocks,
                    plan=plan,
                    brand=brand,
                    tracking=tracker.state,
                    follow_up=next_follow_up,
                    include_research=include_research,
                    budget=secrets.memory_budget,
                    mem0_block=mem0_block,
                    mem0_count=mem0_recall.count,
                )
                last_memory = {
                    "original_tokens": mem.original_tokens,
                    "kept_tokens": mem.kept_tokens,
                    "kv_savings_pct": mem.kv_savings_pct,
                    "policy": mem.policy_name,
                    "turn": turn,
                    "mem0_recalled": mem_stack.get("mem0_recalled", 0),
                    "mem0_enabled": mem_stack.get("mem0_enabled", False),
                    "provider": memory.name,
                    "stack": f"{memory.name}+supercompress",
                }
                memory_totals["original_tokens"] += int(mem.original_tokens or 0)
                memory_totals["kept_tokens"] += int(mem.kept_tokens or 0)
                memory_totals["mem0_recalled"] += int(mem_stack.get("mem0_recalled", 0) or 0)
                memory_totals["turns_compressed"] += 1
                ctx.finish_phase(
                    f"compress-{turn}",
                    f"{mem.original_tokens}→{mem.kept_tokens} tok",
                    memory=last_memory,
                    stage="loop",
                )

                prompt = (
                    _initial_agent_prompt(
                        idea, plan, compressed, tracker.state, brand, existing_repo=existing_repo
                    )
                    if turn == 1
                    else _followup_agent_prompt(
                        turn, next_follow_up, compressed, tracker.state, brand, existing_repo=existing_repo
                    )
                )

                agent_label = agent_kind
                turn_agent = agent_kind
                subtasks = (
                    list(turn_plan.subtasks)
                    if (secrets.subagents_enabled and not demo and len(turn_plan.subtasks) >= 2)
                    else []
                )
                use_parallel = secrets.parallel_agents and not demo and not subtasks
                sec_kind = normalize_agent(secrets.secondary_agent or "claude")
                if not demo:
                    turn_agent, failover_from, usage_snap = resolve_agent_for_turn(agent_kind, secrets)
                    ctx.emit(
                        {
                            "type": "agent_usage",
                            "turn": turn,
                            "agent": turn_agent,
                            **usage_snap.to_dict(),
                        }
                    )
                    if failover_from:
                        ctx.emit(
                            {
                                "type": "agent_failover",
                                "turn": turn,
                                "from_agent": failover_from,
                                "to_agent": turn_agent,
                                "pct": usage_snap.pct,
                                "reason": f"{failover_from} at {usage_snap.pct:.0f}% usage",
                            }
                        )
                        ctx.agent_line(
                            f"⚠ {failover_from} at {usage_snap.pct:.0f}% — failover to {turn_agent}"
                        )
                        runner = CodingAgentRunner(turn_agent, secrets)  # type: ignore[arg-type]
                    agent_label = turn_agent
                if use_parallel:
                    agents_map = {a["id"]: a for a in available_agents()}
                    if sec_kind == turn_agent or not agents_map.get(sec_kind, {}).get("available"):
                        use_parallel = False
                    elif not demo and should_skip_parallel_secondary(sec_kind, secrets):
                        sec_snap = resolve_agent_for_turn(sec_kind, secrets)[2]
                        ctx.emit(
                            {
                                "type": "agent_usage",
                                "turn": turn,
                                "agent": sec_kind,
                                **sec_snap.to_dict(),
                            }
                        )
                        ctx.agent_line(f"⚠ {sec_kind} usage high — parallel agent disabled")
                        use_parallel = False
                    else:
                        agent_label = f"{turn_agent}+{sec_kind}"

                if subtasks:
                    agent_label = f"{turn_agent}×{len(subtasks)}"

                ctx.start_phase(f"agent-{turn}", agent_label.title(), f"Building · turn {turn}", stage="loop")
                ctx.emit(
                    {
                        "type": "agent_turn",
                        "turn": turn,
                        "agent": agent_label,
                        "parallel": use_parallel,
                        "subagents": len(subtasks),
                    }
                )
                sub_names: List[str] = []
                if subtasks:
                    from creation.agents.runner import subagent_names

                    sub_names = subagent_names(len(subtasks))
                    ctx.emit(
                        {
                            "type": "subagents",
                            "turn": turn,
                            "agent": turn_agent,
                            "count": len(subtasks),
                            "tasks": [t[:200] for t in subtasks],
                            "members": [
                                {"index": i, "name": sub_names[i], "task": subtasks[i][:200]}
                                for i in range(len(subtasks))
                            ],
                        }
                    )
                    roster = ", ".join(sub_names)
                    ctx.emit(
                        {
                            "type": "play_by_play",
                            "message": f"{turn_agent} spawned {len(subtasks)} subagents ({roster}) · turn {turn}",
                            "kind": "agent",
                        }
                    )
                    ctx.agent_line(
                        f"─── Turn {turn} · {turn_agent} spawned {len(subtasks)} subagents ───"
                    )
                    for i, task in enumerate(subtasks):
                        ctx.agent_line(f"  ◆ {sub_names[i]}: {task[:140]}")
                else:
                    ctx.agent_line(f"─── Turn {turn} · {agent_label} ───")

                if demo:
                    raise RunValidationError("Demo mode skips the coding agent.")

                if subtasks:
                    agent_result = runner.run_subagents(
                        prompt,
                        subtasks,
                        workdir,
                        on_line=ctx.agent_line,
                        max_workers=max(2, secrets.max_subagents),
                        names=sub_names,
                        on_event=ctx.emit,
                    )
                elif use_parallel:
                    agent_result = runner.run_parallel(prompt, workdir, sec_kind, on_line=ctx.agent_line)
                else:
                    agent_result = runner.run(prompt, workdir, on_line=ctx.agent_line)
                if not demo:
                    record_turn(turn_agent)
                    if detect_rate_limit(agent_result.output):
                        mark_exhausted(turn_agent)
                        ctx.emit(
                            {
                                "type": "agent_usage",
                                "turn": turn,
                                "agent": turn_agent,
                                "pct": 100.0,
                                "status": "critical",
                                "source": "rate_limit",
                            }
                        )
                        ctx.agent_line(f"⚠ {turn_agent} hit rate limit — marked exhausted")
                agent_ok = agent_ok and agent_result.success
                ctx.finish_phase(
                    f"agent-{turn}",
                    "Complete" if agent_result.success else "Finished with errors",
                    success=agent_result.success,
                    stage="loop",
                )
                turn_blocks.append(f"## Agent output (turn {turn})\n{agent_result.output[-3000:]}")
                turn_blocks.append(f"## Workdir (turn {turn})\n{workdir_summary(workdir, 15)}")
                diff = workdir_diff(workdir)
                if diff:
                    ctx.emit({"type": "git_diff", "turn": turn, "diff": diff[:12000]})

            if (turn == 1 or turn_plan.run_qa) and not demo:
                ctx.start_phase(f"qa-{turn}", "QA", "Tests + browser…", stage="loop")
                qa_bundle = run_qa_suite(workdir, turn=turn)
                last_qa = qa_bundle
                turn_blocks.append(f"## QA (turn {turn})\n{qa_bundle.to_context_block()}")
                t = qa_bundle.tests
                b = qa_bundle.browser
                findings_payload = [
                    {"url": f.url, "severity": f.severity, "note": f.note} for f in b.findings
                ]
                ctx.emit(
                    {
                        "type": "qa_output",
                        "turn": turn,
                        "output": t.output[-8000:],
                        "command": t.command,
                        "ran": t.ran,
                        "passed": t.passed,
                        "failed": t.failed,
                        "browser_checked": bool(b.checked_urls),
                        "browser_engine": b.engine,
                        "checked_urls": b.checked_urls,
                        "findings": findings_payload,
                        "notes": b.notes[:8],
                        "screenshots": b.screenshots,
                    }
                )
                if t.ran:
                    test_part = f"{t.passed} passed · {t.failed} failed"
                else:
                    test_part = "no tests detected"
                if b.checked_urls:
                    n_pages = len(b.checked_urls)
                    n_find = len(b.findings)
                    browser_part = f"{n_pages} page{'' if n_pages == 1 else 's'} checked"
                    if n_find:
                        browser_part += f" · {n_find} finding{'' if n_find == 1 else 's'}"
                    else:
                        browser_part += " · clean"
                else:
                    browser_part = "browser skipped"
                ctx.finish_phase(
                    f"qa-{turn}",
                    f"{test_part} · {browser_part}",
                    stage="loop",
                )

            if agent_result is not None or qa_bundle.tests.ran or qa_bundle.browser.checked_urls:
                ctx.start_phase(f"ops-{turn}", "Composio", "Linear · GitHub · email", stage="loop")
                tracker.after_turn(
                    turn,
                    idea,
                    agent_result.success if agent_result else True,
                    workdir,
                    (agent_result.output[-2000:] if agent_result else turn_plan.reason),
                    qa=qa_bundle if qa_bundle.tests.ran else last_qa,
                    on_line=ctx.agent_line,
                )
                turn_blocks.append(tracker.refresh_linear_status())
                ctx.finish_phase(f"ops-{turn}", "Synced", stage="loop")
                ctx.emit_tracking(tracker, f"Turn {turn}")

            # Nebius routes the next turn (one call — no research unless refresh_research)
            ctx.start_phase(f"route-{turn}", "Nebius", "Routing next turn…", stage="loop")
            tracking_ctx = tracker.refresh_linear_status()
            if demo:
                pending_plan = TurnPlan(
                    done=turn >= 3,
                    follow_up=f"Polish for turn {turn + 1}",
                    reason="Demo loop",
                )
            else:
                pending_plan = generate_turn_plan(
                    secrets,
                    idea=idea,
                    plan=plan,
                    turn=turn,
                    max_turns=max_turns,
                    linear_context=tracking_ctx,
                    workdir_summary=workdir_summary(workdir, 25),
                    qa_context=last_qa.to_context_block(),
                    last_follow_up=next_follow_up,
                    max_subagents=secrets.max_subagents if secrets.subagents_enabled else 0,
                )
            ctx.finish_phase(f"route-{turn}", pending_plan.reason, stage="loop")
            ctx.emit(
                {
                    "type": "turn_plan",
                    "turn": turn,
                    "done": pending_plan.done,
                    "run_agent": pending_plan.run_agent,
                    "run_qa": pending_plan.run_qa,
                    "refresh_research": pending_plan.refresh_research,
                    "reason": pending_plan.reason,
                    "follow_up": pending_plan.follow_up,
                }
            )
            ctx.emit(
                {
                    "type": "follow_up",
                    "turn": turn,
                    "prompt": pending_plan.follow_up or ("DONE" if pending_plan.done else ""),
                    "done": pending_plan.done,
                    "kind": "route",
                }
            )
            qa_note = ""
            if last_qa.tests.ran:
                qa_note = f"{last_qa.tests.failed} test failures"
            elif last_qa.browser.findings:
                qa_note = f"{len(last_qa.browser.findings)} browser findings"
            record_turn_lesson(
                workdir,
                turn,
                pending_plan.reason,
                qa_summary=qa_note,
                follow_up=pending_plan.follow_up,
            )
            memory.store_turn(
                project_id=project.id,
                run_id=run.id,
                turn=turn,
                idea=idea,
                reason=pending_plan.reason,
                follow_up=pending_plan.follow_up,
                qa_summary=qa_note,
                agent_excerpt=ctx.agent_log[-800:] if ctx.agent_log else "",
            )
            if pending_plan.done:
                build_complete = True
                break
            next_follow_up = pending_plan.follow_up or next_follow_up

        if turn >= max_turns and not build_complete:
            logger.warning("Turn budget %s reached without completion", max_turns)

        completion: Dict[str, Any] = {}
        marketing_info: Dict[str, Any] = {}
        # Honest ship: always attempt to ship what we built (push + status email),
        # even on an incomplete build. "complete/verified" is reserved for the
        # receipt status — not a gate on whether we ship at all.
        ctx.emit(
            {
                "type": "play_by_play",
                "message": "Shipping — final push + status email…" if not build_complete else "Sending completion email…",
                "kind": "composio",
            }
        )
        completion = tracker.complete(
            idea, turns_completed, plan, workdir=workdir, qa=last_qa, build_complete=build_complete
        )
        if completion.get("stopped_reason") is None and not build_complete:
            completion["stopped_reason"] = "incomplete"

        # Launch marketing only when the build actually completed — a launch
        # announcement for an incomplete build would be dishonest.
        if build_complete:
            if secrets.marketing_enabled and (
                secrets.resend_api_key or secrets.ayrshare_api_key or demo
            ):
                ctx.start_phase("marketing", "Launch", "Email + social posts…", stage="loop")
                live_url = completion.get("pr_url") or tracker.state.github_url
                html_body = build_launch_email_html(
                    product_name=brand.product_name,
                    tagline=brand.tagline,
                    idea=idea,
                    deploy_url=live_url or "",
                    github_url=tracker.state.github_url or "",
                    pr_url=completion.get("pr_url") or "",
                )
                social_post = build_launch_social_post(
                    product_name=brand.product_name,
                    tagline=brand.tagline,
                    idea=idea,
                    deploy_url=live_url or "",
                    github_url=tracker.state.github_url or "",
                    pr_url=completion.get("pr_url") or "",
                )
                marketing_result = launch_marketing(
                    resend_api_key=secrets.resend_api_key,
                    resend_from=secrets.resend_from,
                    marketing_to=secrets.marketing_to,
                    resend_segment_id=secrets.resend_segment_id,
                    ayrshare_api_key=secrets.ayrshare_api_key,
                    marketing_platforms=secrets.marketing_platforms,
                    marketing_media_url=secrets.marketing_media_url,
                    subject=f"{brand.product_name or 'Your build'} is live",
                    html_body=html_body,
                    social_post=social_post,
                    demo=demo,
                )
                marketing_info = marketing_result.to_dict()
                ctx.finish_phase(
                    "marketing",
                    marketing_result.message[:80],
                    stage="loop",
                )
                ctx.emit({"type": "marketing", **marketing_info})

        # Real outcomes for an honest receipt (only true when an action succeeded).
        outcomes: Dict[str, Any] = dict(tracker.outcomes)

        agent_list = [agent_kind]
        if secrets.parallel_agents:
            sec = normalize_agent(secrets.secondary_agent or "claude")
            if sec != agent_kind:
                agent_list.append(sec)

        # Finalize aggregate token-preservation stats for the receipt.
        orig = memory_totals["original_tokens"]
        kept = memory_totals["kept_tokens"]
        memory_totals["tokens_saved"] = max(orig - kept, 0)
        memory_totals["overall_savings_pct"] = (
            round(100.0 * (1.0 - kept / orig), 1) if orig else 0.0
        )

        marketing_obj = MarketingResult(**marketing_info) if marketing_info else None
        ship_receipt = build_ship_receipt(
            idea=idea,
            product_name=brand.product_name,
            tagline=brand.tagline,
            turns=turns_completed,
            build_complete=build_complete,
            tracking=tracker.state.to_dict(),
            completion=completion,
            marketing=marketing_obj,
            memory=last_memory,
            memory_totals=memory_totals,
            qa={
                "tests_ran": last_qa.tests.ran,
                "tests_command": last_qa.tests.command,
                "tests_passed": last_qa.tests.passed,
                "tests_failed": last_qa.tests.failed,
                "tests_output": last_qa.tests.output[-8000:],
                "browser_checked": bool(last_qa.browser.checked_urls),
                "browser_engine": last_qa.browser.engine,
                "browser_checked_urls": last_qa.browser.checked_urls,
                "browser_findings": len(last_qa.browser.findings),
                "findings": [
                    {"url": f.url, "severity": f.severity, "note": f.note}
                    for f in last_qa.browser.findings
                ],
                "screenshots": last_qa.browser.screenshots,
            },
            agents=agent_list,
            sponsor_integrations=build_sponsor_integrations(
                secrets,
                template_id=template_id,
                memory=last_memory,
                agents=agent_list,
                demo=demo,
                outcomes=outcomes,
            ),
            working_branch=working_branch,
        )

        run_ok = agent_ok and build_complete
        update_project(project.id, status="built" if run_ok else "error")
        result = {
            "idea": idea,
            "plan": plan,
            "brand": {
                "product_name": brand.product_name,
                "repo_slug": brand.repo_slug,
                "tagline": brand.tagline,
            },
            "turns": turns_completed,
            "max_turns": max_turns,
            "build_complete": build_complete,
            "memory": last_memory,
            "agent": {"kind": agent_kind, "success": agent_ok, "parallel": secrets.parallel_agents},
            "tracking": tracker.state.to_dict(),
            "completion": completion,
            "marketing": marketing_info,
            "ship_receipt": ship_receipt,
            "workdir": str(workdir),
        }
        status = "completed" if run_ok else "failed"
        update_run(run.id, status=status, phases=ctx.phases, result=result, current_phase="", finished_at=_ts())
        ctx.emit({"type": "ship_receipt", **ship_receipt})
        ctx.emit({"type": "complete", "status": status, "result": result})
        fire_webhook(
            secrets.webhook_url,
            "build.complete" if build_complete else "build.stopped",
            {
                "project_id": project.id,
                "run_id": run.id,
                "status": status,
                "build_complete": build_complete,
                "turns": turns_completed,
                "tracking": tracker.state.to_dict(),
                "pr_url": completion.get("pr_url", ""),
                "deploy_url": ship_receipt.get("deploy_url", ""),
                "ship_receipt": ship_receipt,
            },
            secret=secrets.webhook_secret,
        )
        return result

    except Exception as e:
        logger.exception("creation run failed")
        update_run(run.id, status="failed", error=str(e), current_phase="", finished_at=_ts())
        ctx.emit({"type": "error", "message": str(e)})
        raise
    finally:
        if inbound_poller is not None:
            inbound_poller.stop()
