"""Production deployment to Vercel after a build completes."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\]'\"<>]+")


@dataclass
class DeployResult:
    success: bool
    url: str = ""
    provider: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "url": self.url,
            "provider": self.provider,
            "message": self.message,
        }


def _run(cmd: list[str], workdir: Path, *, env: Optional[dict] = None, timeout: int = 300) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return proc.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 1, f"Deploy timed out after {timeout}s"
    except FileNotFoundError:
        return 127, f"CLI not found: {cmd[0]}"


def _extract_vercel_url(output: str) -> str:
    urls = [
        url.rstrip(").,")
        for url in _URL_RE.findall(output or "")
        if ".vercel.app" in url and "vercel.com/" not in url
    ]
    return urls[-1] if urls else ""


def is_vercel_ready(workdir: Path) -> bool:
    markers = (
        "package.json",
        "index.html",
        "vercel.json",
        "next.config.js",
        "next.config.mjs",
        "vite.config.js",
        "vite.config.ts",
    )
    if any((workdir / name).exists() for name in markers):
        return True
    api_dir = workdir / "api"
    return api_dir.is_dir() and any(api_dir.glob("*.py"))


def _verify_url(url: str, *, attempts: int = 6, delay: float = 2.0) -> tuple[bool, str]:
    last_error = ""
    endpoints = (url, f"{url.rstrip('/')}/health")
    for attempt in range(attempts):
        for endpoint in endpoints:
            try:
                request = urllib.request.Request(endpoint, headers={"User-Agent": "Creation deploy verifier"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    status = int(getattr(response, "status", 200))
                    if 200 <= status < 400:
                        path = "/health" if endpoint.endswith("/health") else "/"
                        return True, f"HTTP {status} at {path}"
                    last_error = f"HTTP {status} at {endpoint}"
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code} at {endpoint}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"{exc} at {endpoint}"
        if attempt < attempts - 1:
            time.sleep(delay)
    return False, last_error or "unreachable"


def _vercel_project_name(workdir: Path) -> str:
    base = re.sub(r"[^a-z0-9._-]+", "-", workdir.name.lower()).strip(".-_") or "project"
    base = re.sub(r"-{2,}", "-", base)[:70].rstrip(".-_")
    digest = hashlib.sha1(str(workdir.resolve()).encode()).hexdigest()[:8]
    return f"creation-{base}-{digest}"[:100]


def _vercel_command_prefix() -> list[str]:
    if shutil.which("vercel"):
        return ["vercel"]
    if shutil.which("npx"):
        return ["npx", "--yes", "vercel"]
    return []


def _vercel_env(*, token: str = "", org_id: str = "", project_id: str = "") -> dict[str, str]:
    env: dict[str, str] = {}
    if token:
        env["VERCEL_TOKEN"] = token
    if org_id:
        env["VERCEL_ORG_ID"] = org_id
    if project_id:
        env["VERCEL_PROJECT_ID"] = project_id
    return env


def _token_args(token: str) -> list[str]:
    return ["--token", token] if token else []


def _deploy_vercel(
    workdir: Path,
    *,
    token: str = "",
    org_id: str = "",
    project_id: str = "",
    demo: bool = False,
    existing_repo: bool = False,
) -> DeployResult:
    if demo:
        slug = re.sub(r"[^a-z0-9-]", "-", workdir.name.lower())[:18] or "creation-demo"
        url = f"https://{slug}.vercel.app"
        return DeployResult(True, url, "vercel", f"[demo] Live at {url}")

    if not is_vercel_ready(workdir):
        if existing_repo:
            return DeployResult(
                True,
                provider="vercel",
                message="Skipped — existing repo has no web deploy markers (vercel.json, index.html, api/, etc.)",
            )
        return DeployResult(
            False,
            provider="vercel",
            message=(
                "Project is not Vercel-ready. Add package.json, index.html, vercel.json, "
                "or a Python function under api/."
            ),
        )

    env = _vercel_env(token=token, org_id=org_id, project_id=project_id)
    prefix = _vercel_command_prefix()
    if not prefix:
        return DeployResult(False, message="Vercel CLI not found (install vercel or use npx)")

    linked = (workdir / ".vercel" / "project.json").exists()
    if not linked:
        link_cmd = [*prefix, "link", "--yes", "--project", _vercel_project_name(workdir), *_token_args(token)]
        link_code, link_out = _run(link_cmd, workdir, env=env, timeout=120)
        if link_code != 0:
            return DeployResult(False, provider="vercel", message=link_out[-1200:] or "Vercel project link failed")

    # Prebuilt deploy (same path as GitHub Actions) — falls back to direct deploy.
    pull_cmd = [*prefix, "pull", "--yes", "--environment=production", *_token_args(token)]
    build_cmd = [*prefix, "build", "--prod", *_token_args(token)]
    prebuilt_cmd = [*prefix, "deploy", "--prebuilt", "--prod", "--yes", *_token_args(token)]
    direct_cmd = [*prefix, "deploy", "--prod", "--yes", *_token_args(token)]

    pull_code, pull_out = _run(pull_cmd, workdir, env=env, timeout=120)
    build_out = ""
    if pull_code == 0:
        build_code, build_out = _run(build_cmd, workdir, env=env, timeout=600)
        if build_code == 0:
            code, out = _run(prebuilt_cmd, workdir, env=env, timeout=600)
            if code == 0:
                url = _extract_vercel_url(out)
                if url:
                    reachable, verification = _verify_url(url)
                    if reachable:
                        return DeployResult(True, url, "vercel", f"Production deployment verified ({verification})")
                    return DeployResult(
                        False,
                        url,
                        "vercel",
                        f"Deployment created but failed reachability verification: {verification}",
                    )

    code, out = _run(direct_cmd, workdir, env=env, timeout=600)
    url = _extract_vercel_url(out)
    if code != 0:
        combined = "\n".join(filter(None, [pull_out[-400:], build_out[-400:], out[-800:]]))
        return DeployResult(False, url, "vercel", combined[-1200:] or f"vercel exit {code}")
    if not url:
        return DeployResult(False, provider="vercel", message=out[-1200:] or "Vercel returned no deployment URL")
    reachable, verification = _verify_url(url)
    if not reachable:
        return DeployResult(
            False,
            url,
            "vercel",
            f"Vercel deployment was created but failed reachability verification: {verification}",
        )
    return DeployResult(True, url, "vercel", f"Production deployment verified ({verification})")


def _detect_vercel_framework(workdir: Path) -> Optional[str]:
    """Best-effort Vercel framework slug so the linked project builds correctly."""
    if (workdir / "next.config.js").exists() or (workdir / "next.config.mjs").exists():
        return "nextjs"
    if (workdir / "vite.config.js").exists() or (workdir / "vite.config.ts").exists():
        return "vite"
    pkg = workdir / "package.json"
    if pkg.exists():
        try:
            import json

            deps = {}
            data = json.loads(pkg.read_text(errors="replace") or "{}")
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        except Exception:
            deps = {}
        if "next" in deps:
            return "nextjs"
        if "vite" in deps:
            return "vite"
        if "react-scripts" in deps:
            return "create-react-app"
    return None


def parse_github_repo(github_url: str) -> str:
    """Return ``owner/repo`` from a GitHub URL, or '' if it can't be parsed."""
    if not github_url:
        return ""
    m = re.search(r"github\.com[/:]+([^/]+/[^/#?]+)", github_url.strip())
    if not m:
        return ""
    return m.group(1).removesuffix(".git").strip("/")


