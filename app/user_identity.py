import os
from urllib.parse import unquote

from fastapi import HTTPException


USERNAME_COOKIE_NAME = "username"
SESSION_USERNAME_KEY = "project_history_username"


def normalize_username(value: str | None) -> str | None:
    username = unquote(value or "").strip()
    return username or None


def is_test_mode() -> bool:
    configured = os.getenv("PARTSHELF_TEST_MODE")
    if configured is None:
        return True
    return configured.strip().lower() in {"1", "true", "yes", "on"}


def require_project_history_username(session) -> None:
    if not is_test_mode() and not session.info.get(SESSION_USERNAME_KEY):
        raise HTTPException(
            status_code=400,
            detail="A non-empty username cookie is required for project component changes",
        )
