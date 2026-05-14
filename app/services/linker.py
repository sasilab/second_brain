"""Auto-linking for Obsidian graph connectivity.

Three feature areas:

1. Tag pages — for every tag in use, write `Tags/<tag>.md` listing notes with
   that tag. Each note's body gets a `<!-- linker:tags -->` section with
   wiki-links like `[[Tags/python]]`.
2. Related notes — semantic search via the indexer. Each note's body gets a
   `<!-- linker:related -->` section listing the top N most-similar notes.
3. Daily round-up — each daily note's body gets a `<!-- linker:daily-links -->`
   section listing standalone notes filed the same day.

All injected sections are wrapped in HTML comment markers so re-running the
linker is idempotent. The indexer strips these markers before chunking, so
auto-link content never pollutes search embeddings.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import frontmatter

from app.config import settings
from app.services import browse, indexer, vault as vault_svc


log = logging.getLogger("second_brain.linker")


RELATED_LIMIT = 3
TAGS_DIR_NAME = "Tags"

MARKER_RE = re.compile(
    r"\n*<!--\s*linker:([\w-]+)\s*-->.*?<!--\s*/linker:[\w-]+\s*-->\n*",
    re.DOTALL,
)

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


# ---------- public helpers ----------


def strip_linker_sections(body: str) -> str:
    """Used by the indexer to keep auto-links out of embeddings."""
    return MARKER_RE.sub("\n", body or "").strip() + "\n" if body else ""


def link_new_note(path: Path) -> None:
    """Add Tags + Related sections to a freshly-written standalone note."""
    try:
        meta, body = vault_svc.read_note(path)
    except Exception as e:
        log.warning("link_new_note read failed: %s", e)
        return

    note_id = str(meta.get("id") or "")
    note_type = str(meta.get("type") or "")
    tags = _coerce_tags(meta.get("tags"))

    new_body = body
    new_body = _replace_section(new_body, "tags", _build_tag_links(tags))
    # MOC notes are themselves curated link lists — auto-related would just echo
    # the same items, so we skip it for type=moc.
    if note_type != "moc":
        new_body = _replace_section(new_body, "related", _build_related(note_id, body))

    if new_body != body:
        _rewrite(path, meta, new_body)


def update_tag_pages(tags: Iterable[str]) -> None:
    """Regenerate the tag index page for each given tag."""
    seen = {t.strip().lower() for t in tags if t and t.strip()}
    if not seen:
        return
    all_notes = browse.list_all_notes()
    tags_dir = settings.vault_root / TAGS_DIR_NAME
    tags_dir.mkdir(parents=True, exist_ok=True)
    for tag in seen:
        notes = [n for n in all_notes if any(str(t).lower() == tag for t in n.get("tags") or [])]
        _write_tag_page(tags_dir, tag, notes)


def regenerate_all_tag_indexes() -> dict[str, int]:
    """Wipe and rebuild every page in Tags/."""
    tags_dir = settings.vault_root / TAGS_DIR_NAME
    tags_dir.mkdir(parents=True, exist_ok=True)

    all_notes = browse.list_all_notes()

    by_tag: dict[str, list[dict]] = {}
    for n in all_notes:
        for t in n.get("tags") or []:
            key = str(t).strip().lower()
            if key:
                by_tag.setdefault(key, []).append(n)

    written = 0
    for tag, notes in by_tag.items():
        _write_tag_page(tags_dir, tag, notes)
        written += 1

    # Drop pages whose tag is no longer in use
    valid_filenames = {_safe_tag_filename(t) for t in by_tag}
    removed = 0
    for existing in tags_dir.glob("*.md"):
        if existing.stem not in valid_filenames:
            try:
                existing.unlink()
                removed += 1
            except OSError:
                pass

    return {"tag_pages_written": written, "tag_pages_removed": removed}


def link_daily_for_date(date_iso: str) -> None:
    """Update the daily file's `Notes from today` section. No-op if daily file is absent."""
    iso_day = (date_iso or "")[:10]
    if not iso_day:
        return
    daily_path = settings.daily_dir / f"{iso_day}.md"
    if not daily_path.exists():
        return
    try:
        meta, body = vault_svc.read_note(daily_path)
    except Exception as e:
        log.warning("link_daily read failed: %s", e)
        return

    section = _build_daily_links(iso_day)
    new_body = _replace_section(body, "daily-links", section)
    if new_body != body:
        _rewrite(daily_path, meta, new_body)


