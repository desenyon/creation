"""FastAPI local server — landing, dashboard, live SSE."""

from __future__ import annotations

import html
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from creation.agents.runner import available_agents
from creation.agents.usage import summarize_all
from creation.account_api import legacy as legacy_composio_router
from creation.account_api import router as account_router
from creation.forge_api import router as forge_router
from creation.composio_api import ensure_composio_ready, router as composio_router
from creation.integrations.composio_ops import ComposioOps
from creation.integrations.marketing import MarketingResult, launch_marketing
from creation.validate import RunValidationError, validate_live_run
from creation.config import UserSecrets, ensure_dirs, get_settings, load_secrets, save_secrets
from creation.events import publish, subscribe
from creation.manual_takeover import add_message, list_messages
from creation.orchestrator import PIPELINE, run_factory
from creation.store import (
    count_running_runs,
    create_project,
    create_run,
    delete_project,
    enqueue_project,
    get_project,
    get_run,
    init_db,
    list_projects,
    list_running_runs,
    list_runs,
    portfolio_summary,
    update_project,
)

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent
_REPO_DIR = _PKG_DIR.parent


def _resolve_dir(name: str) -> Path:
    """Find a UI directory whether running from an installed wheel or a checkout.

    Installed: the assets ship inside the package (``creation/app``). In a dev
    checkout the marketing site (``web``) still lives at the repo root.
    """
    bundled = _PKG_DIR / name
    return bundled if bundled.exists() else _REPO_DIR / name


# The dashboard/onboarding UI is bundled in the package so `pip install
# creation` is fully self-contained (no repo checkout needed).
APP_DIR = _resolve_dir("app")
# The public marketing site is deployed to Vercel from the repo root `web/`; it
# is an optional local convenience, not required for the installed product.
WEB_DIR = _resolve_dir("web")

app = FastAPI(title="Creation", version="0.6.0")
app.include_router(account_router)
app.include_router(legacy_composio_router)
app.include_router(forge_router)
app.include_router(composio_router)

from creation.work.api import router as work_router  # noqa: E402

app.include_router(work_router)


class SecretsUpdate(BaseModel):
    composio_api_key: Optional[str] = None
    composio_user_id: Optional[str] = None
    composio_github_auth_config_id: Optional[str] = None
    composio_linear_auth_config_id: Optional[str] = None
    composio_gmail_auth_config_id: Optional[str] = None
    composio_firecrawl_auth_config_id: Optional[str] = None
    composio_firecrawl_user_id: Optional[str] = None
    tavily_api_key: Optional[str] = None
    nebius_api_key: Optional[str] = None
    memory_provider: Optional[str] = None
    mem0_api_key: Optional[str] = None
    mem0_enabled: Optional[bool] = None
    supermemory_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    default_agent: Optional[str] = None
    memory_budget: Optional[float] = None
    auto_branch: Optional[bool] = None
    linear_team_id: Optional[str] = None
    linear_project_mode: Optional[str] = None
    linear_project_id: Optional[str] = None
    linear_project_url: Optional[str] = None
    linear_project_name: Optional[str] = None
    github_owner: Optional[str] = None
    github_repo: Optional[str] = None
    gmail_notify_to: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    ship_mode: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    schedule_interval_hours: Optional[int] = None
    max_turn_budget: Optional[int] = None
    parallel_agents: Optional[bool] = None
    secondary_agent: Optional[str] = None
    subagents_enabled: Optional[bool] = None
    max_subagents: Optional[int] = None
    work_graph_enabled: Optional[bool] = None
    work_auto_dispatch: Optional[bool] = None
    marketing_enabled: Optional[bool] = None
    resend_api_key: Optional[str] = None
    resend_from: Optional[str] = None
    marketing_to: Optional[str] = None
    resend_segment_id: Optional[str] = None
    ayrshare_api_key: Optional[str] = None
    marketing_platforms: Optional[str] = None
    marketing_media_url: Optional[str] = None
    max_concurrent_runs: Optional[int] = None
    agent_usage_warn_pct: Optional[float] = None
    agent_usage_critical_pct: Optional[float] = None
    agent_usage_failover_pct: Optional[float] = None
    agent_failover_enabled: Optional[bool] = None
    agent_fallback: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str = "Loop"
    idea: str = ""
    agent: str = "codex"
    template_id: str = "greenfield"
    workdir: str = ""
    max_turn_budget: Optional[int] = None


