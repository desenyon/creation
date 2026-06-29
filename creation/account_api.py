"""Account API — single sign-on, credits, and Relay credentials."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from creation.account.auth import login, register, resolve_api_key
from creation.account.store import AccountStore
from creation.config import load_secrets, save_secrets

router = APIRouter(prefix="/api/account", tags=["account"])


class RegisterBody(BaseModel):
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class CredentialsBody(BaseModel):
    github_token: Optional[str] = None
    linear_api_key: Optional[str] = None
    linear_team_id: Optional[str] = None
    notify_email: Optional[str] = None


def _user_from_header(authorization: str = Header(default=""), x_api_key: str = Header(default="")) -> object:
    token = x_api_key.strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = resolve_api_key(token)
    if not user:
        raise HTTPException(401, "Invalid API key — run `creation login`")
    return user


@router.post("/register")
def api_register(body: RegisterBody):
    try:
        user = register(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    secrets = load_secrets()
    secrets.account_email = user.email
    secrets.account_token = user.api_key
    save_secrets(secrets)
    return AccountStore().export_profile(user)


@router.post("/login")
def api_login(body: LoginBody):
    try:
        user, _session = login(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    secrets = load_secrets()
    secrets.account_email = user.email
    secrets.account_token = user.api_key
    save_secrets(secrets)
    return AccountStore().export_profile(user)


@router.get("/me")
def api_me(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
    user = _user_from_header(authorization, x_api_key)
    return AccountStore().export_profile(user)  # type: ignore[arg-type]


@router.put("/credentials")
def api_credentials(body: CredentialsBody, authorization: str = Header(default=""), x_api_key: str = Header(default="")):
    user = _user_from_header(authorization, x_api_key)
    updated = AccountStore().update_credentials(
        user.id,  # type: ignore[union-attr]
        github_token=body.github_token,
        linear_api_key=body.linear_api_key,
        linear_team_id=body.linear_team_id,
        notify_email=body.notify_email,
    )
    secrets = load_secrets()
    if body.github_token is not None:
        secrets.github_token = body.github_token
    if body.linear_api_key is not None:
        secrets.linear_api_key = body.linear_api_key
    if body.linear_team_id is not None:
        secrets.linear_team_id = body.linear_team_id
    if body.notify_email is not None:
        secrets.notify_email = body.notify_email
    save_secrets(secrets)
    return AccountStore().export_profile(updated)


# Legacy composio onboarding shim for old splash.js until studio UI loads
legacy = APIRouter(prefix="/api/composio", tags=["legacy"])


@legacy.get("/onboarding")
def legacy_onboarding():
    secrets = load_secrets()
    return {
        "ready": bool(secrets.account_token),
        "account_email": secrets.account_email,
        "message": "Creation account ready" if secrets.account_token else "Run creation login",
    }
