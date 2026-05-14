"""Auth endpoints: status, first-run setup, login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import auth
from app.models.schemas import (
    AuthStatus,
    LoginRequest,
    LoginResponse,
    PasswordSetupRequest,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatus)
def status_endpoint() -> AuthStatus:
    return AuthStatus(has_password=auth.has_password())


@router.post("/setup", response_model=LoginResponse)
def setup(req: PasswordSetupRequest) -> LoginResponse:
    if auth.has_password():
        raise HTTPException(status_code=400, detail="Password already set")
    try:
        auth.set_password(req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return LoginResponse(token=auth.issue_token())


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    if not auth.has_password():
        raise HTTPException(
            status_code=400,
            detail="No password set. Call /api/auth/setup first.",
        )
    if not auth.verify_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    return LoginResponse(token=auth.issue_token())