class QueueCreate(BaseModel):
    seed: str = ""


class RunCreate(BaseModel):
    seed: str = ""
    max_turn_budget: Optional[int] = None


class SuggestRequest(BaseModel):
    seed: str = ""
    count: int = 3


class ManualMessageCreate(BaseModel):
    text: str


class TesterFeedbackCreate(BaseModel):
    name: str
    email: str
    project: str = ""
    feedback: str


def _run_dict(r) -> Dict[str, Any]:
    return asdict(r)


def _agent_ready(sec: UserSecrets) -> bool:
    agents = {a["id"]: a for a in available_agents()}
    info = agents.get(sec.default_agent)
    return bool(info and info.get("available"))


def _memory_status(sec: UserSecrets, *, demo: bool = False) -> Dict[str, Any]:
    from creation.memory import memory_status

    return memory_status(sec, demo=demo)


def _tester_feedback_subject(body: TesterFeedbackCreate) -> str:
    target = body.project.strip() or body.name.strip() or body.email.strip() or "tester"
    return f"Creation tester feedback: {target}"[:180]


def _tester_feedback_plain_text(body: TesterFeedbackCreate) -> str:
    return "\n".join(
        [
            "Tester feedback for Creation",
            "",
            f"Name: {body.name.strip()}",
            f"Email: {body.email.strip()}",
            f"Project: {body.project.strip() or 'n/a'}",
            "",
            "Feedback:",
            body.feedback.strip(),
            "",
            "Source: https://creation.dev/testers",
        ]
    )


def _tester_feedback_html(body: TesterFeedbackCreate) -> str:
    name = html.escape(body.name.strip())
    email = html.escape(body.email.strip())
    project = html.escape(body.project.strip() or "n/a")
    feedback = html.escape(body.feedback.strip()).replace("\n", "<br />")
    return f"""<!DOCTYPE html>
<html>
  <body style="font-family:system-ui,-apple-system,sans-serif;line-height:1.5;color:#111;background:#fff">
    <h1 style="margin:0 0 16px">Creation tester feedback</h1>
    <p style="margin:0 0 8px"><strong>Name:</strong> {name}</p>
    <p style="margin:0 0 8px"><strong>Email:</strong> {email}</p>
    <p style="margin:0 0 16px"><strong>Project:</strong> {project}</p>
    <div style="margin:0 0 8px"><strong>Feedback</strong></div>
    <div style="white-space:normal;border-left:3px solid #f0a8c8;padding-left:12px">{feedback}</div>
    <p style="margin:20px 0 0;color:#666;font-size:14px">Source: https://creation.dev/testers</p>
  </body>
</html>"""


def _send_tester_feedback_email(sec: UserSecrets, body: TesterFeedbackCreate, *, demo: bool = False) -> MarketingResult:
    subject = _tester_feedback_subject(body)
    html_body = _tester_feedback_html(body)
    text_body = _tester_feedback_plain_text(body)
    recipient = (sec.marketing_to or sec.gmail_notify_to or "").strip()

    if sec.resend_api_key.strip() and sec.resend_from.strip():
        resend = launch_marketing(
            resend_api_key=sec.resend_api_key,
            resend_from=sec.resend_from,
            marketing_to=recipient,
            subject=subject,
            html_body=html_body,
            demo=demo,
        )
        if resend.success:
            return MarketingResult(
                True,
                provider="resend",
                message=resend.message or "Tester feedback emailed",
                broadcast_id=resend.broadcast_id,
                emails_sent=resend.emails_sent,
                channels=["email"],
            )

    if sec.composio_api_key.strip() and sec.composio_gmail_auth_config_id.strip():
        ops = ComposioOps(sec, demo=demo)
        recipient_to = recipient if recipient and recipient != "me" else "me"
        gmail = ops.send_gmail(subject, text_body, to=recipient_to)
        if gmail.success:
            return MarketingResult(
                True,
                provider="gmail",
                message=gmail.detail,
                channels=["email"],
            )
        return MarketingResult(False, provider="gmail", message=gmail.detail)

    return MarketingResult(
        False,
        message="No email integration configured for tester feedback",
    )


