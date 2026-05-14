"""Browse: list / filter notes from the vault.

Walks the vault directly. A short in-memory cache (30 s) keeps repeated browse
requests cheap; the cache is invalidated explicitly after every capture (see
processor.py) so freshly-saved notes appear immediately.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter
from typing import Any

from app.config import settings
from app.services import vault as vault_svc


CACHE_TTL_SECONDS = 30
SKIP_TOP_LEVEL = {"_meta", "Templates"}

_cache_lock = threading.Lock()
_cache_notes: list[dict] | None = None
_cache_at: float = 0.0


def invalidate_cache() -> None:
    global _cache_notes, _cache_at
    with _cache_lock:
        _cache_notes = None
        _cache_at = 0.0


def list_all_notes() -> list[dict]:
    """Return all notes' summary dicts, sorted newest-first.

    Cached for CACHE_TTL_SECONDS. Safe to call from request handlers.
    """
    global _cache_notes, _cache_at
    with _cache_lock:
        now = time.time()
        if _cache_notes is not None and now - _cache_at < CACHE_TTL_SECONDS:
            return _cache_notes
        notes = _scan_vault()
        notes.sort(key=_sort_key, reverse=True)
        _cache_notes = notes
        _cache_at = now
        return notes


def get_tags(limit: int = 100) -> list[dict]:
    counter: Counter[str] = Counter()
    for n in list_all_notes():
        for t in n.get("tags") or []:
            t = str(t).strip().lower()
            if t:
                counter[t] += 1
    return [{"tag": t, "count": c} for t, c in counter.most_common(limit)]


# ---------- internals ----------


def _scan_vault() -> list[dict]:
    out: list[dict] = []
    if not settings.vault_root.exists():
        return out
    for md_path in settings.vault_root.rglob("*.md"):
        rel = md_path.relative_to(settings.vault_root)
        parts = rel.parts
        if parts and parts[0] in SKIP_TOP_LEVEL:
            continue
        try:
            metadata, content = vault_svc.read_note(md_path)
        except Exception:
            continue

        title = (
            _extract_h1(content)
            or str(metadata.get("original_title") or "").strip()
            or md_path.stem
        )

        tags = metadata.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            tags = []

        out.append(
            {
                "id": str(metadata.get("id") or ""),
                "path": vault_svc.vault_relative(md_path),
                "title": str(title)[:140],
                "type": str(metadata.get("type") or ""),
                "source": str(metadata.get("source") or ""),
                "category": str(metadata.get("category") or ""),
                "date": str(metadata.get("date") or ""),
                "summary": str(metadata.get("summary") or ""),
                "tags": [str(t) for t in tags],
                # Used internally for sort fallback only
                "_mtime": _safe_mtime(md_path),
            }
        )
    return out


def _extract_h1(content: str) -> str | None:
    for line in content.splitlines()[:12]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            return s[2:].strip()
        if not s.startswith("#"):
            return None  # body started with no H1
    return None


def _safe_mtime(p) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _sort_key(note: dict) -> tuple:
    """Sort by frontmatter date (string compare works for ISO 8601), file mtime as tiebreaker."""
    return (note.get("date", ""), note.get("_mtime", 0.0))


def filter_and_paginate(
    notes: list[dict],
    *,
    type: str | None,
    source: str | None,
    tag: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    filtered: list[dict] = notes
    if type:
        filtered = [n for n in filtered if n.get("type") == type]
    if source:
        filtered = [n for n in filtered if n.get("source") == source]
    if tag:
        tag_lower = tag.strip().lower()
        filtered = [
            n for n in filtered if any(str(t).lower() == tag_lower for t in n.get("tags") or [])
        ]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    return page, total


def to_summary_dicts(notes: list[dict]) -> list[dict]:
    """Strip internal-only fields (e.g. _mtime) before returning to clients."""
    return [{k: v for k, v in n.items() if not k.startswith("_")} for n in notes]
