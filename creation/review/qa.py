"""Post-turn QA — test runner + browser review for Linear + Nebius."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

from creation.review.devserver import boot_dev_server

logger = logging.getLogger(__name__)

# No defaults: an empty list means "no checkable URL" rather than probing
# Creation's own server. Real URLs come from the booted project dev server.
_DEFAULT_URLS: tuple[str, ...] = ()

_chromium_install_tried = False


@dataclass
class TestFailure:
    test_id: str
    message: str


@dataclass
class TestReport:
    ran: bool = False
    command: str = ""
    passed: int = 0
    failed: int = 0
    failures: List[TestFailure] = field(default_factory=list)
    output: str = ""

    def to_context_block(self) -> str:
        lines = ["## Test run"]
        if not self.ran:
            lines.append("No test suite detected or pytest not on PATH.")
            return "\n".join(lines)
        lines.append(f"Command: `{self.command}` · passed {self.passed} · failed {self.failed}")
        for f in self.failures[:12]:
            lines.append(f"- **{f.test_id}** — {f.message[:200]}")
        if self.output:
            lines.append(f"\n```\n{self.output[-1500:]}\n```")
        return "\n".join(lines)


@dataclass
class BrowserFinding:
    url: str
    severity: str
    note: str


@dataclass
class BrowserReport:
    engine: str = "httpx"
    checked_urls: List[str] = field(default_factory=list)
    findings: List[BrowserFinding] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)

    def to_context_block(self) -> str:
        lines = [f"## Browser review ({self.engine})"]
        if self.checked_urls:
            lines.append("Checked: " + ", ".join(self.checked_urls))
        for f in self.findings:
            lines.append(f"- [{f.severity}] {f.url} — {f.note}")
        for n in self.notes[:8]:
            lines.append(f"- {n}")
        if not self.findings and not self.notes:
            lines.append("No blocking issues detected on checked URLs.")
        return "\n".join(lines)


@dataclass
class QABundle:
    tests: TestReport = field(default_factory=TestReport)
    browser: BrowserReport = field(default_factory=BrowserReport)

    def to_context_block(self) -> str:
        return self.tests.to_context_block() + "\n\n" + self.browser.to_context_block()


def qa_artifacts_dir(workdir: Path) -> Path:
    d = workdir / ".creation" / "qa"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_qa_artifacts(workdir: Path, turn: int, bundle: QABundle) -> dict:
    """Persist test output + screenshot paths for mission-control panes."""
    d = qa_artifacts_dir(workdir)
    turn_dir = d / f"turn_{turn}"
    turn_dir.mkdir(parents=True, exist_ok=True)
    test_path = turn_dir / "tests.txt"
    if bundle.tests.output:
        test_path.write_text(bundle.tests.output, encoding="utf-8")
    meta = {
        "turn": turn,
        "test_output": str(test_path.relative_to(workdir)) if test_path.exists() else "",
        "screenshots": bundle.browser.screenshots,
        "tests_failed": bundle.tests.failed,
        "browser_findings": len(bundle.browser.findings),
    }
    (turn_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def run_qa_suite(workdir: Path, *, turn: int = 0) -> QABundle:
    bundle = QABundle(tests=run_tests(workdir), browser=run_browser_review(workdir, turn=turn))
    if turn:
        save_qa_artifacts(workdir, turn, bundle)
    return bundle


def run_tests(workdir: Path, timeout: int = 120) -> TestReport:
    report = TestReport()
    if not workdir.exists():
        return report

    if (workdir / "pyproject.toml").exists() or (workdir / "pytest.ini").exists() or (workdir / "tests").is_dir():
        if shutil.which("pytest"):
            report.command = "pytest -q"
            report.ran = True
            try:
                r = subprocess.run(
                    ["pytest", "-q", "--tb=short"],
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                out = (r.stdout or "") + "\n" + (r.stderr or "")
                report.output = out[-8000:]
                report.failures = _parse_pytest_failures(out)
                report.failed = len(report.failures)
                # pytest -q summary line: "3 failed, 2 passed"
                m = re.search(r"(\d+) passed", out)
                if m:
                    report.passed = int(m.group(1))
                if report.failed == 0 and r.returncode != 0 and not report.failures:
                    report.failures.append(TestFailure("pytest", f"exit code {r.returncode}"))
                    report.failed = 1
            except subprocess.TimeoutExpired:
                report.failures = [TestFailure("pytest", "timed out")]
                report.failed = 1
            return report

    if (workdir / "package.json").exists() and shutil.which("npm"):
        report.command = "npm test --if-present"
        report.ran = True
        try:
            r = subprocess.run(
                ["npm", "test", "--if-present"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (r.stdout or "") + "\n" + (r.stderr or "")
            report.output = out[-8000:]
            if r.returncode != 0:
                report.failures.append(TestFailure("npm test", out.strip()[-300:] or f"exit {r.returncode}"))
                report.failed = 1
        except subprocess.TimeoutExpired:
            report.failures = [TestFailure("npm test", "timed out")]
            report.failed = 1
    return report


def _parse_pytest_failures(output: str) -> List[TestFailure]:
    failures: List[TestFailure] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("FAILED "):
            rest = line[7:].strip()
            parts = rest.split(" - ", 1)
            failures.append(TestFailure(parts[0], parts[1] if len(parts) > 1 else "failed"))
        elif " ERROR " in line and line.endswith(" "):
            failures.append(TestFailure(line[:120], "error"))
    # short summary failures
    if not failures:
        for m in re.finditer(r"FAILED (\S+)", output):
            failures.append(TestFailure(m.group(1), "failed"))
    return failures[:20]


def _discover_urls(workdir: Path) -> List[str]:
    urls = list(_DEFAULT_URLS)
    readme = workdir / "README.md"
    if readme.exists():
        for m in re.finditer(r"https?://[^\s\)>\"]+", readme.read_text(errors="replace")):
            u = m.group(0).rstrip(".,)")
            if "localhost" in u or "127.0.0.1" in u:
                urls.append(u)
    return list(dict.fromkeys(urls))[:6]


def _build_urls(base_url: str) -> List[str]:
    base = base_url.rstrip("/")
    return [base or base_url]


def run_browser_review(workdir: Path, *, turn: int = 0) -> BrowserReport:
    shot_dir = qa_artifacts_dir(workdir) / (f"turn_{turn}" if turn else "latest")
    if turn:
        shot_dir.mkdir(parents=True, exist_ok=True)

    # Boot the generated app so we check the project under test (not Creation).
    with boot_dev_server(workdir, qa_artifacts_dir(workdir)) as server:
        boot_note = ""
        if server and server.base_url:
            urls = _build_urls(server.base_url)
        else:
            urls = _discover_urls(workdir)
            if server and server.note:
                boot_note = server.note

        if not urls:
            report = BrowserReport(engine="none")
            report.notes.append(boot_note or "No runnable app or localhost URL detected — browser QA skipped.")
            return report

        # The dev server stays alive inside this block while we hit it.
        pw = _playwright_review(urls, screenshot_dir=shot_dir if turn else None, workdir=workdir)
        report = pw or _httpx_review(urls)
        if server and server.label:
            report.notes.insert(0, f"Booted {server.label} → {server.base_url}")
        elif boot_note:
            report.notes.insert(0, boot_note)
        return report


def _httpx_review(urls: List[str]) -> BrowserReport:
    report = BrowserReport(engine="httpx", checked_urls=urls)
    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        for url in urls:
            try:
                r = client.get(url)
                if r.status_code >= 400:
                    report.findings.append(
                        BrowserFinding(url, "error", f"HTTP {r.status_code}")
                    )
                    continue
                text = r.text[:50000].lower()
                if "traceback" in text or "internal server error" in text:
                    report.findings.append(BrowserFinding(url, "error", "Error text in response body"))
                elif url.endswith("/dashboard") and "creation" not in text:
                    report.findings.append(BrowserFinding(url, "warn", "Dashboard HTML missing expected content"))
                else:
                    report.notes.append(f"OK {url} ({r.status_code})")
            except Exception as e:
                report.findings.append(BrowserFinding(url, "error", str(e)[:200]))
    return report


def _try_install_chromium() -> bool:
    """Install Playwright's chromium once per process so screenshots work."""
    global _chromium_install_tried
    if _chromium_install_tried:
        return False
    _chromium_install_tried = True
    try:
        r = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            timeout=300,
        )
        return r.returncode == 0
    except Exception as e:
        logger.debug("playwright install chromium failed: %s", e)
        return False


