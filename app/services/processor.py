"""AI processing pipeline: classify, tag, summarize, write to vault.

Shared helper `_file_with_analysis()` handles the common branching:
journal/05_Daily → append to today's daily note; everything else → new file in PARA folder.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.services import browse, indexer, linker, vault
from app.services.llm_providers import get_active_provider
from app.services.weather import format_header_suffix


log = logging.getLogger("second_brain.processor")


SYSTEM_PROMPT = """You are organizing notes for a personal knowledge management system using a PARA folder structure.

Given a user's note, respond with a JSON object containing:
- "type": one of "journal", "idea", "reference", "task", "chat", "voice", "image"
- "category": one of "00_Inbox", "01_Projects", "02_Areas", "03_Resources", "05_Daily", "07_References"
  - Use "05_Daily" for personal journal entries, daily reflections, day-to-day captures
  - Use "01_Projects" for work tied to a specific deliverable with a deadline
  - Use "02_Areas" for ongoing areas of life (health, finances, career, family, relationships)
  - Use "03_Resources" for general reference topics worth keeping (techniques, learnings)
  - Use "07_References" for saved articles, links, quotes
  - Use "00_Inbox" only if truly uncertain
- "tags": array of 3-7 short lowercase tags (single words or hyphenated, no '#')
- "summary": 1-3 sentence summary
- "title": short descriptive title (max 8 words, no quotes)

