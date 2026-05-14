"""Gemini / Google Takeout parser.

Gemini exports are inconsistent depending on which export route the user used.
We handle four shapes:
  1. JSON array of conversation objects with `messages`/`turns`
  2. {conversations: [...]} wrapper
  3. Google "My Activity" JSON array (each item is a single user query)
  4. Google "My Activity" HTML (the default Takeout format) — see parse_html()
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.parsers._common import NormalizedConversation, load_json, parse_date


_USER_ROLES = {"user", "human"}
_ASSISTANT_ROLES = {"assistant", "model", "bard", "gemini"}


def parse(data: bytes | str | list | dict) -> list[NormalizedConversation]:
    raw = load_json(data)

    if isinstance(raw, dict):
        raw = (
            raw.get("conversations")
            or raw.get("Conversations")
            or raw.get("data")
            or raw.get("items")
            or raw.get("activities")
            or []
        )
    if not isinstance(raw, list):
        raise ValueError("Gemini export: expected a JSON array (or an object containing one)")

    out: list[NormalizedConversation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            normalized = _parse_item(item)
            if normalized and normalized["messages"]:
                out.append(normalized)
        except Exception:
            continue
    return out


def _parse_item(item: dict) -> NormalizedConversation | None:
    # "My Activity" item: has a `header` of "Bard"/"Gemini" and a single title (the user query)
    header = (item.get("header") or "").lower()
    if header in ("bard", "gemini") and "messages" not in item and "turns" not in item:
        title = (item.get("title") or "").strip()
        # Strip the typical "Asked: " / "Said " / "Searched for: " prefixes
        for prefix in ("Asked: ", "Said: ", "Searched for: ", "Prompted: "):
            if title.startswith(prefix):
                title = title[len(prefix):]
                break
        if not title:
            return None
        date = parse_date(item.get("time"))
        return {
            "source_id": str(item.get("titleUrl", ""))[:128],
            "title": title[:120],
            "date": date,
            "messages": [{"role": "user", "content": title}],
        }

    # Conversation-style
    title = (item.get("title") or item.get("name") or "Untitled chat").strip() or "Untitled chat"
    source_id = str(item.get("id") or item.get("uuid") or item.get("conversation_id") or "")
    date = (
        parse_date(item.get("create_time"))
        or parse_date(item.get("created_at"))
        or parse_date(item.get("createdAt"))
        or parse_date(item.get("time"))
    )

    raw_messages = item.get("messages") or item.get("turns") or []
    if not isinstance(raw_messages, list):
        return None

    messages = []
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        role_raw = (msg.get("role") or msg.get("author") or msg.get("sender") or "").lower()
        if role_raw in _ASSISTANT_ROLES:
            role = "assistant"
        elif role_raw in _USER_ROLES:
            role = "user"
        else:
            continue

        content: Any = msg.get("content") or msg.get("text") or msg.get("message") or ""
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    parts.append(str(c.get("text") or c.get("content") or ""))
                else:
                    parts.append(str(c))
            content = "\n\n".join(p for p in parts if p)
        content = str(content).strip()
        if not content:
            continue
        messages.append({"role": role, "content": content})

    return {
        "source_id": source_id,
        "title": title,
        "date": date,
        "messages": messages,
    }


# ---------- HTML "My Activity" parser ----------


_ACTIVITY_DATE_FORMATS = (
    "%b %d, %Y, %I:%M:%S %p UTC",     # Google sometimes uses a narrow no-break space
    "%b %d, %Y, %I:%M:%S %p UTC",
    "%b %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %I:%M %p UTC",
    "%b %d, %Y, %I:%M %p UTC",
    "%b %d, %Y, %H:%M:%S UTC",
    "%B %d, %Y, %I:%M:%S %p UTC",
    "%B %d, %Y, %I:%M:%S %p UTC",
)

_DATE_HINT = re.compile(
    r"^[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}(?::\d{2})?"
)

_ACTION_PREFIXES = (
    "prompted",
    "asked",
    "searched for",
    "searched",
    "said",
    "told",
    "used gemini",
)

_PRODUCT_KEYWORDS = ("gemini", "bard")


def parse_html(html: str | bytes) -> list[NormalizedConversation]:
    """Parse Google Takeout's My Activity HTML for Gemini/Bard entries."""
    if isinstance(html, bytes):
        html = html.decode("utf-8-sig", errors="replace")

    # html.parser is slower than lxml but is in the stdlib — fine for personal use.
    soup = BeautifulSoup(html, "html.parser")

    out: list[NormalizedConversation] = []
    for cell in soup.select(".outer-cell"):
        try:
            item = _parse_outer_cell(cell)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


def _parse_outer_cell(cell: Tag) -> NormalizedConversation | None:
    header = cell.select_one(".header-cell")
    product = header.get_text(separator=" ", strip=True).lower() if header else ""
    if not any(k in product for k in _PRODUCT_KEYWORDS):
        return None

    # Main body is the .content-cell that is NOT the right-aligned metadata column
    bodies = cell.select(".content-cell")
    body: Tag | None = None
    for b in bodies:
        classes = b.get("class") or []
        if "mdl-typography--text-right" in classes:
            continue
        body = b
        break
    if body is None:
        return None

    text = body.get_text(separator="\n").strip()
    if not text:
        return None

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None

    date: datetime | None = None
    content_lines: list[str] = []
    for line in lines:
        if date is None and _DATE_HINT.match(line):
            d = _parse_activity_date(line)
            if d:
                date = d
                continue
        content_lines.append(line)

    content = " ".join(content_lines).strip()
    if not content:
        return None

    # Strip the leading action verb ("Prompted", "Asked: …", …)
    lowered = content.lower()
    for prefix in _ACTION_PREFIXES:
        if lowered.startswith(prefix):
            rest = content[len(prefix):]
            content = rest.lstrip(": ").strip()
            break

    if len(content) < 2:
        return None

    return {
        "source_id": "",
        "title": content[:120],
        "date": date,
        "messages": [{"role": "user", "content": content}],
    }


def _parse_activity_date(s: str) -> datetime | None:
    s = s.strip()
    for fmt in _ACTIVITY_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Last-ditch ISO attempt
    return parse_date(s)
