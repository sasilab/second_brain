"""Build a Map of Content (MOC) hub note for a topic description.

Pipeline:
  1. Split the topic on commas / dashes / semicolons → search terms
  2. ChromaDB search per term, dedupe by note_id, cap at CANDIDATE_TOTAL_CAP
  3. Ask the active LLM to (a) drop irrelevant matches, (b) group the rest
     into 2-6 named categories, returning JSON
  4. Validate the returned paths against the candidate set (drop hallucinations)
  5. Write the hub note to 01_Projects/, index it, run the linker on it
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from slugify import slugify

from app.config import settings
from app.services import browse, indexer, linker, vault
from app.services.llm_providers import get_active_provider


log = logging.getLogger("second_brain.moc")

CANDIDATE_LIMIT_PER_QUERY = 20
CANDIDATE_TOTAL_CAP = 50
SNIPPET_LEN_FOR_LLM = 250


SYSTEM_PROMPT = """You are organizing the user's personal notes into a Map of Content (MOC) — a hub page that groups related notes by subtopic.

You will receive:
- A topic description from the user
- A numbered list of candidate notes (title, exact path, short snippet) found via semantic search

Your job:
1. SELECT the notes that genuinely fit the topic. Drop unrelated matches — quality over quantity.
2. GROUP the selected notes into 2-6 categories with descriptive names.
3. ORDER notes within each category by relevance (best first).

Respond with ONLY a JSON object in this shape:
{
  "title": "<short descriptive MOC title, 4-8 words>",
  "summary": "<1-2 sentence overview of what this MOC covers>",
  "categories": [
    {
      "name": "<category name>",
      "description": "<optional 1-sentence description of what's in this category>",
      "notes": [
        {"path": "<EXACT path from the candidate list>", "note": "<optional 1-line context for this note>"}
      ]
    }
  ]
}

