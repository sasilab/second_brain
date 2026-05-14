"""Shared helpers for chat-export parsers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypedDict


class NormalizedMessage(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class NormalizedConversation(TypedDict):
    source_id: str            # original conversation ID from the export (may be empty)
    title: str
    date: datetime | None     # creation time, if known
    messages: list[NormalizedMessage]


def load_json(data: bytes | str | dict | list) -> Any:
    """Accept bytes/str/already-parsed JSON. Always returns the parsed value."""
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, bytes):
        # ChatGPT exports occasionally have a UTF-8 BOM
        data = data.decode("utf-8-sig", errors="replace")
    return json.loads(data)


_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_date(value: Any) -> datetime | None:
    """Coerce Unix timestamp / ISO 8601 / common strings → naive datetime, or None."""
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            # Heuristic: treat very large numbers as milliseconds
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # ISO with Z → +00:00 for fromisoformat
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s[: len(fmt) + 6 if "%f" in fmt else len(fmt)], fmt)
            except ValueError:
                continue
    return None
