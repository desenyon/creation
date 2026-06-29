"""Coding agent adapters — spawn any registered terminal-native CLI."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from creation.agents.registry import AGENT_REGISTRY, AgentSpec, build_command, normalize_agent, resolve_spec
from creation.config import UserSecrets

LineCallback = Callable[[str], None]
EventCallback = Callable[[Dict[str, object]], None]

# Friendly, distinct call-signs for subagents so a fan-out turn reads like a team
# rather than "sub1/sub2". Computing pioneers — easy to tell apart in the log/UI.
SUBAGENT_NAMES = [
    "Ada", "Turing", "Hopper", "Lovelace", "Knuth",
    "Dijkstra", "Ritchie", "Torvalds", "Liskov", "Carmack",
]


def subagent_names(n: int) -> List[str]:
    """Return ``n`` distinct subagent call-signs (cycles with a suffix past the roster)."""
    out: List[str] = []
    for i in range(max(0, n)):
        base = SUBAGENT_NAMES[i % len(SUBAGENT_NAMES)]
        out.append(base if i < len(SUBAGENT_NAMES) else f"{base}-{i // len(SUBAGENT_NAMES) + 1}")
    return out


@dataclass
class AgentResult:
    agent: str
    success: bool
    output: str
    command: str


def _cursor_stream_line(raw: str) -> Optional[str]:
    line = raw.strip()
    if not line:
        return None
    if not line.startswith("{"):
        return line
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(obj, dict):
        return line

    typ = str(obj.get("type") or obj.get("event") or "")
    if typ in ("assistant", "message", "text", "content", "result"):
        content = obj.get("content") or obj.get("text") or obj.get("message") or obj.get("result")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [p.get("text", p) if isinstance(p, dict) else str(p) for p in content]
            joined = "".join(str(p) for p in parts if p).strip()
            if joined:
                return joined

    if typ in ("tool_call", "tool_use", "tool", "function_call"):
        name = obj.get("name") or obj.get("tool") or obj.get("tool_name") or "tool"
        return f"▸ {name}"

    delta = obj.get("delta")
    if isinstance(delta, str) and delta.strip():
        return delta.strip()
    if isinstance(delta, dict):
        chunk = delta.get("content") or delta.get("text")
        if isinstance(chunk, str) and chunk.strip():
            return chunk.strip()

    subtype = obj.get("subtype") or obj.get("status")
    if subtype and typ:
        return f"· {typ}:{subtype}"
    return None


def _run_streaming(
    cmd: List[str],
    workdir: Path,
    env: Dict[str, str],
    on_line: Optional[LineCallback] = None,
    timeout: int = 600,
    line_mapper: Optional[Callable[[str], Optional[str]]] = None,
    stdin_text: Optional[str] = None,
) -> AgentResult:
    agent = cmd[0]
    lines: List[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            env={**os.environ, **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin_text else None,
            text=True,
            bufsize=1,
        )

        if stdin_text and proc.stdin is not None:
            proc.stdin.write(stdin_text)
            if not stdin_text.endswith("\n"):
                proc.stdin.write("\n")
            proc.stdin.close()

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                out_line = line_mapper(line) if line_mapper else line
                if out_line is None:
                    continue
                lines.append(out_line)
                if on_line:
                    on_line(out_line)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return AgentResult(
                agent=agent,
                success=False,
                output=f"Agent timed out after {timeout}s.",
                command=" ".join(cmd),
            )
        t.join(timeout=2)
        out = "\n".join(lines)[-12000:]
        return AgentResult(agent=agent, success=proc.returncode == 0, output=out, command=" ".join(cmd))
    except FileNotFoundError:
        msg = f"CLI not found: {agent}. Install it and ensure it's on PATH."
        if on_line:
            on_line(msg)
        return AgentResult(agent=agent, success=False, output=msg, command=" ".join(cmd))


def _write_prompt(workdir: Path, prompt: str) -> Path:
    p = workdir / "FACTORY_PROMPT.md"
    p.write_text(prompt)
    return p


def _bin_available(spec: AgentSpec) -> bool:
    if any(shutil.which(b) for b in spec.bins):
        return True
    if spec.npx_package and shutil.which("npx"):
        return True
    return False


class CodingAgentRunner:
    def __init__(self, kind: str, secrets: UserSecrets):
        self.kind = normalize_agent(kind)
        self.spec = resolve_spec(self.kind)
        self.secrets = secrets

    def run(self, prompt: str, workdir: Path, on_line: Optional[LineCallback] = None) -> AgentResult:
        workdir.mkdir(parents=True, exist_ok=True)
        _write_prompt(workdir, prompt)
        env = self._env()
        cmd = build_command(self.spec, prompt)
        if on_line:
            on_line(f"$ {' '.join(cmd)}")
        mapper = _cursor_stream_line if self.spec.stream_json else None
        stdin_text = prompt if self.spec.stdin_prompt else None
        return _run_streaming(
            cmd,
            workdir,
            env,
            on_line=on_line,
            line_mapper=mapper,
            timeout=self.spec.timeout,
            stdin_text=stdin_text,
        )

    def run_parallel(
        self,
        prompt: str,
        workdir: Path,
        secondary_kind: str,
        on_line: Optional[LineCallback] = None,
    ) -> AgentResult:
        """Run primary + secondary agents in parallel — backend vs frontend focus."""
        secondary = CodingAgentRunner(secondary_kind, self.secrets)
        primary_label = self.spec.label
        secondary_label = secondary.spec.label
        backend_prompt = (
            f"{prompt}\n\n## Parallel focus ({primary_label})\n"
            "Own backend, APIs, data layer, CLI, and server tests."
        )
        frontend_prompt = (
            f"{prompt}\n\n## Parallel focus ({secondary_label})\n"
            "Own frontend, UI, styling, components, and client-side code."
        )

        def tagged(label: str, cb: Optional[LineCallback]) -> Optional[LineCallback]:
            if not cb:
                return None

            def wrapper(line: str) -> None:
                cb(f"[{label}] {line}")

            return wrapper

        results: List[AgentResult] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.run, backend_prompt, workdir, tagged(primary_label, on_line)),
                pool.submit(secondary.run, frontend_prompt, workdir, tagged(secondary_label, on_line)),
            ]
            for fut in as_completed(futures):
                results.append(fut.result())

        combined = "\n\n".join(f"### {r.agent}\n{r.output[-4000:]}" for r in results)
        sec = normalize_agent(secondary_kind)
        return AgentResult(
            agent=f"{self.kind}+{sec}",
            success=all(r.success for r in results),
            output=combined,
            command=" | ".join(r.command for r in results),
        )

    def run_subagents(
        self,
        base_prompt: str,
        subtasks: List[str],
        workdir: Path,
        on_line: Optional[LineCallback] = None,
        max_workers: int = 3,
        names: Optional[List[str]] = None,
        on_event: Optional[EventCallback] = None,
    ) -> AgentResult:
        """Fan a single turn out into N focused, named subagents working concurrently.

        Each subagent runs the same coding-agent CLI in the shared workdir but is
        scoped to one disjoint subtask, so they shouldn't touch each other's files.
        Each gets a call-sign (e.g. "Ada"); output is tagged ``[Ada]`` and the
        ``on_event`` callback fires ``subagent_start``/``subagent_done`` so the UI can
        show each one live. Results are merged into one AgentResult (in task order).
        """
        tasks = [t.strip() for t in subtasks if t.strip()]
        if len(tasks) < 2:
            # Nothing to parallelize — fall back to a normal single run.
            return self.run(base_prompt, workdir, on_line=on_line)

        labels = list(names) if names else subagent_names(len(tasks))
        while len(labels) < len(tasks):
            labels.append(f"sub{len(labels) + 1}")
        workers = max(1, min(max_workers, len(tasks)))

        def tagged(label: str, cb: Optional[LineCallback]) -> Optional[LineCallback]:
            if not cb:
                return None

            def wrapper(line: str) -> None:
                cb(f"[{label}] {line}")

            return wrapper

        def prompt_for(index: int, task: str) -> str:
            others = "\n".join(
                f"  - {labels[j]}: {tasks[j][:160]}" for j in range(len(tasks)) if j != index
            )
            return (
                f"{base_prompt}\n\n"
                f"## You are subagent {labels[index]} ({index + 1} of {len(tasks)}) — your scope\n{task}\n\n"
                "You are one of several agents working on this repo at the same time. "
                "Stay strictly inside your scope above. Only create/edit files that belong to "
                "your scope; do NOT touch files owned by the other subagents:\n"
                f"{others}\n"
                "Commit nothing that reformats or rewrites shared files outside your scope."
            )

        def run_one(index: int, task: str) -> AgentResult:
            name = labels[index]
            if on_event:
                on_event({"type": "subagent_start", "index": index, "name": name, "task": task[:200]})
            res = self.run(prompt_for(index, task), workdir, tagged(name, on_line))
            if on_event:
                on_event({"type": "subagent_done", "index": index, "name": name, "success": res.success})
            return res

        results: List[Optional[AgentResult]] = [None] * len(tasks)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, i, task): i for i, task in enumerate(tasks)}
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()

        done = [r for r in results if r is not None]
        combined = "\n\n".join(
            f"### {labels[i]} ({r.agent})\n{r.output[-3500:]}" for i, r in enumerate(done)
        )
        return AgentResult(
            agent=f"{self.kind}×{len(tasks)}",
            success=all(r.success for r in done),
            output=combined,
            command=" | ".join(r.command for r in done),
        )

    def _env(self) -> Dict[str, str]:
        e: Dict[str, str] = {}
        if self.secrets.openai_api_key:
            e["OPENAI_API_KEY"] = self.secrets.openai_api_key
        if self.secrets.anthropic_api_key:
            e["ANTHROPIC_API_KEY"] = self.secrets.anthropic_api_key
        return e


def available_agents() -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for spec in AGENT_REGISTRY:
        bins = list(spec.bins)
        if spec.npx_package:
            bins.append("npx")
        out.append(
            {
                "id": spec.id,
                "label": spec.label,
                "available": _bin_available(spec),
                "bins": bins,
                "local_auth": spec.auth == "local",
                "auth": spec.auth,
            }
        )
    return out