def deploy_vercel_via_composio(
    secrets,
    repo_full_name: str,
    workdir: Path,
    *,
    demo: bool = False,
) -> DeployResult:
    """Link a GitHub repo to a Vercel project via Composio so it auto-deploys.

    Uses the connected Vercel account's ``VERCEL_CREATE_PROJECT2`` tool to create
    (or confirm) a project bound to ``repo_full_name``. Once linked, Vercel
    deploys every push to the default branch — no token or CLI needed.
    """
    workdir = Path(workdir)
    project_name = _vercel_project_name(workdir)
    url = f"https://{project_name}.vercel.app"
    if demo:
        return DeployResult(True, url, "vercel-git", f"[demo] Linked {repo_full_name} → Vercel ({url})")

    from creation.integrations.composio_ops import ComposioOps

    ops = ComposioOps(secrets, demo=False)
    args: dict = {
        "name": project_name,
        "gitRepository": {"type": "github", "repo": repo_full_name},
    }
    framework = _detect_vercel_framework(workdir)
    if framework:
        args["framework"] = framework

    res = ops.run_action("VERCEL_CREATE_PROJECT2", args)
    blob = f"{res.detail} {res.data}".lower()
    if res.success:
        return DeployResult(True, url, "vercel-git", f"Linked {repo_full_name} → Vercel; auto-deploys on every push")
    # Idempotent: a project already linked to this repo is success, not failure.
    if "already" in blob or "conflict" in blob or "exists" in blob or "409" in blob:
        return DeployResult(True, url, "vercel-git", f"{repo_full_name} already linked to Vercel; auto-deploys on push")
    return DeployResult(False, provider="vercel-git", message=(res.detail or "Vercel project link failed")[:600])


def deploy_project(
    workdir: Path,
    *,
    target: str = "vercel",
    demo: bool = False,
    vercel_token: str = "",
    vercel_org_id: str = "",
    vercel_project_id: str = "",
    existing_repo: bool = False,
) -> DeployResult:
    """Deploy a completed project to Vercel production and verify its URL."""
    workdir = Path(workdir)
    if not workdir.exists():
        return DeployResult(False, message="Workdir missing")

    target = (target or "vercel").lower().strip()
    if target == "none":
        return DeployResult(False, message="Deploy disabled")

    if demo:
        return _deploy_vercel(workdir, demo=True)

    return _deploy_vercel(
        workdir,
        token=vercel_token,
        org_id=vercel_org_id,
        project_id=vercel_project_id,
        existing_repo=existing_repo,
    )
