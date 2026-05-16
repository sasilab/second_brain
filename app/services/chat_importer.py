"""Write parsed chat exports into the vault.

Each conversation becomes one .md file in 06_Chats/{Source}/, with frontmatter
matching the spec. Idempotent: re-imports skip files that already exist.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from slugify import slugify

from app.config import settings
from app.parsers._common import strip_unsupported_blocks
from app.services import browse, indexer, linker, vault
from app.services.llm_providers import get_active_provider


log = logging.getLogger("second_brain.chat_importer")


SOURCE_FOLDERS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
}


CHAT_ANALYSIS_SYSTEM = """You are organizing imported AI chat transcripts.

Given a conversation, respond with a JSON object:
- "tags": array of 3-7 short lowercase tags (single words or hyphenated, no '#').
   Focus on topics, technologies, concepts. Avoid generic tags like "ai" or "chat".
- "summary": 1-2 sentence summary of what the conversation was about.

Respond ONLY with the JSON object. No code fences, no prose."""


# ---------- helpers ----------


def _strip_json_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _stable_uuid(source: str, identifying_seed: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"second-brain:chat:{source}:{identifying_seed}")


def _format_messages_md(messages: list[dict]) -> str:
    out_lines: list[str] = []
    for msg in messages:
        label = "User" if msg["role"] == "user" else "Assistant"
        content = (msg["content"] or "").rstrip()
        out_lines.append(f"**{label}:**\n\n{content}\n")
    return "\n".join(out_lines)


def _analyze(conv: dict) -> dict:
    """Best-effort LLM tags + summary. Returns {tags: [], summary: ""} on any failure."""
    excerpt_parts = []
    for msg in conv["messages"][:6]:
        label = "User" if msg["role"] == "user" else "Assistant"
        excerpt_parts.append(f"{label}: {(msg['content'] or '')[:600]}")
    prompt = f"Title: {conv['title']}\n\nFirst messages:\n\n" + "\n\n".join(excerpt_parts)

    try:
        provider = get_active_provider()
        raw = provider.complete(prompt=prompt, system=CHAT_ANALYSIS_SYSTEM, json_mode=True)
        data = json.loads(_strip_json_fences(raw))
    except Exception as e:
        log.warning("Chat analysis failed for %r: %s", conv.get("title", "?"), e)
        return {"tags": [], "summary": ""}

    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).lower().lstrip("#").strip() for t in tags if str(t).strip()][:7]
    summary = str(data.get("summary") or "").strip()
    return {"tags": tags, "summary": summary}


# ---------- main entry point ----------


def iter_import(
    conversations: list[dict],
    *,
    source: str,
    process: bool = True,
    do_index: bool = True,
) -> Iterator[dict]:
    """Generator that imports conversations one at a time and yields progress events.

    Event shapes:
      {"phase": "started", "total": N}
      {"phase": "progress", "index": i, "total": N, "title": str,
       "imported": .., "skipped": .., "failed": .., "outcome": "imported"|"skipped"|"failed"}
      {"phase": "done", "total": N, "imported": .., "skipped": .., "failed": ..}
    """
    if source not in SOURCE_FOLDERS:
        raise ValueError(f"Unknown chat source: {source!r}")

    folder = settings.chats_dir / SOURCE_FOLDERS[source]
    folder.mkdir(parents=True, exist_ok=True)

    total = len(conversations)
    yield {"phase": "started", "total": total}

    imported = 0
    skipped = 0
    failed = 0

    for i, conv in enumerate(conversations):
        title = (conv or {}).get("title", "?") if isinstance(conv, dict) else "?"
        outcome: str
        try:
            outcome = _import_one(
                conv, source=source, folder=folder, process=process, do_index=do_index
            )
        except Exception as e:
            log.warning("Import failed for %r: %s", title, e)
            outcome = "failed"

        if outcome == "imported":
            imported += 1
        elif outcome == "skipped":
            skipped += 1
        else:
            failed += 1

        yield {
            "phase": "progress",
            "index": i + 1,
            "total": total,
            "title": (title or "?")[:80],
            "outcome": outcome,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
        }

    # Tag pages are expensive — regenerate once at the end of the import instead of per-note.
    if imported > 0:
        try:
            linker.regenerate_all_tag_indexes()
        except Exception as e:
            log.warning("Tag index regeneration failed after import: %s", e)

    yield {
        "phase": "done",
        "total": total,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
    }


def import_conversations(
    conversations: list[dict],
    *,
    source: str,
    process: bool = True,
    limit: int | None = None,
    do_index: bool = True,
) -> dict[str, int]:
    """Sync convenience wrapper: drains iter_import and returns the final counts."""
    iterable = conversations if limit is None else conversations[:limit]
    final: dict | None = None
    for event in iter_import(iterable, source=source, process=process, do_index=do_index):
        if event["phase"] == "done":
            final = event
    if final is None:
        return {"total": 0, "imported": 0, "skipped": 0, "failed": 0}
    return {
        "total": final["total"],
        "imported": final["imported"],
        "skipped": final["skipped"],
        "failed": final["failed"],
    }


def _import_one(
    conv: dict,
    *,
    source: str,
    folder: Path,
    process: bool,
    do_index: bool,
) -> str:
    title = (conv.get("title") or "Untitled chat").strip() or "Untitled chat"
    date: datetime = conv.get("date") or datetime.now()
    messages = conv.get("messages") or []
    if not messages:
        return "skipped"

    source_id = str(conv.get("source_id") or "").strip()
    iso_date = date.strftime("%Y-%m-%d")

    seed = source_id or f"{title}|{date.isoformat()}"
    note_uuid = _stable_uuid(source, seed)
    short_hash = note_uuid.hex[:6]

    slug = slugify(title)[:50] or "chat"
    filename = f"{iso_date}-{slug}-{short_hash}.md"
    path = folder / filename

    if path.exists():
        return "skipped"

    analysis = _analyze(conv) if process else {"tags": [], "summary": ""}

    metadata: dict[str, Any] = {
        "id": str(note_uuid),
        "source": source,
        "type": "chat",
        "date": date.strftime("%Y-%m-%dT%H:%M:%S"),
        "tags": analysis["tags"],
        "summary": analysis["summary"],
        "category": f"06_Chats/{folder.name}",
        "original_title": title,
    }
    if source_id:
        metadata["original_id"] = source_id

    body = f"# {title}\n\n{_format_messages_md(messages)}"
    vault.write_note(folder, filename, body, metadata)

    if do_index:
        try:
            indexer.index_note(str(note_uuid), body, metadata, vault.vault_relative(path))
        except Exception as e:
            log.warning("Indexing failed for chat %s: %s", filename, e)

    browse.invalidate_cache()

    try:
        linker.link_new_note(path)
    except Exception as e:
        log.warning("Linking failed for chat %s: %s", filename, e)

    return "imported"


# ---------- post-hoc cleanup ----------


def clean_existing_chat_notes() -> dict[str, int]:
    """Strip 'block not supported' placeholders from already-imported chat notes.

    Walks vault/06_Chats/, rewrites notes whose body changed, and returns counts.
    Run `cli.py reindex` afterwards to refresh embeddings — the body changed but
    we don't reindex inline to keep this fast and avoid surprise side effects.
    """
    scanned = 0
    cleaned = 0
    errors = 0

    chats_root = settings.chats_dir
    if not chats_root.exists():
        return {"scanned": 0, "cleaned": 0, "errors": 0}

    for md_path in chats_root.rglob("*.md"):
        scanned += 1
        try:
            meta, body = vault.read_note(md_path)
        except Exception as e:
            log.warning("clean_existing_chat_notes read failed for %s: %s", md_path, e)
            errors += 1
            continue

        # Cheap skip: if the placeholder text isn't present, nothing to do.
        if "not supported on your current device" not in (body or "").lower():
            continue

        new_body = strip_unsupported_blocks(body)
        if new_body and not new_body.endswith("\n"):
            new_body += "\n"

        if new_body == body:
            continue

        try:
            import frontmatter  # local import — only needed for this rare operation

            post = frontmatter.Post(new_body, **{k: v for k, v in meta.items()})
            md_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            cleaned += 1
        except Exception as e:
            log.warning("clean_existing_chat_notes write failed for %s: %s", md_path, e)
            errors += 1

    if cleaned:
        browse.invalidate_cache()

    return {"scanned": scanned, "cleaned": cleaned, "errors": errors}