@app.on_event("startup")
def startup() -> None:
    ensure_dirs()
    init_db()
    from creation.work import store as _wstore
    from creation.work import audit as _audit
    from creation.work import playbook as _playbook

    _wstore.init_work_db()
    _audit.init_audit_db()
    _playbook.init_playbook_db()
    from creation.schedule import start_scheduler

    start_scheduler()
    from creation.work.loop import start_work_dispatcher

    start_work_dispatcher()


@app.get("/api/health")
def health() -> Dict[str, Any]:
    s = get_settings()
    sec = load_secrets()
    auth_configs = {
        "github": bool(sec.composio_github_auth_config_id),
        "linear": bool(sec.composio_linear_auth_config_id),
        "gmail": bool(sec.composio_gmail_auth_config_id),
        "firecrawl": bool(sec.composio_firecrawl_auth_config_id),
    }
    return {
        "ok": True,
        "demo": s.creation_demo,
        "agents": available_agents(),
        "pipeline": [{"id": p[0], "tool": p[1], "label": p[2]} for p in PIPELINE],
        "completion_mode": "linear",
        "api_version": 10,
        "orchestration": "smart_router",
        "max_concurrent_runs": sec.max_concurrent_runs,
        "running_count": count_running_runs(),
        "features": [
            "auth_config_connections",
            "autosuggest",
            "skills_memory",
            "mem0_memory",
            "supercompress",
            "ship_receipt",
            "launch_marketing",
            "existing_repo_edits",
            "parallel_agents",
            "manual_takeover",
            "concurrent_runs",
            "agent_usage_failover",
            "smart_router",
            "mission_control",
            "pr_ship",
            "firecrawl",
            "webhooks",
            "templates",
            "portfolio",
            "schedule",
        ],
        "pillars": {
            "composio": bool(sec.composio_api_key and sec.composio_user_id and all(auth_configs.values())),
            "tavily": bool(sec.tavily_api_key),
            "nebius": bool(sec.nebius_api_key),
            "mem0": bool(sec.mem0_enabled and (s.creation_demo or sec.mem0_api_key)),
            "memory": bool(_memory_status(sec, demo=s.creation_demo)["enabled"]),
            "agent": _agent_ready(sec),
        },
        "keys_configured": {
            "composio": bool(sec.composio_api_key),
            "composio_user_id": bool(sec.composio_user_id),
            **auth_configs,
            "tavily": bool(sec.tavily_api_key),
            "nebius": bool(sec.nebius_api_key),
            "mem0": bool(sec.mem0_api_key),
        },
        "memory_stack": {
            **_memory_status(sec, demo=s.creation_demo),
            "supercompress": "in-turn token eviction before agent calls",
        },
    }


@app.get("/api/memory/status")
def api_memory_status() -> Dict[str, Any]:
    """Live memory-stack detection for onboarding/settings (read-only).

    Returns the global ``memory_provider`` setting, the resolved provider, and
    which backends (mem0/supermemory) are detected on this machine.
    """
    s = get_settings()
    return _memory_status(load_secrets(), demo=s.creation_demo)


@app.get("/api/secrets")
def get_secrets_masked() -> Dict[str, Any]:
    sec = load_secrets()
    d = sec.model_dump()
    for k in d:
        if k.endswith("_api_key") and d[k]:
            d[k] = d[k][:4] + "••••" + d[k][-4:] if len(d[k]) > 8 else "••••"
    return d


