"""Creation account authentication helpers."""

from __future__ import annotations

from typing import Optional, Tuple

from creation.account.store import AccountStore, AccountUser


def login(email: str, password: str) -> Tuple[AccountUser, str]:
    return AccountStore().login(email, password)


def register(email: str, password: str) -> AccountUser:
    return AccountStore().register(email, password)


def resolve_api_key(api_key: str) -> Optional[AccountUser]:
    if not api_key.strip():
        return None
    return AccountStore().get_by_api_key(api_key)


def resolve_session(token: str) -> Optional[AccountUser]:
    if not token.strip():
        return None
    return AccountStore().get_by_session(token)