Rules:
- Use the candidates' exact paths verbatim. Do not invent or modify paths.
- It's OK (and expected) to drop candidates that don't actually fit.
- It's OK to include only one category if the topic is narrow.
- No code fences. No prose outside the JSON."""


# ---------- topic + candidates ----------


def split_topic_terms(topic: str) -> list[str]:
    """Split a topic like 'startup work - X, Y, Z' into searchable sub-terms."""
    parts = re.split(r"[,;]|\s+[-–—]\s+", topic)
    return [p.strip() for p in parts if p.strip()]


def gather_candidates(topic: str) -> list[dict]:
    queries: list[str] = [topic]
    parts = split_topic_terms(topic)
    if len(parts) > 1:
        for p in parts:
            if p not in queries:
                queries.append(p)

    seen: set[str] = set()
    out: list[dict] = []
    for q in queries:
        try:
            hits = indexer.search(q, limit=CANDIDATE_LIMIT_PER_QUERY)
        except Exception as e:
            log.warning("search failed for %r: %s", q, e)
            continue
        for h in hits:
            nid = h.get("id")
            if not nid or nid in seen:
                continue
            # Skip existing MOCs and tag pages so we don't recurse into hub-of-hubs
            if h.get("type") == "moc":
                continue
            path = h.get("path") or ""
            if path.startswith("Tags/"):
                continue
            seen.add(nid)
            out.append(h)
            if len(out) >= CANDIDATE_TOTAL_CAP:
                return out
    return out


# ---------- LLM organization ----------


def _strip_json_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def organize_with_llm(topic: str, candidates: list[dict]) -> dict[str, Any]:
    listing_lines: list[str] = []
    for i, c in enumerate(candidates, start=1):
        title = c.get("title") or "(untitled)"
        path = c.get("path") or ""
        snippet = (c.get("text") or c.get("snippet") or "").strip().replace("\n", " ")
        snippet = snippet[:SNIPPET_LEN_FOR_LLM]
        listing_lines.append(f"{i}. {title}\n   path: {path}\n   {snippet}")

    user_prompt = f"Topic: {topic}\n\nCandidate notes:\n\n" + "\n\n".join(listing_lines)

    provider = get_active_provider()
    raw = provider.complete(prompt=user_prompt, system=SYSTEM_PROMPT, json_mode=True)
    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as e:
        log.warning("LLM returned invalid JSON: %s\nRaw head: %s", e, raw[:300])
        # Fallback: dump everything in one category
        return _fallback_organization(topic, candidates)

    return _sanitize_organization(data, candidates, topic)


def _fallback_organization(topic: str, candidates: list[dict]) -> dict:
    return {
        "title": topic[:80] or "Map of Content",
        "summary": f"Notes related to: {topic}",
        "categories": [
            {
                "name": "Related notes",
                "description": "",
                "notes": [
                    {
                        "path": c["path"],
                        "title": c.get("title") or c["path"],
                        "note": "",
                    }
                    for c in candidates
                ],
            }
        ],
    }


def _sanitize_organization(data: dict, candidates: list[dict], topic: str) -> dict:
    by_path = {c["path"]: c for c in candidates if c.get("path")}

    out: dict[str, Any] = {
        "title": str(data.get("title") or "").strip()[:120] or topic[:80] or "Map of Content",
        "summary": str(data.get("summary") or "").strip(),
        "categories": [],
    }

    raw_cats = data.get("categories") or []
    if not isinstance(raw_cats, list):
        return out

    used_paths: set[str] = set()
    for cat in raw_cats:
        if not isinstance(cat, dict):
            continue
        name = str(cat.get("name") or "").strip()
        if not name:
            continue
        cat_notes = []
        for n in (cat.get("notes") or []):
            if not isinstance(n, dict):
                continue
            path = str(n.get("path") or "").strip()
            if path not in by_path or path in used_paths:
                continue
            used_paths.add(path)
            cat_notes.append(
                {
                    "path": path,
                    "title": by_path[path].get("title") or path.rsplit("/", 1)[-1],
                    "note": str(n.get("note") or "").strip(),
                }
            )
        if not cat_notes:
            continue
        out["categories"].append(
            {
                "name": name,
                "description": str(cat.get("description") or "").strip(),
                "notes": cat_notes,
            }
        )

    return out


# ---------- rendering ----------


def _wikilink(path: str, title: str) -> str:
    target = path[:-3] if path.lower().endswith(".md") else path
    label = (title or target.rsplit("/", 1)[-1]).replace("[", "(").replace("]", ")")
    if label and label != target:
        return f"[[{target}|{label}]]"
    return f"[[{target}]]"


def render_moc_body(topic: str, organization: dict) -> str:
    lines: list[str] = [f"# {organization['title']}", ""]
    summary = organization.get("summary", "")
    if summary:
        lines.append(summary)
        lines.append("")
    lines.append(f"> Map of content generated from topic: *{topic}*")
    lines.append("")

    if not organization["categories"]:
        lines.append("*(No matching notes selected.)*")
        lines.append("")
        return "\n".join(lines)

    for cat in organization["categories"]:
        lines.append(f"## {cat['name']}")
        lines.append("")
        if cat.get("description"):
            lines.append(cat["description"])
            lines.append("")
        for note in cat["notes"]:
            link = _wikilink(note["path"], note["title"])
            if note.get("note"):
                lines.append(f"- {link} — {note['note']}")
            else:
                lines.append(f"- {link}")
        lines.append("")

    return "\n".join(lines)


# ---------- main entry point ----------


def build_moc(topic: str) -> dict[str, Any]:
    """Run the full pipeline. Returns metadata about the created MOC."""
    topic = topic.strip()
    if not topic:
        raise ValueError("Topic cannot be empty")

    candidates = gather_candidates(topic)
    if not candidates:
        return {
            "path": None,
            "title": None,
            "categories": 0,
            "notes_linked": 0,
            "candidates_considered": 0,
            "skipped_reason": "no candidates found",
        }

    organization = organize_with_llm(topic, candidates)
    body = render_moc_body(topic, organization)

    note_id = str(uuid.uuid4())
    now = datetime.now()
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%S")

    title = organization["title"]
    slug = slugify(title)[:60] or "moc"
    filename = f"{now.strftime('%Y-%m-%d')}-moc-{slug}.md"
    folder = settings.projects_dir
    folder.mkdir(parents=True, exist_ok=True)

    # Aggregate tags from referenced candidates so the MOC inherits topic context
    tag_counter: Counter[str] = Counter()
    for cat in organization["categories"]:
        for note in cat["notes"]:
            cand = next((c for c in candidates if c.get("path") == note["path"]), None)
            if cand:
                for t in cand.get("tags") or []:
                    if t:
                        tag_counter[str(t).lower()] += 1
    tags = ["moc"] + [t for t, _ in tag_counter.most_common(6)]

    metadata = {
        "id": note_id,
        "source": "cli",
        "type": "moc",
        "date": iso_now,
        "tags": tags,
        "summary": (organization.get("summary") or "")[:300],
        "category": "01_Projects",
        "topic": topic,
    }

    path = vault.write_note(folder, filename, body, metadata)

    try:
        indexer.index_note(note_id, body, metadata, vault.vault_relative(path))
    except Exception as e:
        log.warning("indexing MOC failed: %s", e)

    browse.invalidate_cache()

    try:
        linker.link_new_note(path)
        linker.update_tag_pages(tags)
    except Exception as e:
        log.warning("linker failed for MOC: %s", e)

    return {
        "path": vault.vault_relative(path),
        "title": title,
        "categories": len(organization["categories"]),
        "notes_linked": sum(len(c["notes"]) for c in organization["categories"]),
        "candidates_considered": len(candidates),
    }
