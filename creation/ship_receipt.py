"""Ship Receipt — proof-of-ship payload for dashboard and webhooks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from creation.integrations.deploy import DeployResult
from creation.integrations.marketing import MarketingResult


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _token_preservation(totals: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Real, aggregate token-preservation stats for the receipt panel."""
    t = totals or {}
    original = int(t.get("original_tokens") or 0)
    kept = int(t.get("kept_tokens") or 0)
    saved = int(t.get("tokens_saved") if t.get("tokens_saved") is not None else max(original - kept, 0))
    pct = t.get("overall_savings_pct")
    if pct is None:
        pct = round(100.0 * (1.0 - kept / original), 1) if original else 0.0
    recalled = int(t.get("mem0_recalled") or 0)
    turns = int(t.get("turns_compressed") or 0)
    if original:
        summary = (
            f"{pct:.0f}% saved ({_fmt_tokens(original)} → {_fmt_tokens(kept)} tokens)"
            + (f", {recalled} memories recalled" if recalled else "")
        )
    else:
        summary = "No compression recorded this run"
    return {
        "original_tokens": original,
        "kept_tokens": kept,
        "tokens_saved": saved,
        "savings_pct": pct,
        "mem0_recalled": recalled,
        "turns_compressed": turns,
        "summary": summary,
    }


def build_ship_receipt(
    *,
    idea: str,
    product_name: str,
    tagline: str,
    turns: int,
    build_complete: bool,
    tracking: Dict[str, Any],
    completion: Dict[str, Any],
    deploy: Optional[DeployResult] = None,
    marketing: Optional[MarketingResult] = None,
    memory: Optional[Dict[str, Any]] = None,
    memory_totals: Optional[Dict[str, Any]] = None,
    qa: Optional[Dict[str, Any]] = None,
    agents: Optional[list[str]] = None,
    sponsor_integrations: Optional[list[Dict[str, str]]] = None,
    working_branch: Optional[str] = None,
) -> Dict[str, Any]:
    gmail = completion.get("final_gmail") or {}
    gmail_ok = bool(gmail.get("success") if isinstance(gmail, dict) else getattr(gmail, "success", False))
    pr_url = completion.get("pr_url") or ""
    deploy_url = deploy.url if deploy and deploy.success else ""
    deploy_provider = deploy.provider if deploy else ""
    marketing_sent = bool(marketing and marketing.success)
    marketing_message = marketing.message[:200] if marketing else ""
    qa_data = qa or {}
    sponsors = sponsor_integrations or []
    live_integrations = [row["sponsor"] for row in sponsors if row.get("status") == "live"]
    qa_clean = bool(qa_data.get("tests_ran") and qa_data.get("tests_failed") == 0)
    browser_clean = bool(qa_data.get("browser_checked") and qa_data.get("browser_findings") == 0)
    artifact_count = sum(
        bool(value)
        for value in (
            tracking.get("github_url"),
            tracking.get("linear_project_url"),
            gmail_ok,
            deploy_url,
        )
    )
    proof = [
        {
            "axis": "Working demo",
            "status": "verified" if build_complete and qa_clean and deploy_url and artifact_count >= 3 else "partial",
            "evidence": (
                f"{artifact_count}/4 ship artifacts · {qa_data.get('tests_passed', 0)} tests passed · "
                f"{'live deploy' if deploy_url else 'deploy missing'}"
            ),
        },
        {
            "axis": "Integration depth",
            "status": "verified" if len(live_integrations) >= 4 else "partial",
            "evidence": (
                f"{len(live_integrations)} live integrations"
                + (f": {', '.join(live_integrations)}" if live_integrations else "")
            ),
        },
        {
            "axis": "Usefulness",
            "status": "demonstrated" if build_complete and artifact_count >= 3 else "partial",
            "evidence": (
                "Idea → researched plan → tested repo → tracked ship artifacts"
                if build_complete
                else "End-to-end outcome not complete"
            ),
        },
        {
            "axis": "Code quality",
            "status": "verified" if qa_clean and browser_clean else "partial",
            "evidence": (
                f"{qa_data.get('tests_passed', 0)} passed / {qa_data.get('tests_failed', 0)} failed · "
                f"{qa_data.get('browser_findings', 0)} browser findings"
            ),
        },
        {
            "axis": "Pitch + story",
            "status": "ready" if build_complete and artifact_count >= 3 else "partial",
            "evidence": "Receipt condenses the complete build into verifiable evidence",
        },
    ]

    return {
        "idea": idea,
        "product_name": product_name or idea[:80],
        "tagline": tagline,
        "turns": turns,
        "build_complete": build_complete,
        "github_url": tracking.get("github_url") or "",
        "working_branch": working_branch or "",
        "pr_url": pr_url,
        "linear_url": tracking.get("linear_project_url") or "",
        "linear_project": tracking.get("linear_project_name") or "",
        "gmail_sent": gmail_ok,
        "gmail_subject": gmail.get("message", "")[:120] if isinstance(gmail, dict) else "",
        "deploy_url": deploy_url,
        "deploy_provider": deploy_provider,
        "deploy_message": deploy.message[:200] if deploy else "",
        "marketing_sent": marketing_sent,
        "marketing_message": marketing_message,
        "agents": agents or [],
        "qa": qa_data,
        "memory_savings_pct": (memory or {}).get("kv_savings_pct"),
        "mem0_recalled": (memory or {}).get("mem0_recalled"),
        "token_preservation": _token_preservation(memory_totals),
        "sponsor_integrations": sponsors,
        "proof": proof,
        "verified_artifacts": artifact_count,
        "live_integration_count": len(live_integrations),
        "live_url": deploy_url or pr_url or tracking.get("github_url") or "",
    }
