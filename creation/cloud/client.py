"""HTTP client for Creation Cloud (Vercel-hosted account + Forge)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

DEFAULT_CLOUD_URL = "https://creation.dev"


def cloud_base_url() -> str:
    from creation.config import load_secrets

    sec = load_secrets()
    url = (sec.cloud_api_url or os.environ.get("CREATION_CLOUD_URL") or "").strip()
    return (url or DEFAULT_CLOUD_URL).rstrip("/")


def cloud_enabled() -> bool:
    from creation.config import load_secrets

    sec = load_secrets()
    return bool((sec.cloud_api_url or os.environ.get("CREATION_CLOUD_URL") or "").strip())


def _headers(api_key: str = "") -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def cloud_register(email: str, password: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{cloud_base_url()}/api/account/register",
            json={"email": email, "password": password},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


def cloud_login(email: str, password: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{cloud_base_url()}/api/account/login",
            json={"email": email, "password": password},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


def cloud_me(api_key: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{cloud_base_url()}/api/account/me", headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def cloud_update_credentials(api_key: str, **fields: Optional[str]) -> Dict[str, Any]:
    body = {k: v for k, v in fields.items() if v is not None}
    with httpx.Client(timeout=30.0) as client:
        r = client.put(
            f"{cloud_base_url()}/api/account/credentials",
            json=body,
            headers=_headers(api_key),
        )
        r.raise_for_status()
        return r.json()


def cloud_forge_chat(api_key: str, messages: list, *, model: str = "creation-forge-v1", max_tokens: int = 800) -> str:
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{cloud_base_url()}/api/forge/v1/chat/completions",
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            headers=_headers(api_key),
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
