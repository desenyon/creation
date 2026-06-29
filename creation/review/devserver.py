"""Boot a generated app's dev server so browser QA can hit a real URL.

The orchestrator builds arbitrary projects (Vite/Next/CRA, Django, Flask,
FastAPI, or a static site). Browser QA used to fetch hardcoded localhost URLs
that pointed at Creation itself — useless for the project under test. This module
detects how to start the project, launches it on a known host/port, waits for
it to answer HTTP, and guarantees teardown.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Ports announced by the server in its own startup logs (e.g. "http://localhost:3000").
_LOG_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)")


@dataclass
class DevCommand:
    argv: List[str]
    port: int
    env: dict = field(default_factory=dict)
    install: Optional[List[str]] = None
    needs_node_modules: bool = False
    boot_timeout: float = 30.0
    label: str = ""


@dataclass
class DevServerHandle:
    base_url: Optional[str]
    command: str
    label: str
    log_path: Optional[Path] = None
    note: str = ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except Exception:
        return ""


def _find_python_web_entry(workdir: Path) -> Optional[tuple[str, str]]:
    """Return (kind, module/file) for a Python web app, if detectable."""
    for name in ("main.py", "app.py", "server.py", "api.py", "asgi.py", "wsgi.py"):
        f = workdir / name
        if not f.exists():
            continue
        text = _read_text(f)
        module = name[:-3]
        if "FastAPI(" in text or "from fastapi" in text:
            var = "app"
            for cand in ("app", "api", "application"):
                if f"{cand} = FastAPI(" in text or f"{cand}=FastAPI(" in text:
                    var = cand
                    break
            return ("fastapi", f"{module}:{var}")
        if "Flask(" in text or "from flask" in text:
            return ("flask", module)
    return None


def detect_dev_command(workdir: Path) -> Optional[DevCommand]:
    port = _free_port()
    py = sys.executable or "python3"

    pkg = workdir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(_read_text(pkg) or "{}")
        except Exception:
            data = {}
        scripts = data.get("scripts", {}) or {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        script = next((s for s in ("dev", "start", "serve", "preview") if s in scripts), None)
        if script:
            script_body = str(scripts.get(script, "")).lower()
            is_vite = "vite" in script_body or "vite" in deps
            env = {"PORT": str(port), "HOST": "127.0.0.1", "BROWSER": "none", "CI": "1"}
            if is_vite:
                argv = ["npm", "run", script, "--", "--port", str(port), "--host", "127.0.0.1"]
            else:
                argv = ["npm", "run", script]
            return DevCommand(
                argv=argv,
                port=port,
                env=env,
                install=["npm", "install", "--no-audit", "--no-fund", "--silent"],
                needs_node_modules=True,
                boot_timeout=40.0,
                label=f"npm run {script}",
            )

    if (workdir / "manage.py").exists():
        return DevCommand(
            argv=[py, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
            port=port,
            boot_timeout=30.0,
            label="django runserver",
        )

    py_entry = _find_python_web_entry(workdir)
    if py_entry:
        kind, target = py_entry
        if kind == "fastapi":
            return DevCommand(
                argv=[py, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(port)],
                port=port,
                boot_timeout=25.0,
                label=f"uvicorn {target}",
            )
        if kind == "flask":
            return DevCommand(
                argv=[py, "-m", "flask", "--app", target, "run", "--port", str(port)],
                port=port,
                env={"FLASK_APP": target},
                boot_timeout=25.0,
                label=f"flask run ({target})",
            )

    # Static site: an index.html with no server framework.
    if (workdir / "index.html").exists():
        return DevCommand(
            argv=[py, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            port=port,
            boot_timeout=10.0,
            label="python http.server",
        )

    return None


def _ports_from_log(log_path: Optional[Path]) -> List[int]:
    if not log_path or not log_path.exists():
        return []
    try:
        text = log_path.read_text(errors="replace")[-8000:]
    except Exception:
        return []
    return list(dict.fromkeys(int(m) for m in _LOG_URL_RE.findall(text)))


def _probe(
    requested_port: int,
    log_path: Optional[Path],
    deadline: float,
    proc: subprocess.Popen,
) -> Optional[str]:
    """Probe only the port we requested plus any port the server announces.

    We never blind-scan common ports — that risks latching onto an unrelated
    dev server already running on the machine.
    """
    with httpx.Client(timeout=2.5, follow_redirects=True) as client:
        while time.time() < deadline:
            if proc.poll() is not None:
                return None  # server process exited
            ports = [requested_port] + [p for p in _ports_from_log(log_path) if p != requested_port]
            for p in ports:
                try:
                    r = client.get(f"http://127.0.0.1:{p}/")
                    if r.status_code < 500:
                        return f"http://127.0.0.1:{p}"
                except Exception:
                    continue
            time.sleep(0.8)
    return None


def _terminate(proc: Optional[subprocess.Popen]) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:
        with contextlib.suppress(Exception):
            proc.terminate()
    try:
        proc.wait(timeout=6)
    except Exception:
        with contextlib.suppress(Exception):
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()


@contextlib.contextmanager
def boot_dev_server(workdir: Path, log_dir: Path) -> Iterator[Optional[DevServerHandle]]:
    """Detect, start, and wait for the project's dev server. Always tears down."""
    cmd = detect_dev_command(workdir)
    if not cmd:
        yield None
        return

    # First-time install for node projects (persists across turns).
    if cmd.install and cmd.needs_node_modules and not (workdir / "node_modules").exists():
        with contextlib.suppress(Exception):
            subprocess.run(cmd.install, cwd=str(workdir), capture_output=True, timeout=420)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "devserver.log"
    proc: Optional[subprocess.Popen] = None
    log_file = None
    try:
        log_file = open(log_path, "wb")
        env = {**os.environ, **cmd.env}
        kwargs: dict = dict(cwd=str(workdir), stdout=log_file, stderr=subprocess.STDOUT, env=env)
        if hasattr(os, "setsid"):
            kwargs["preexec_fn"] = os.setsid  # own process group for clean teardown
        try:
            proc = subprocess.Popen(cmd.argv, **kwargs)
        except FileNotFoundError as e:
            yield DevServerHandle(
                base_url=None,
                command=" ".join(cmd.argv),
                label=cmd.label,
                log_path=log_path,
                note=f"could not launch '{cmd.label}': {e}",
            )
            return

        base = _probe(cmd.port, log_path, time.time() + cmd.boot_timeout, proc)
        note = "" if base else f"dev server '{cmd.label}' did not become reachable within {int(cmd.boot_timeout)}s"
        yield DevServerHandle(base_url=base, command=" ".join(cmd.argv), label=cmd.label, log_path=log_path, note=note)
    finally:
        _terminate(proc)
        with contextlib.suppress(Exception):
            if log_file:
                log_file.close()