@app.put("/api/secrets")
def put_secrets(body: SecretsUpdate) -> Dict[str, str]:
    sec = load_secrets()
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "schedule_enabled" and isinstance(v, str):
            v = v.lower() == "true"
        if k == "mem0_enabled" and isinstance(v, str):
            v = v.lower() == "true"
        if k == "parallel_agents" and isinstance(v, str):
            v = v.lower() == "true"
        if k == "subagents_enabled" and isinstance(v, str):
            v = v.lower() == "true"
        if k == "max_subagents" and isinstance(v, str):
            v = int(v) if v.strip().isdigit() else 3
        if k in ("work_graph_enabled", "work_auto_dispatch") and isinstance(v, str):
            v = v.lower() == "true"
        if k == "agent_failover_enabled" and isinstance(v, str):
            v = v.lower() == "true"
        if k == "auto_branch" and isinstance(v, str):
            v = v.lower() == "true"
        if k == "marketing_enabled" and isinstance(v, str):
            v = v.lower() == "true"
        setattr(sec, k, v)
    save_secrets(sec)
    return {"status": "saved"}


@app.get("/api/agents/usage")
def api_agents_usage() -> Dict[str, Any]:
    sec = load_secrets()
    agents = summarize_all(sec)
    return {
        "agents": [a.to_dict() for a in agents],
        "failover_enabled": sec.agent_failover_enabled,
        "failover_pct": sec.agent_usage_failover_pct,
        "fallback": sec.agent_fallback,
    }


@app.get("/api/runs/active")
def api_active_runs() -> Dict[str, Any]:
    sec = load_secrets()
    runs = list_running_runs()
    return {
        "runs": runs,
        "count": len(runs),
        "max_concurrent_runs": sec.max_concurrent_runs,
    }


@app.get("/api/projects")
def api_list_projects() -> List[Dict[str, Any]]:
    running = {r["project_id"]: r for r in list_running_runs()}
    out = []
    for p in list_projects():
        d = p.__dict__
        if p.id in running:
            d["running_run_id"] = running[p.id]["run_id"]
            d["run_status"] = "running"
        out.append(d)
    return out


@app.post("/api/projects")
def api_create_project(body: ProjectCreate) -> Dict[str, Any]:
    sec = load_secrets()
    agent = body.agent or sec.default_agent
    wd = body.workdir.strip() or None
    p = create_project(
        body.name,
        body.idea,
        agent,
        template_id=body.template_id or "greenfield",
        workdir=wd,
        max_turn_budget=body.max_turn_budget,
    )
    return p.__dict__


@app.get("/api/projects/{pid}")
def api_get_project(pid: str) -> Dict[str, Any]:
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    return {**p.__dict__, "runs": [_run_dict(r) for r in list_runs(pid)]}


@app.patch("/api/projects/{pid}")
def api_patch_project(pid: str, body: ProjectCreate) -> Dict[str, Any]:
    wd = body.workdir.strip() or None
    p = update_project(
        pid,
        name=body.name,
        idea=body.idea,
        agent=body.agent,
        template_id=body.template_id or "greenfield",
        workdir=wd,
        max_turn_budget=body.max_turn_budget,
    )
    if not p:
        raise HTTPException(404, "project not found")
    return p.__dict__


def _delete_project_or_409(pid: str) -> Dict[str, str]:
    try:
        if not delete_project(pid):
            raise HTTPException(404, "project not found")
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"status": "deleted", "id": pid}


@app.delete("/api/projects/{pid}")
def api_delete_project(pid: str) -> Dict[str, str]:
    return _delete_project_or_409(pid)


@app.post("/api/projects/{pid}/delete")
def api_delete_project_post(pid: str) -> Dict[str, str]:
    """POST fallback when DELETE is blocked or server is behind a restrictive proxy."""
    return _delete_project_or_409(pid)


