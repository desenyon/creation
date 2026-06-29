"""Deploy + ship receipt tests."""

import urllib.error
from pathlib import Path

from creation.integrations import deploy
from creation.integrations.deploy import DeployResult, deploy_project
from creation.ship_receipt import build_ship_receipt


def test_deploy_demo_vercel(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"demo"}')
    result = deploy_project(tmp_path, demo=True)
    assert result.success
    assert result.url.startswith("https://")
    assert result.provider == "vercel"


def test_deploy_disabled(tmp_path: Path):
    result = deploy_project(tmp_path, target="none")
    assert not result.success


def test_vercel_deploy_is_production_and_verified(tmp_path: Path, monkeypatch):
    (tmp_path / "index.html").write_text("ok")
    calls = []
    monkeypatch.setattr(deploy.shutil, "which", lambda name: "/opt/homebrew/bin/vercel" if name == "vercel" else None)

    def fake_run(cmd, workdir, **kwargs):
        calls.append(cmd)
        if len(cmd) >= 2 and cmd[1] == "pull":
            return 1, "skip prebuilt in test"
        if "deploy" in cmd:
            return 0, "Production: https://verified.vercel.app"
        return 0, "ok"

    monkeypatch.setattr(deploy, "_run", fake_run)
    monkeypatch.setattr(deploy, "_verify_url", lambda url: (True, "HTTP 200"))
    result = deploy_project(tmp_path)
    assert result.success
    assert result.url == "https://verified.vercel.app"
    assert calls[0][:4] == ["vercel", "link", "--yes", "--project"]
    assert any(c[:2] == ["vercel", "deploy"] for c in calls)


def test_vercel_deploy_skips_non_web_existing_repo(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('cli')")
    result = deploy_project(tmp_path, existing_repo=True)
    assert result.success
    assert "Skipped" in result.message


def test_vercel_deploy_rejects_unreachable_url(tmp_path: Path, monkeypatch):
    (tmp_path / "index.html").write_text("ok")
    monkeypatch.setattr(deploy.shutil, "which", lambda name: "/opt/homebrew/bin/vercel" if name == "vercel" else None)
    monkeypatch.setattr(
        deploy,
        "_run",
        lambda *args, **kwargs: (0, "Production: https://broken.vercel.app"),
    )
    monkeypatch.setattr(deploy, "_verify_url", lambda url: (False, "HTTP 500"))
    result = deploy_project(tmp_path)
    assert not result.success
    assert "verification" in result.message


def test_vercel_deploy_requires_compatible_project(tmp_path: Path):
    result = deploy_project(tmp_path)
    assert not result.success
    assert "not Vercel-ready" in result.message


def test_is_vercel_ready_public_alias(tmp_path: Path):
    (tmp_path / "vercel.json").write_text("{}")
    assert deploy.is_vercel_ready(tmp_path)


def test_verify_url_accepts_health_endpoint(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/health"):
            return Response()
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(deploy.urllib.request, "urlopen", fake_urlopen)
    success, message = deploy._verify_url("https://api.vercel.app", attempts=1, delay=0)
    assert success
    assert message == "HTTP 200 at /health"


def test_build_ship_receipt():
    receipt = build_ship_receipt(
        idea="CLI tool",
        product_name="SyncCLI",
        tagline="Sync everything",
        turns=5,
        build_complete=True,
        tracking={"github_url": "https://github.com/u/r", "linear_project_url": "https://linear.app/p"},
        completion={"pr_url": "https://github.com/u/r/pull/1", "final_gmail": {"success": True}},
        deploy=DeployResult(True, "https://sync.vercel.app", "vercel", "ok"),
        memory={"kv_savings_pct": 65, "mem0_recalled": 3},
        qa={
            "tests_ran": True,
            "tests_passed": 12,
            "tests_failed": 0,
            "browser_checked": True,
            "browser_findings": 0,
        },
        agents=["codex", "claude"],
        sponsor_integrations=[
            {"sponsor": name, "integration": "real", "status": "live"}
            for name in ("Tavily", "Nebius", "Composio", "SuperCompress")
        ],
    )
    assert receipt["live_url"] == "https://sync.vercel.app"
    assert receipt["gmail_sent"] is True
    assert receipt["agents"] == ["codex", "claude"]
    assert receipt["verified_artifacts"] == 4
    assert receipt["live_integration_count"] == 4
    assert len(receipt["proof"]) == 5
    assert not any(item["status"] == "partial" for item in receipt["proof"])
