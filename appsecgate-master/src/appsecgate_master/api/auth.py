"""Проектная Bearer-аутентификация master API."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from appsecgate_master.api.config import MasterSettings

_BEARER = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)] = None,
) -> str:
    """Вернуть project_key, связанный с API-ключом."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    settings: MasterSettings = request.app.state.settings
    for project, api_key in settings.api_keys.items():
        if secrets.compare_digest(credentials.credentials, api_key):
            return project
    raise _unauthorized()


def authorize_project(authenticated: str, requested: str) -> None:
    if authenticated != requested:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key is not authorized for this project",
        )
