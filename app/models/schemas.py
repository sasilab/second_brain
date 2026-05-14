"""Pydantic request/response models for all routers."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    has_password: bool


class PasswordSetupRequest(BaseModel):
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


class CaptureContext(BaseModel):
    """Optional ambient context attached to a capture by the client (the PWA)."""
    lat: float | None = None
    lon: float | None = None


class TextCaptureRequest(BaseModel):
    content: str
    context: CaptureContext | None = None


class CaptureResponse(BaseModel):
    id: str
    filed_to: str
    type: str
    category: str
    tags: list[str]
    summary: str
    title: str


class VoiceCaptureResponse(CaptureResponse):
    transcript: str


class ImageCaptureResponse(CaptureResponse):
    description: str
    image_path: str  # vault-relative path to the saved attachment


class LinkCaptureRequest(BaseModel):
    url: str
    context: CaptureContext | None = None


class LinkCaptureResponse(CaptureResponse):
    url: str
    page_title: str


# ---------- Search / Ask ----------


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    type: str | None = None
    source: str | None = None
    category: str | None = None


class SearchResultItem(BaseModel):
    id: str
    title: str
    path: str
    snippet: str
    score: float
    type: str = ""
    source: str = ""
    date: str = ""
    category: str = ""
    tags: list[str] = []


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


class AskRequest(BaseModel):
    question: str
    limit: int = 6


class AskResponse(BaseModel):
    answer: str
    sources: list[SearchResultItem]


# ---------- Chat import ----------


class ImportResponse(BaseModel):
    source: str
    total: int
    imported: int
    skipped: int
    failed: int


# ---------- Browse / Config ----------


class AppConfigResponse(BaseModel):
    vault_name: str
    active_provider: str


class NoteSummary(BaseModel):
    id: str
    path: str
    title: str
    type: str = ""
    source: str = ""
    category: str = ""
    date: str = ""
    summary: str = ""
    tags: list[str] = []


class NotesListResponse(BaseModel):
    notes: list[NoteSummary]
    total: int
    limit: int
    offset: int


class TagCount(BaseModel):
    tag: str
    count: int


class TagsResponse(BaseModel):
    tags: list[TagCount]


# ---------- Settings ----------


class SettingsResponse(BaseModel):
    active_provider: str
    openai_model: str
    anthropic_model: str
    google_model: str
    vault_name: str
    openai_configured: bool
    anthropic_configured: bool
    google_configured: bool


class SettingsUpdateRequest(BaseModel):
    active_provider: str | None = None
    openai_model: str | None = None
    anthropic_model: str | None = None
    google_model: str | None = None
    vault_name: str | None = None
    # Keys are write-only — they're never echoed back in GET responses.
    # Send "" to clear an override (falls back to .env value).
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None


class ProviderInfo(BaseModel):
    name: str
    display: str
    configured: bool
    model: str


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]
