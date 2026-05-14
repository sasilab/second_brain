"""Single-user password auth. Bcrypt hash in _meta/config.json + in-memory session tokens."""

from __future__ import annotations

import json
import secrets
from typing import Optional

import bcrypt
from fastapi import Header, HTTPException, status

from app.config import settings


_active_tokens: set[str] = set()


def _load_config() -> dict:
    if settings.config_json_path.exists():
        try:
            return json.loads(settings.config_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_config(data: dict) -> None:
    settings.meta_dir.mkdir(parents=True, exist_ok=True)
    settings.config_json_path.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def has_password() -> bool:
    return bool(_load_config().get("password_hash"))


def set_password(password: str) -> None:
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    config = _load_config()
    config["password_hash"] = hashed.decode("utf-8")
    _save_config(config)


def verify_password(password: str) -> bool:
    stored = _load_config().get("password_hash")
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return False


def issue_token() -> str:
    token = secrets.token_urlsafe(32)
    _active_tokens.add(token)
    return token


def revoke_token(token: str) -> None:
    _active_tokens.discard(token)


def bootstrap_from_env() -> None:
    """If APP_PASSWORD is set in .env and no password is configured yet, seed it."""
    if not has_password() and settings.app_password:
        set_password(settings.app_password)


def require_auth(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer ") :]
    if token not in _active_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return token