def _playwright_review(
    urls: List[str],
    screenshot_dir: Optional[Path] = None,
    workdir: Optional[Path] = None,
) -> Optional[BrowserReport]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    report = BrowserReport(engine="playwright", checked_urls=urls)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                if not _try_install_chromium():
                    return None
                browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            console_msgs: List[str] = []

            def _on_console(msg):
                if msg.type in ("error", "warning"):
                    console_msgs.append(f"{msg.type}: {msg.text[:120]}")

            page.on("console", _on_console)
            for url in urls:
                try:
                    console_msgs.clear()
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    status = resp.status if resp else 0
                    title = page.title()
                    if status >= 400:
                        report.findings.append(BrowserFinding(url, "error", f"HTTP {status}"))
                    else:
                        report.notes.append(f"OK {url} — title: {title[:80]}")
                    if screenshot_dir:
                        safe = re.sub(r"[^a-z0-9]+", "-", url.split("//")[-1].lower())[:40]
                        shot = screenshot_dir / f"{safe or 'page'}.png"
                        page.screenshot(path=str(shot), full_page=False)
                        if workdir:
                            try:
                                report.screenshots.append(str(shot.relative_to(workdir)))
                            except ValueError:
                                report.screenshots.append(str(shot))
                        else:
                            report.screenshots.append(str(shot))
                    # Streaming dashboards may never become network-idle.
                    page.reload(wait_until="domcontentloaded", timeout=12000)
                    for msg in console_msgs[:5]:
                        report.findings.append(BrowserFinding(url, "warn", f"Console {msg}"))
                except Exception as e:
                    report.findings.append(BrowserFinding(url, "error", str(e)[:200]))
            browser.close()
    except Exception as e:
        logger.debug("playwright review failed: %s", e)
        return None
    return report
