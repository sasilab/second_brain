"""Browse endpoints: recent notes + tag aggregation."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_auth
from app.models.schemas import (
    NoteSummary,
    NotesListResponse,
    TagCount,
    TagsResponse,
)
from app.services import browse


router = APIRouter(prefix="/api", tags=["browse"], dependencies=[Depends(require_auth)])


@router.get("/notes/recent", response_model=NotesListResponse)
def list_recent(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type: Optional[str] = None,
    source: Optional[str] = None,
    tag: Optional[str] = None,
) -> NotesListResponse:
    all_notes = browse.list_all_notes()
    page, total = browse.filter_and_paginate(
        all_notes, type=type, source=source, tag=tag, limit=limit, offset=offset
    )
    summaries = [NoteSummary(**n) for n in browse.to_summary_dicts(page)]
    return NotesListResponse(notes=summaries, total=total, limit=limit, offset=offset)


@router.get("/tags", response_model=TagsResponse)
def list_tags(limit: int = Query(100, ge=1, le=500)) -> TagsResponse:
    items = browse.get_tags(limit=limit)
    return TagsResponse(tags=[TagCount(**t) for t in items])