Respond ONLY with the JSON object. No markdown code fences. No prose."""


VALID_TYPES = {"journal", "idea", "reference", "task", "chat", "voice", "image"}
VALID_CATEGORIES = {
    "00_Inbox",
    "01_Projects",
    "02_Areas",
    "03_Resources",
    "04_Archive",
    "05_Daily",
    "07_References",
}


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _sanitize(data: dict) -> dict:
    out: dict[str, Any] = {}
    out["type"] = data.get("type") if data.get("type") in VALID_TYPES else "idea"
    out["category"] = (
        data.get("category") if data.get("category") in VALID_CATEGORIES else "00_Inbox"
    )
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        tags = []
    out["tags"] = [str(t).lower().lstrip("#").strip() for t in tags if str(t).strip()][:7]
    out["summary"] = str(data.get("summary") or "").strip()
    out["title"] = str(data.get("title") or "Untitled note").strip().strip('"')[:120]
    return out


def analyze(content: str) -> dict[str, Any]:
    provider = get_active_provider()
    raw = provider.complete(prompt=content, system=SYSTEM_PROMPT, json_mode=True)
    cleaned = _strip_json_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = {
            "type": "idea",
            "category": "00_Inbox",
            "tags": [],
            "summary": content[:200].strip(),
            "title": content.strip().split("\n", 1)[0][:60] or "Untitled note",
        }
    return _sanitize(data)


def _file_with_analysis(
    analysis: dict,
    *,
    source: str,
    now: datetime,
    new_file_body: str,
    daily_body: str,
    extra_metadata: dict | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Common write step. Daily journal entries APPEND; everything else gets its own file.

    `context` (optional) carries weather/location for this capture. For daily
    appends it goes into the timestamp header; for new files it's stored under
    the `context` key in frontmatter.
    """
    note_id = vault.make_id()
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%S")

    if analysis["type"] == "journal" or analysis["category"] == "05_Daily":
        path = vault.append_daily(
            now,
            daily_body,
            header_suffix=format_header_suffix(context),
        )
        # Re-index the whole daily file under a stable per-day ID so chunks
        # accumulate predictably as more entries are appended.
        try:
            full_meta, full_body = vault.read_note(path)
            indexer.index_note(
                indexer.daily_id_for_date_iso(now.strftime("%Y-%m-%d")),
                full_body,
                full_meta,
                vault.vault_relative(path),
            )
        except Exception as e:
            log.warning("indexing daily file failed (capture still saved): %s", e)
    else:
        metadata: dict[str, Any] = {
            "id": note_id,
            "source": source,
            "type": analysis["type"],
            "date": iso_now,
            "tags": analysis["tags"],
            "summary": analysis["summary"],
            "category": analysis["category"],
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        if context:
            metadata["context"] = context
        folder = vault.resolve_category_dir(analysis["category"])
        filename = vault.make_filename(now, analysis["title"])
        path = vault.write_note(folder, filename, new_file_body, metadata)
        try:
            indexer.index_note(note_id, new_file_body, metadata, vault.vault_relative(path))
        except Exception as e:
            log.warning("indexing new note failed (file still saved): %s", e)

        # Browse cache invalidated before linker runs so update_tag_pages sees the new note.
        browse.invalidate_cache()

        try:
            linker.link_new_note(path)
            linker.update_tag_pages(analysis["tags"])
            linker.link_daily_for_date(now.strftime("%Y-%m-%d"))
        except Exception as e:
            log.warning("linker failed for %s (file still saved): %s", path, e)

    # Browse list cached for 30 s — drop it so the new note shows up immediately
    browse.invalidate_cache()

    return {
        "id": note_id,
        "filed_to": vault.vault_relative(path),
        **analysis,
    }


# ---------- Capture-type entry points ----------


def process_text_capture(
    content: str,
    source: str = "pwa",
    now: datetime | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    analysis = analyze(content)
    return _file_with_analysis(
        analysis,
        source=source,
        now=now,
        new_file_body=f"# {analysis['title']}\n\n{content}\n",
        daily_body=content,
        context=context,
    )


def process_voice_capture(
    transcript: str,
    source: str = "pwa",
    now: datetime | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    analysis = analyze(transcript)
    return _file_with_analysis(
        analysis,
        source=source,
        now=now,
        new_file_body=(
            f"# {analysis['title']}\n\n"
            f"*Transcribed voice note*\n\n"
            f"{transcript}\n"
        ),
        daily_body=f"🎙️ Voice note: {transcript}",
        extra_metadata={"input": "voice"},
        context=context,
    )


def process_image_capture(
    description: str,
    image_relpath: str,
    source: str = "pwa",
    now: datetime | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """`image_relpath` is the path used inside the markdown link, relative to the note's folder."""
    now = now or datetime.now()
    analysis = analyze(description)
    image_embed = f"![Image]({image_relpath})"
    return _file_with_analysis(
        analysis,
        source=source,
        now=now,
        new_file_body=(
            f"# {analysis['title']}\n\n"
            f"{image_embed}\n\n"
            f"## Description\n\n"
            f"{description}\n"
        ),
        daily_body=f"📷 {image_embed}\n{description}",
        extra_metadata={"input": "image", "image": image_relpath},
        context=context,
    )


def process_link_capture(
    url: str,
    page_title: str,
    text: str,
    source: str = "pwa",
    now: datetime | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    analysis_input = (
        f"Title: {page_title}\nURL: {url}\n\nContent:\n{text[:4000]}"
    )
    analysis = analyze(analysis_input)
    # Page title is more accurate than LLM-generated for filename + heading
    if page_title:
        analysis["title"] = page_title[:120]

    excerpt = text[:5000]
    truncated = "\n\n*[excerpt truncated — full content fetched at capture time]*" if len(text) > 5000 else ""

    new_file_body = (
        f"# {analysis['title']}\n\n"
        f"**Source:** [{url}]({url})\n\n"
        f"**Summary:** {analysis['summary']}\n\n"
        f"---\n\n"
        f"{excerpt}{truncated}\n"
    )
    daily_body = f"🔗 [{analysis['title']}]({url})\n{analysis['summary']}"

    return _file_with_analysis(
        analysis,
        source=source,
        now=now,
        new_file_body=new_file_body,
        daily_body=daily_body,
        extra_metadata={"input": "link", "url": url},
        context=context,
    )
