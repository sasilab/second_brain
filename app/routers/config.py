"""App configuration endpoint — exposes UI-relevant settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.config import settings
from app.models.schemas import AppConfigResponse


router = APIRouter(prefix="/api", tags=["config"], dependencies=[Depends(require_auth)])


@router.get("/config", response_model=AppConfigResponse)
def get_config() -> AppConfigResponse:
    return AppConfigResponse(
        vault_name=settings.effective_vault_name,
        active_provider=settings.active_provider,
    )