@app.post("/api/suggest")
def api_suggest(body: SuggestRequest) -> Dict[str, Any]:
    """Autosuggest ranked product ideas (Tavily + Nebius)."""
    from creation.suggest import suggest_products

    secrets = load_secrets()
    settings = get_settings()
    demo = settings.creation_demo or not secrets.tavily_api_key.strip()
    ideas, bundle = suggest_products(
        secrets, body.seed, demo=demo, count=min(max(body.count, 1), 5)
    )
    return {
        "seed": body.seed,
        "query": bundle.query,
        "synthesis": bundle.answer,
        "suggestions": [s.to_dict() for s in ideas],
    }


@app.get("/api/templates")
def api_templates() -> List[Dict[str, Any]]:
    from creation.templates import list_templates

    return list_templates()


@app.get("/api/portfolio")
def api_portfolio() -> List[Dict[str, Any]]:
    return portfolio_summary()


@app.get("/api/queue")
def api_queue() -> Dict[str, Any]:
    from creation.schedule import queue_status

    return queue_status()


@app.post("/api/projects/{pid}/queue")
def api_enqueue(pid: str, body: QueueCreate) -> Dict[str, Any]:
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    qid = enqueue_project(pid, body.seed)
    return {"queue_id": qid, "project_id": pid, "status": "queued"}


@app.get("/api/runs/{rid}/diff")
def api_run_diff(rid: str) -> Dict[str, Any]:
    from creation.integrations.git_sync import workdir_diff

    r = get_run(rid)
    if not r:
        raise HTTPException(404, "run not found")
    p = get_project(r.project_id)
    if not p or not p.workdir:
        return {"diff": ""}
    return {"diff": workdir_diff(Path(p.workdir))}


@app.get("/api/projects/{pid}/qa/{turn}")
def api_qa_artifact(pid: str, turn: int) -> Dict[str, Any]:
    import json as _json

    p = get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    meta_path = Path(p.workdir) / ".creation" / "qa" / f"turn_{turn}" / "meta.json"
    test_path = Path(p.workdir) / ".creation" / "qa" / f"turn_{turn}" / "tests.txt"
    if not meta_path.exists():
        raise HTTPException(404, "qa artifacts not found")
    meta = _json.loads(meta_path.read_text())
    output = test_path.read_text() if test_path.exists() else ""
    return {**meta, "output": output}


@app.get("/api/projects/{pid}/skills")
def api_project_skills(pid: str) -> Dict[str, Any]:
    from creation.skills import skills_status

    p = get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    wd = Path(p.workdir) if p.workdir else None
    if not wd or not wd.exists():
        return {"project_id": pid, "ready": False, "lesson_count": 0}
    st = skills_status(wd)
    return {"project_id": pid, "ready": True, **st}


@app.get("/api/validate")
def api_validate(agent: Optional[str] = None) -> Dict[str, Any]:
    sec = load_secrets()
    kind = agent or sec.default_agent
    try:
        validate_live_run(sec, kind)  # type: ignore[arg-type]
        ensure_composio_ready()
        return {"ok": True, "agent": kind}
    except (RunValidationError, HTTPException) as e:
        detail = e.detail if isinstance(e, HTTPException) else str(e)
        return {"ok": False, "agent": kind, "error": detail}


@app.post("/api/projects/{pid}/run")
def api_run_factory(pid: str, body: RunCreate, bg: BackgroundTasks) -> Dict[str, Any]:
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    secrets = load_secrets()
    settings = get_settings()
    if not settings.creation_demo:
        max_runs = max(secrets.max_concurrent_runs, 1)
        if count_running_runs() >= max_runs:
            raise HTTPException(
                429,
                f"Max {max_runs} concurrent builds running — wait for one to finish or raise max_concurrent_runs in settings",
            )
        try:
            validate_live_run(secrets, p.agent)  # type: ignore[arg-type]
        except RunValidationError as e:
            raise HTTPException(400, str(e)) from e
        ensure_composio_ready()

    run = create_run(pid)

    def _job() -> None:
        from creation.events import publish
        from creation.store import update_run as ur

        try:
            run_factory(run, secrets, body.seed, max_turn_budget=body.max_turn_budget)
        except Exception as e:
            logger.exception("creation run failed")
            ur(run.id, status="failed", error=str(e), finished_at=datetime.now(timezone.utc).isoformat())
            publish(run.id, {"type": "error", "message": str(e)})

    bg.add_task(_job)
    return {"run_id": run.id, "status": "started"}


