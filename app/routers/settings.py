"""Settings endpoints — runtime overrides for provider keys, models, vault name."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_auth
from app.config import settings
from app.models.schemas import (
    ProviderInfo,
    ProvidersResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.services import llm_providers, runtime_settings


router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])


VALID_PROVIDERS = {"openai", "anthropic", "google"}


def _current_settings() -> SettingsResponse:
    return SettingsResponse(
        active_provider=settings.active_provider,
        openai_model=settings.openai_model,
        anthropic_model=settings.anthropic_model,
        google_model=settings.google_model,
        vault_name=settings.effective_vault_name,
        openai_configured=bool(settings.openai_api_key),
        anthropic_configured=bool(settings.anthropic_api_key),
        google_configured=bool(settings.google_api_key),
    )


@router.get("", response_model=SettingsResponse)
def get_settings_endpoint() -> SettingsResponse:
    return _current_settings()


@router.put("", response_model=SettingsResponse)
def update_settings(req: SettingsUpdateRequest) -> SettingsResponse:
    updates = req.model_dump(exclude_unset=True)
    if "active_provider" in updates and updates["active_provider"] not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"active_provider must be one of {sorted(VALID_PROVIDERS)}",
        )
    runtime_settings.update(updates)
    llm_providers.reset_clients()
    return _current_settings()


@router.get("/providers", response_model=ProvidersResponse)
def list_providers_endpoint() -> ProvidersResponse:
    return ProvidersResponse(
        providers=[ProviderInfo(**p) for p in llm_providers.list_providers()]
    )
