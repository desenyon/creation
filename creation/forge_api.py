"""Forge API — OpenAI-compatible planning endpoint billed to Creation account."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from creation.account.auth import resolve_api_key
from creation.account.store import AccountStore
from creation.services.forge.engine import heuristic_plan

router = APIRouter(prefix="/api/forge/v1", tags=["forge"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "creation-forge-v1"
    messages: List[ChatMessage]
    max_tokens: int = 800


def _auth_user(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
    token = x_api_key.strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = resolve_api_key(token)
    if not user:
        user = AccountStore().ensure_local_account()
    return user


@router.post("/chat/completions")
def chat_completions(body: ChatRequest, authorization: str = Header(default=""), x_api_key: str = Header(default="")):
    user = _auth_user(authorization, x_api_key)
    AccountStore().deduct_credits(user.id, max(25, len(str(body.messages)) // 8), "forge", body.model)

    system = next((m.content for m in body.messages if m.role == "system"), "")
    user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), "")

    backend_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if backend_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=backend_key)
            resp = client.chat.completions.create(
                model=os.environ.get("CREATION_FORGE_MODEL", "gpt-4o-mini"),
                messages=[m.model_dump() for m in body.messages],
                max_tokens=body.max_tokens,
            )
            text = resp.choices[0].message.content or ""
            return _wrap_completion(body.model, text)
        except Exception:
            pass

    text = _heuristic_response(system, user_msg)
    return _wrap_completion(body.model, text)


def _heuristic_response(system: str, user: str) -> str:
    sl = system.lower()
    if "json" in sl and "brand" in sl:
        from creation.services.forge.client import ProductBrand, _fallback_slug

        idea = user.split("Idea:")[-1].strip() if "Idea:" in user else user[:120]
        b = ProductBrand.from_idea(idea)
        return (
            '{"product_name": "%s", "repo_slug": "%s", "tagline": "%s", "linear_project_name": "%s"}'
            % (b.product_name, b.repo_slug, b.tagline, b.linear_project_name)
        )
    if "json" in sl and ("turn" in sl or "follow" in sl):
        return '{"done": false, "refresh_research": false, "run_agent": true, "run_qa": true, "follow_up": "Continue the build — fix failing tests first.", "subtasks": [], "reason": "Heuristic route"}'
    if "json" in sl and "linear" in sl:
        return '{"active_step_index": 1, "step_states": [{"index": 1, "state": "in_progress"}], "new_issues": [], "board_summary": "Forge heuristic board sync."}'
    if "plan" in sl or "numbered" in sl:
        return heuristic_plan(user[:500], 12)
    if "email" in sl:
        return f"Creation progress update\n\n{user[-1200:]}"
    return heuristic_plan(user[:500], 8)


def _wrap_completion(model: str, content: str) -> Dict[str, Any]:
    return {
        "id": "forge-local",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