@app.get("/api/runs/{rid}")
def api_get_run(rid: str) -> Dict[str, Any]:
    r = get_run(rid)
    if not r:
        raise HTTPException(404, "run not found")
    out = _run_dict(r)
    out["manual_messages"] = list_messages(rid)
    return out


@app.get("/api/runs/{rid}/messages")
def api_list_run_messages(rid: str) -> List[Dict[str, Any]]:
    if not get_run(rid):
        raise HTTPException(404, "run not found")
    return list_messages(rid)


@app.post("/api/runs/{rid}/messages")
def api_post_run_message(rid: str, body: ManualMessageCreate) -> Dict[str, Any]:
    r = get_run(rid)
    if not r:
        raise HTTPException(404, "run not found")
    if r.status != "running":
        raise HTTPException(400, "Manual takeover is only available while a run is active")
    try:
        msg = add_message(rid, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    publish(rid, {"type": "manual_message", **msg})
    return msg


@app.get("/api/runs/{rid}/stream")
async def api_stream_run(rid: str) -> StreamingResponse:
    r = get_run(rid)
    if not r:
        raise HTTPException(404, "run not found")

    async def gen():
        snap = json.dumps({"type": "snapshot", "run": _run_dict(r)})
        yield f"data: {snap}\n\n"
        async for msg in subscribe(rid):
            yield f"data: {msg}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/api/projects/{pid}/artifact")
def api_project_artifact(pid: str, path: str) -> FileResponse:
    p = get_project(pid)
    if not p or not p.workdir:
        raise HTTPException(404)
    root = Path(p.workdir).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "artifact not found")
    return FileResponse(target)


@app.get("/api/projects/{pid}/files")
def api_list_files(pid: str) -> List[str]:
    p = get_project(pid)
    if not p:
        raise HTTPException(404)
    root = Path(p.workdir)
    if not root.exists():
        return []
    return [str(f.relative_to(root)) for f in root.rglob("*") if f.is_file()][:200]


if APP_DIR.exists():
    app.mount("/assets", StaticFiles(directory=APP_DIR / "assets"), name="assets")


_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


@app.get("/")
def landing() -> FileResponse:
    return FileResponse(APP_DIR / "landing.html", headers=_NO_CACHE)


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse(APP_DIR / "dashboard.html", headers=_NO_CACHE)


@app.get("/board")
def board_removed() -> Response:
    return Response(status_code=404)


@app.get("/onboarding")
def onboarding() -> FileResponse:
    return FileResponse(APP_DIR / "onboarding.html", headers=_NO_CACHE)


@app.get("/site")
def marketing_redirect():
    """Local mirror of the public marketing site (only in a dev checkout)."""
    index = WEB_DIR / "index.html"
    if not index.exists():
        return RedirectResponse("/")
    return FileResponse(index)


@app.get("/testers")
def testers_page():
    """Local mirror of the public tester portal."""
    page = WEB_DIR / "testers.html"
    if not page.exists():
        return RedirectResponse("/")
    return FileResponse(page)


@app.post("/api/testers/feedback")
def api_tester_feedback(body: TesterFeedbackCreate) -> Dict[str, Any]:
    sec = load_secrets()
    settings = get_settings()
    result = _send_tester_feedback_email(sec, body, demo=settings.creation_demo)
    if not result.success:
        raise HTTPException(status_code=503, detail=result.message or "unable to send feedback")
    return result.to_dict()
