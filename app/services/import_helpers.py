"""Helpers for chat-export uploads.

`extract_payload(raw, source)` detects whether the upload is a plain JSON/HTML
file or a ZIP archive and returns the relevant inner content.

For ZIPs we skip directories that Google Takeout includes alongside the actual
Gemini conversation data (`gemini_scheduled_actions_data`, `gemini_gems_data`)
plus macOS metadata (`__MACOSX`).
"""

from __future__ import annotations

import io
import zipfile
from typing import Tuple


SKIP_PATH_PARTS = (
    "gemini_scheduled_actions_data",
    "gemini_gems_data",
    "__macosx",
    ".ds_store",
)

_CHAT_JSON_NAMES = ("conversations.json",)

_GEMINI_ACTIVITY_BASENAMES = (
    "myactivity",        # MyActivity.json / MyActivity.html
    "my activity",       # "My Activity.html" (with space)
)


def is_zip(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == b"PK\x03\x04"


def extract_payload(raw: bytes, source: str) -> Tuple[bytes | str, str]:
    """Return (content, format) where format ∈ {"json", "html"}.

    Raises ValueError if the input is a ZIP but no recognisable conversation
    file is found inside.
    """
    if is_zip(raw):
        return _from_zip(raw, source)
    return _from_plain(raw)


def _from_plain(raw: bytes) -> Tuple[bytes | str, str]:
    head = raw[:64].lstrip().lower()
    if head.startswith(b"<"):
        return raw.decode("utf-8-sig", errors="replace"), "html"
    return raw, "json"


def _path_is_skipped(path: str) -> bool:
    """Skip Google Takeout's non-conversation directories + mac metadata."""
    lower = path.lower().replace("\\", "/")
    parts = lower.split("/")
    for part in parts:
        for skip in SKIP_PATH_PARTS:
            if skip in part:
                return True
    return False


def _from_zip(data: bytes, source: str) -> Tuple[bytes | str, str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"Uploaded file looked like a zip but couldn't be opened: {e}")

    # (zipinfo, format, priority)  — higher priority wins
    candidates: list[tuple[zipfile.ZipInfo, str, int]] = []

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            path = info.filename.replace("\\", "/")
            if _path_is_skipped(path):
                continue

            base = path.rsplit("/", 1)[-1]
            base_lower = base.lower()

            if source == "gemini":
                normalized = base_lower.replace(" ", "")
                matches_activity = any(p.replace(" ", "") in normalized for p in _GEMINI_ACTIVITY_BASENAMES)
                if matches_activity:
                    if base_lower.endswith(".json"):
                        candidates.append((info, "json", 100))
                    elif base_lower.endswith((".html", ".htm")):
                        candidates.append((info, "html", 90))
                # Fallback: any .json under a "Gemini Apps Activity" path
                elif base_lower.endswith(".json") and "gemini" in path.lower():
                    candidates.append((info, "json", 50))
            else:
                # chatgpt / claude both export conversations.json
                if base_lower in _CHAT_JSON_NAMES:
                    candidates.append((info, "json", 100))
                elif base_lower.endswith(".json") and "conversation" in base_lower:
                    candidates.append((info, "json", 60))

        if not candidates:
            expected = (
                "MyActivity.html or MyActivity.json"
                if source == "gemini"
                else "conversations.json"
            )
            raise ValueError(
                f"Couldn't find a {source} conversation file inside the zip "
                f"(expected {expected}). Make sure you uploaded the right archive."
            )

        candidates.sort(key=lambda c: -c[2])
        info, fmt, _ = candidates[0]

        with zf.open(info) as f:
            content = f.read()

    if fmt == "html":
        return content.decode("utf-8-sig", errors="replace"), "html"
    return content, "json"
