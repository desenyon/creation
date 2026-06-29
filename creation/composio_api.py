"""FastAPI routes for Composio Auth Config onboarding."""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from creation.config import load_secrets
from creation.integrations.composio_connections import ComposioConnectionManager

router = APIRouter(prefix="/api/composio", tags=["composio"])


class ConnectRequest(BaseModel):
    toolkit: str
    callback_url: str


def _choose_local_folder() -> str:
    system = platform.system()
    if system == "Darwin":
        command = [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Choose a project folder for Creation")',
        ]
    elif system == "Windows":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$dialog.Description = 'Choose a project folder for Creation'; "
                "if ($dialog.ShowDialog() -eq 'OK') { $dialog.SelectedPath }"
            ),
        ]
    elif shutil.which("zenity"):
        command = [
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Choose a project folder for Creation",
        ]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory", ".", "Choose a project folder for Creation"]
    else:
        raise RuntimeError("No native folder picker is available on this system")

    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode:
        return ""
    path = result.stdout.strip()
    if len(path) > 1:
        path = path.rstrip("/\\")
    return path


def onboarding_status() -> Dict[str, object]:
    secrets = load_secrets()
    core = {
        "tavily": bool(secrets.tavily_api_key.strip()),
        "nebius": bool(secrets.nebius_api_key.strip()),
        "composio": bool(secrets.composio_api_key.strip()),
        "composio_user_id": bool(secrets.composio_user_id.strip()),
    }
    auth_configs = {
        slug: bool(spec.auth_config_id)
        for slug, spec in ComposioConnectionManager(secrets).specs().items()
    }
    connections = {"ready": False, "connections": {}}
    if all(core.values()) and all(auth_configs.values()):
        connections = ComposioConnectionManager(secrets).status()
    complete = all(core.values()) and all(auth_configs.values()) and bool(connections.get("ready"))
    mem0 = {
        "enabled": bool(secrets.mem0_enabled),
        "configured": bool(secrets.mem0_api_key.strip()),
        "ready": bool(secrets.mem0_enabled and secrets.mem0_api_key.strip()),
    }
    return {
        "complete": complete,
        "configured": all(core.values()),
        "core": core,
        "mem0": mem0,
        "auth_configs": auth_configs,
        "connections": connections.get("connections", {}),
    }


@router.get("/onboarding")
def get_onboarding_status() -> Dict[str, object]:
    return onboarding_status()


@router.post("/folder")
def choose_folder() -> Dict[str, str]:
    try:
        return {"path": _choose_local_folder()}
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(408, "Folder selection timed out") from exc
    except Exception as exc:
        raise HTTPException(500, f"Could not open the folder selector: {exc}") from exc


@router.get("/connections")
def connection_status() -> Dict[str, object]:
    try:
        return ComposioConnectionManager(load_secrets()).status()
    except Exception as exc:
        raise HTTPException(502, f"Could not check Composio connections: {exc}") from exc


@router.post("/connect")
def connect(body: ConnectRequest) -> Dict[str, str]:
    try:
        return ComposioConnectionManager(load_secrets()).connect_link(
            body.toolkit, body.callback_url
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Could not create Composio Connect Link: {exc}") from exc


def ensure_composio_ready() -> None:
    state = ComposioConnectionManager(load_secrets()).status()
    if state.get("ready"):
        return
    connections = state.get("connections", {})
    pending = [
        slug.title()
        for slug, item in connections.items()
        if not item.get("configured") or not item.get("connected")
    ]
    raise HTTPException(
        400,
        "Connect all required Composio integrations before starting: " + ", ".join(pending),
    )
