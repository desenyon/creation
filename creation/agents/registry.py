"""Registry of terminal-native AI coding agent CLIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Literal, Optional

PromptBuilder = Callable[[str], List[str]]

AuthKind = Literal["local", "api_key", "mixed"]


@dataclass(frozen=True)
class AgentSpec:
    id: str
    label: str
    bins: tuple[str, ...]
    build: PromptBuilder
    npx_package: str = ""
    auth: AuthKind = "mixed"
    stream_json: bool = False
    stdin_prompt: bool = False
    timeout: int = 1800


def _trunc(prompt: str, n: int = 8000) -> str:
    return prompt[:n]


def _codex(prompt: str) -> List[str]:
    return ["codex", "exec", "--full-auto", _trunc(prompt)]


def _codex_npx(prompt: str) -> List[str]:
    return ["npx", "-y", "@openai/codex", "exec", "--full-auto", _trunc(prompt)]


def _claude(prompt: str) -> List[str]:
    return ["claude", "-p", _trunc(prompt), "--dangerously-skip-permissions"]


def _opencode(prompt: str) -> List[str]:
    return ["opencode", "run", _trunc(prompt)]


def _openclaw(prompt: str) -> List[str]:
    message = (
        "Act as the coding runtime for Creation. Work directly in the current process "
        "directory, use host tools to inspect and edit the repository, run verification, "
        "and complete the task without only describing changes.\n\n"
        + _trunc(prompt)
    )
    return [
        "openclaw",
        "agent",
        "--local",
        "--agent",
        "main",
        "--message",
        message,
        "--timeout",
        "1800",
    ]


def _cursor(prompt: str) -> List[str]:
    return [
        "cursor-agent",
        "-p",
        "--force",
        "--trust",
        "--output-format",
        "stream-json",
        "--stream-partial-output",
        _trunc(prompt),
    ]


def _cursor_legacy(prompt: str) -> List[str]:
    return ["cursor", "agent", "-p", _trunc(prompt)]


def _copilot(prompt: str) -> List[str]:
    return [
        "copilot",
        "--autopilot",
        "--allow-all",
        "--max-autopilot-continues",
        "50",
        "-p",
        _trunc(prompt),
    ]


def _gemini(prompt: str) -> List[str]:
    # --skip-trust: Creation runs headless in a managed workdir; without it Gemini
    # treats the folder as untrusted, overrides --yolo to "default", and refuses
    # to write any files (it only prints its banner).
    return ["gemini", "-p", _trunc(prompt), "--yolo", "--skip-trust"]


def _gemini_npx(prompt: str) -> List[str]:
    return ["npx", "-y", "@google/gemini-cli", "-p", _trunc(prompt), "--yolo", "--skip-trust"]


def _freebuff(prompt: str) -> List[str]:
    return ["freebuff"]


def _codebuff(prompt: str) -> List[str]:
    return ["codebuff"]


def _backboard(prompt: str) -> List[str]:
    return ["backboard"]


def _goose(prompt: str) -> List[str]:
    return ["goose", "run", "-t", _trunc(prompt)]


def _qwen(prompt: str) -> List[str]:
    return ["qwen", "-p", _trunc(prompt), "--yolo"]


def _qwen_code(prompt: str) -> List[str]:
    return ["qwen-code", "-p", _trunc(prompt), "--yolo"]


def _aider(prompt: str) -> List[str]:
    return ["aider", "--message", _trunc(prompt), "--yes-always", "--no-auto-commits"]


def _amazon_q(prompt: str) -> List[str]:
    return ["q", "chat", "--no-interactive", _trunc(prompt)]


def _kimi(prompt: str) -> List[str]:
    return ["kimi", "-p", _trunc(prompt), "--yolo"]


def _antigravity(prompt: str) -> List[str]:
    return ["agy", _trunc(prompt)]


def _pi(prompt: str) -> List[str]:
    return ["pi", "-p", _trunc(prompt)]


def _crush(prompt: str) -> List[str]:
    return ["crush", "--prompt", _trunc(prompt), "--yolo"]


def _cline(prompt: str) -> List[str]:
    return ["cline", "-y", _trunc(prompt)]


def _roo(prompt: str) -> List[str]:
    return ["roo", "-p", _trunc(prompt), "--yes"]


def _kilo(prompt: str) -> List[str]:
    return ["kilocode", "-p", _trunc(prompt), "--auto"]


def _plandex(prompt: str) -> List[str]:
    return ["plandex", "tell", _trunc(prompt)]


def _vibe(prompt: str) -> List[str]:
    return ["vibe", "-p", _trunc(prompt)]


def _gptme(prompt: str) -> List[str]:
    return ["gptme", _trunc(prompt)]


def _everycode(prompt: str) -> List[str]:
    return ["everycode", "-p", _trunc(prompt), "--yolo"]


def _droid(prompt: str) -> List[str]:
    return ["droid", "exec", "-p", _trunc(prompt), "--auto"]


def _factory(prompt: str) -> List[str]:
    return ["factory", "run", _trunc(prompt)]


def _amp(prompt: str) -> List[str]:
    return ["amp", "--no-tui", "--prompt", _trunc(prompt)]


def _continue_cli(prompt: str) -> List[str]:
    return ["cn", "-p", _trunc(prompt)]


def _neovate(prompt: str) -> List[str]:
    return ["neovate", "-p", _trunc(prompt), "--yolo"]


def _openhands(prompt: str) -> List[str]:
    return ["openhands", "-p", _trunc(prompt)]


def _swe_agent(prompt: str) -> List[str]:
    return ["sweagent", "run", _trunc(prompt)]


def _logicoal(prompt: str) -> List[str]:
    return ["logicoal", "-p", _trunc(prompt)]


def _forge(prompt: str) -> List[str]:
    return ["forge", "run", _trunc(prompt)]


def _coro(prompt: str) -> List[str]:
    return ["coro", "-p", _trunc(prompt)]


def _cto(prompt: str) -> List[str]:
    return ["solo-cto-agent", "do", _trunc(prompt)]


def _openharness(prompt: str) -> List[str]:
    return ["openharness", "-p", _trunc(prompt), "--yolo"]


def _trae(prompt: str) -> List[str]:
    return ["trae", "-p", _trunc(prompt)]


def _devon(prompt: str) -> List[str]:
    return ["devon", "-p", _trunc(prompt)]


def _letta(prompt: str) -> List[str]:
    return ["letta-code", "-p", _trunc(prompt)]


def _crab(prompt: str) -> List[str]:
    return ["crab", "-p", _trunc(prompt), "--yolo"]


def _warp(prompt: str) -> List[str]:
    return ["warp", "agent", "-p", _trunc(prompt)]


def _cmd(prompt: str) -> List[str]:
    return ["cmd", "-p", _trunc(prompt)]


AGENT_REGISTRY: tuple[AgentSpec, ...] = (
    AgentSpec("aider", "Aider", ("aider",), _aider, auth="api_key"),
    AgentSpec("amazon_q", "Amazon Q Developer", ("q",), _amazon_q, auth="local"),
    AgentSpec("amp", "Amp (Sourcegraph)", ("amp",), _amp, auth="mixed"),
    AgentSpec("antigravity", "Antigravity", ("agy", "antigravity"), _antigravity, auth="local"),
    AgentSpec("backboard", "Backboard R-CLI", ("backboard",), _backboard, auth="api_key", stdin_prompt=True),
    AgentSpec("claude", "Claude Code", ("claude",), _claude, auth="local"),
    AgentSpec("cline", "Cline CLI", ("cline",), _cline, auth="mixed"),
    AgentSpec("codex", "Codex", ("codex",), _codex, npx_package="@openai/codex", auth="local"),
    AgentSpec("command_code", "Command Code", ("cmd", "command-code"), _cmd, auth="mixed"),
    AgentSpec("continue", "Continue CLI", ("cn", "continue"), _continue_cli, auth="mixed"),
    AgentSpec("copilot", "GitHub Copilot CLI", ("copilot",), _copilot, npx_package="@github/copilot", auth="local"),
    AgentSpec("coro", "Coro Code", ("coro", "coro-code"), _coro, auth="mixed"),
    AgentSpec("crab", "Crab Code", ("crab",), _crab, auth="mixed"),
    AgentSpec("crush", "Crush", ("crush",), _crush, auth="mixed"),
    AgentSpec("cto", "Solo CTO Agent", ("solo-cto-agent", "solo-cto"), _cto, auth="api_key"),
    AgentSpec("cursor", "Cursor Agent", ("cursor-agent", "cursor"), _cursor, auth="local", stream_json=True),
    AgentSpec("devon", "Devon", ("devon",), _devon, auth="mixed"),
    AgentSpec("droid", "Factory Droid", ("droid",), _droid, auth="mixed"),
    AgentSpec("everycode", "Every Code", ("everycode",), _everycode, auth="mixed"),
    AgentSpec("factory", "Factory", ("factory",), _factory, auth="mixed"),
    AgentSpec("forge", "ForgeCode", ("forge",), _forge, auth="mixed"),
    AgentSpec("freebuff", "Freebuff", ("freebuff",), _freebuff, npx_package="freebuff", auth="local", stdin_prompt=True),
    AgentSpec("codebuff", "Codebuff", ("codebuff",), _codebuff, npx_package="codebuff", auth="mixed", stdin_prompt=True),
    AgentSpec("gemini", "Gemini CLI", ("gemini",), _gemini, npx_package="@google/gemini-cli", auth="local"),
    AgentSpec("goose", "Goose", ("goose",), _goose, auth="mixed"),
    AgentSpec("gptme", "gptme", ("gptme",), _gptme, auth="mixed"),
    AgentSpec("kilo", "Kilo Code", ("kilocode", "kilo"), _kilo, auth="mixed"),
    AgentSpec("kimi", "Kimi Code CLI", ("kimi",), _kimi, npx_package="@moonshot-ai/kimi-code", auth="local"),
    AgentSpec("letta", "Letta Code", ("letta-code", "letta"), _letta, auth="mixed"),
    AgentSpec("logicoal", "LogiCoal", ("logicoal",), _logicoal, auth="mixed"),
    AgentSpec("neovate", "Neovate Code", ("neovate",), _neovate, auth="mixed"),
    AgentSpec("openhands", "OpenHands CLI", ("openhands",), _openhands, auth="mixed"),
    AgentSpec("openharness", "openHarness", ("openharness",), _openharness, auth="mixed"),
    AgentSpec("openclaw", "OpenClaw Runtime", ("openclaw",), _openclaw, npx_package="openclaw", auth="local"),
    AgentSpec("opencode", "OpenCode", ("opencode",), _opencode, auth="mixed"),
    AgentSpec("pi", "Pi", ("pi",), _pi, auth="mixed"),
    AgentSpec("plandex", "Plandex", ("plandex",), _plandex, auth="api_key"),
    AgentSpec("qwen", "Qwen Code", ("qwen", "qwen-code"), _qwen, auth="local"),
    AgentSpec("roo", "Roo Code", ("roo",), _roo, auth="mixed"),
    AgentSpec("swe_agent", "SWE-agent", ("sweagent", "swe-agent"), _swe_agent, auth="api_key"),
    AgentSpec("trae", "Trae Agent", ("trae",), _trae, auth="mixed"),
    AgentSpec("vibe", "Mistral Vibe", ("vibe", "mistral-vibe"), _vibe, auth="mixed"),
    AgentSpec("warp", "Warp Agent", ("warp",), _warp, auth="local"),
)

AGENT_IDS: frozenset[str] = frozenset(a.id for a in AGENT_REGISTRY)

AGENT_BY_ID: dict[str, AgentSpec] = {a.id: a for a in AGENT_REGISTRY}


def normalize_agent(kind: str) -> str:
    k = (kind or "codex").strip().lower()
    if k not in AGENT_BY_ID:
        known = ", ".join(sorted(AGENT_IDS))
        raise ValueError(f"Unknown agent {kind!r}. Choose one of: {known}")
    return k


def resolve_spec(kind: str) -> AgentSpec:
    return AGENT_BY_ID[normalize_agent(kind)]


def build_command(spec: AgentSpec, prompt: str) -> List[str]:
    """Resolve the shell command for a spec, including npx/binary fallbacks."""
    import shutil

    if spec.id == "codex":
        if shutil.which("codex"):
            return spec.build(prompt)
        if spec.npx_package and shutil.which("npx"):
            return _codex_npx(prompt)
    if spec.id == "gemini":
        if shutil.which("gemini"):
            return spec.build(prompt)
        if spec.npx_package and shutil.which("npx"):
            return _gemini_npx(prompt)
    if spec.id == "openclaw" and not shutil.which("openclaw") and spec.npx_package and shutil.which("npx"):
        return ["npx", "-y", spec.npx_package, *spec.build(prompt)[1:]]
    if spec.id == "cursor":
        if shutil.which("cursor-agent"):
            return spec.build(prompt)
        if shutil.which("cursor"):
            return _cursor_legacy(prompt)
    if spec.id == "qwen":
        if shutil.which("qwen"):
            return spec.build(prompt)
        if shutil.which("qwen-code"):
            return _qwen_code(prompt)
    if spec.id in ("freebuff", "codebuff") and not any(shutil.which(b) for b in spec.bins):
        if spec.npx_package and shutil.which("npx"):
            return ["npx", "-y", spec.npx_package]
    if spec.id == "copilot" and not shutil.which("copilot") and spec.npx_package and shutil.which("npx"):
        return ["npx", "-y", spec.npx_package, *spec.build(prompt)[1:]]
    return spec.build(prompt)