def relink_all_notes(verbose: bool = False) -> dict[str, int]:
    """Apply per-note linking to every note in the vault. Used by `cli.py link`."""
    relinked = 0
    skipped = 0
    errors = 0
    daily_dates: set[str] = set()

    for md_path in settings.vault_root.rglob("*.md"):
        rel = md_path.relative_to(settings.vault_root).parts
        if not rel or rel[0] in {"_meta", "Templates", TAGS_DIR_NAME}:
            skipped += 1
            continue

        if rel[0] == "05_Daily":
            daily_dates.add(md_path.stem)
            continue

        try:
            link_new_note(md_path)
            relinked += 1
            if verbose:
                log.info("linked %s", md_path.relative_to(settings.vault_root))
        except Exception as e:
            log.warning("link failed for %s: %s", md_path, e)
            errors += 1

    daily_updated = 0
    for d in daily_dates:
        try:
            link_daily_for_date(d)
            daily_updated += 1
        except Exception as e:
            log.warning("daily link failed for %s: %s", d, e)
            errors += 1

    return {
        "relinked": relinked,
        "daily_updated": daily_updated,
        "skipped": skipped,
        "errors": errors,
    }


# ---------- internals ----------


def _coerce_tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []


def _safe_tag_filename(tag: str) -> str:
    name = _INVALID_FILENAME_CHARS.sub("-", tag).strip(" .-") or "tag"
    return name.lower()[:80]


def _path_no_ext(path: str) -> str:
    return path[:-3] if path.lower().endswith(".md") else path


def _wikilink(path: str, title: str | None = None) -> str:
    target = _path_no_ext(path)
    label = (title or target.rsplit("/", 1)[-1]).replace("[", "(").replace("]", ")")
    if label and label != target:
        return f"[[{target}|{label}]]"
    return f"[[{target}]]"


def _build_tag_links(tags: list[str]) -> str | None:
    if not tags:
        return None
    pieces = [f"[[{TAGS_DIR_NAME}/{_safe_tag_filename(t)}|{t}]]" for t in tags]
    return "## Tags\n\n" + " ".join(pieces) + "\n"


def _build_related(note_id: str, body: str) -> str | None:
    query = strip_linker_sections(body or "").strip()[:600]
    if not query:
        return None
    try:
        # Pull extra so we can drop self / Tags hits before truncating
        hits = indexer.search(query, limit=RELATED_LIMIT * 4)
    except Exception as e:
        log.warning("related search failed: %s", e)
        return None

    filtered: list[dict] = []
    for h in hits:
        if note_id and h.get("id") == note_id:
            continue
        path = h.get("path") or ""
        if path.startswith(f"{TAGS_DIR_NAME}/"):
            continue
        filtered.append(h)
        if len(filtered) >= RELATED_LIMIT:
            break

    if not filtered:
        return None

    lines = ["## Related", ""]
    for h in filtered:
        lines.append(f"- {_wikilink(h['path'], h.get('title'))}")
    return "\n".join(lines) + "\n"


def _build_daily_links(iso_day: str) -> str | None:
    same_day = []
    for n in browse.list_all_notes():
        date_str = (n.get("date") or "")[:10]
        if date_str != iso_day:
            continue
        path = n.get("path") or ""
        # Skip the daily file itself + tag pages
        if path.startswith("05_Daily/") or path.startswith(f"{TAGS_DIR_NAME}/"):
            continue
        same_day.append(n)

    if not same_day:
        return None

    lines = ["## Notes from today", ""]
    for n in same_day:
        lines.append(f"- {_wikilink(n.get('path', ''), n.get('title'))}")
    return "\n".join(lines) + "\n"


def _write_tag_page(tags_dir: Path, tag: str, notes: list[dict]) -> None:
    filename = _safe_tag_filename(tag) + ".md"
    path = tags_dir / filename

    notes_sorted = sorted(notes, key=lambda n: (n.get("date") or "", n.get("title") or ""), reverse=True)

    lines = [f"# {tag}", "", f"Notes tagged with **#{tag}** ({len(notes_sorted)})", ""]
    for n in notes_sorted:
        lines.append(f"- {_wikilink(n.get('path', ''), n.get('title'))}")
    body = "\n".join(lines) + "\n"

    metadata = {
        "type": "tag-index",
        "tag": tag,
        "count": len(notes_sorted),
    }
    post = frontmatter.Post(body, **metadata)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _replace_section(body: str, name: str, content: str | None) -> str:
    """Replace the marker-delimited section. content=None removes the section."""
    start = f"<!-- linker:{name} -->"
    end = f"<!-- /linker:{name} -->"

    s = body.find(start)
    e = body.find(end)
    has_existing = s != -1 and e != -1 and e > s

    if has_existing:
        before = body[:s].rstrip()
        after = body[e + len(end):].lstrip("\n")
    else:
        before = body.rstrip()
        after = ""

    if not content:
        if has_existing:
            joined = before + ("\n\n" + after if after else "\n")
            return joined
        return body  # nothing to remove, no content to add

    section = f"{start}\n{content.rstrip()}\n{end}"
    parts = [before, section]
    if after:
        parts.append(after)
    return "\n\n".join(parts).rstrip() + "\n"


def _rewrite(path: Path, metadata: dict, new_body: str) -> None:
    post = frontmatter.Post(new_body, **{k: v for k, v in metadata.items()})
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
