"""Vault read/write helpers. Handles markdown + YAML frontmatter and daily-note appending."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import frontmatter
from slugify import slugify

from app.config import settings


# Folder → 24-bit RGB int (Obsidian's graph color format)
GRAPH_COLOR_GROUPS: tuple[tuple[str, int], ...] = (
    ("path:05_Daily",          0x3a7aff),  # blue
    ("path:06_Chats/ChatGPT",  0x4caf50),  # green
    ("path:06_Chats/Claude",   0x9c27b0),  # purple
    ("path:06_Chats/Gemini",   0xff9800),  # orange
    ("path:01_Projects",       0xef4444),  # red
    ("path:02_Areas",          0xfbc02d),  # yellow
    ("path:03_Resources",      0x00bfa5),  # teal
    ("path:07_References",     0x9e9e9e),  # gray
    ("path:Tags",              0xec407a),  # pink
)


def make_id() -> str:
    return str(uuid.uuid4())


def write_note(folder: Path, filename: str, content: str, metadata: dict) -> Path:
    """Write a new note. Overwrites if filename collides — caller controls naming."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    post = frontmatter.Post(content, **metadata)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


def read_note(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    return dict(post.metadata), post.content


def make_filename(date: datetime, title: str) -> str:
    iso = date.strftime("%Y-%m-%d")
    slug = slugify(title) or "note"
    # cap slug length to keep paths sane
    slug = slug[:60]
    return f"{iso}-{slug}.md"


CATEGORY_DIRS = {
    "00_Inbox": "inbox_dir",
    "01_Projects": "projects_dir",
    "02_Areas": "areas_dir",
    "03_Resources": "resources_dir",
    "04_Archive": "archive_dir",
    "05_Daily": "daily_dir",
    "07_References": "references_dir",
}


def resolve_category_dir(category: str) -> Path:
    attr = CATEGORY_DIRS.get(category)
    if attr is None:
        return settings.inbox_dir
    return getattr(settings, attr)


def append_daily(
    date: datetime,
    body: str,
    prefix: str = "",
    header_suffix: str = "",
) -> Path:
    """
    Append a timestamped entry to the daily note for the given date.
    Creates the file with a header if it doesn't exist.

    `header_suffix` (optional) is appended to the timestamp line after a `· `
    separator — used for weather/location: ## 16:26 · ☀️ 22°C, partly cloudy · Coburg
    """
    folder = settings.daily_dir
    folder.mkdir(parents=True, exist_ok=True)
    iso_date = date.strftime("%Y-%m-%d")
    path = folder / f"{iso_date}.md"

    if not path.exists():
        long_date = date.strftime("%A, %B %d, %Y")
        header = (
            "---\n"
            f"date: {iso_date}\n"
            "type: daily\n"
            "tags: [journal]\n"
            "---\n\n"
            f"# {long_date}\n\n"
        )
        path.write_text(header, encoding="utf-8")

    timestamp = date.strftime("%H:%M")
    if header_suffix:
        entry = f"## {timestamp} · {header_suffix}\n"
    else:
        entry = f"## {timestamp}\n"
    if prefix:
        entry += f"{prefix} "
    entry += body.rstrip() + "\n\n"

    with path.open("a", encoding="utf-8") as f:
        f.write(entry)

    return path


def ensure_obsidian_graph_config() -> None:
    """Write .obsidian/graph.json with folder→color groups, IF the file doesn't already exist.

    Obsidian creates .obsidian/ on first open. We only seed it; we never overwrite
    a config the user (or Obsidian itself) has already written.
    """
    obs_dir = settings.vault_root / ".obsidian"
    obs_dir.mkdir(parents=True, exist_ok=True)
    graph_path = obs_dir / "graph.json"
    if graph_path.exists():
        return

    color_groups = [
        {"query": query, "color": {"a": 1, "rgb": rgb}}
        for query, rgb in GRAPH_COLOR_GROUPS
    ]
    config = {
        "collapse-filter": True,
        "search": "",
        "showTags": True,
        "showAttachments": False,
        "hideUnresolved": False,
        "showOrphans": True,
        "collapse-color-groups": False,
        "colorGroups": color_groups,
        "collapse-display": False,
        "showArrow": False,
        "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1,
        "collapse-forces": False,
        "centerStrength": 0.5,
        "repelStrength": 10,
        "linkStrength": 1,
        "linkDistance": 250,
        "scale": 1,
        "close": True,
    }
    graph_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def vault_relative(path: Path) -> str:
    try:
        rel = path.relative_to(settings.vault_root)
    except ValueError:
        return str(path)
    return str(rel).replace("\\", "/")
