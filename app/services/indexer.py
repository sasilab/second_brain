"""ChromaDB-backed semantic search.

Notes are split into ~1000-char chunks (paragraph-aware) and stored under
deterministic IDs `{note_id}_chunk_{i}`. Re-indexing a note deletes its old
chunks first, so updates don't leave stale entries.

The Chroma client and collection are created lazily on first use.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from app.config import settings


log = logging.getLogger("second_brain.indexer")

COLLECTION_NAME = "second_brain"

_client = None
_collection = None


def _coll():
    """Lazy ChromaDB collection. First call may take a few seconds (model download)."""
    global _client, _collection
    if _collection is None:
        import chromadb

        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ---------- chunking ----------


def chunk_text(text: str, max_chars: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into chunks of ~max_chars, breaking on paragraph/sentence boundaries when possible."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            tail = text[start:].strip()
            if tail:
                chunks.append(tail)
            break

        window = text[start:end]
        cut = -1
        # Prefer paragraph break
        idx = window.rfind("\n\n")
        if idx > max_chars // 2:
            cut = idx
        else:
            # Try sentence/line endings
            for delim in (". ", "! ", "? ", "\n"):
                idx = window.rfind(delim)
                if idx > max_chars // 2:
                    cut = idx + len(delim)
                    break
        if cut <= 0:
            cut = max_chars  # hard cut

        piece = text[start : start + cut].strip()
        if piece:
            chunks.append(piece)
        start = max(start + cut - overlap, start + 1)

    return chunks


# ---------- metadata coercion ----------


def _coerce_meta_value(v: Any) -> Any:
    """ChromaDB metadata only accepts str/int/float/bool. Coerce everything else."""
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, list):
        return ",".join(str(x) for x in v if x is not None)
    if v is None:
        return ""
    return str(v)


def _build_meta(note_id: str, chunk_index: int, frontmatter: dict, vault_relpath: str) -> dict:
    title = frontmatter.get("title")
    if not title:
        # Daily notes have no title in frontmatter — derive from filename
        title = Path(vault_relpath).stem
    return {
        "note_id": note_id,
        "chunk_index": chunk_index,
        "path": vault_relpath,
        "title": _coerce_meta_value(title),
        "type": _coerce_meta_value(frontmatter.get("type", "")),
        "source": _coerce_meta_value(frontmatter.get("source", "")),
        "date": _coerce_meta_value(frontmatter.get("date", "")),
        "category": _coerce_meta_value(frontmatter.get("category", "")),
        "tags": _coerce_meta_value(frontmatter.get("tags", [])),
        "summary": _coerce_meta_value(frontmatter.get("summary", "")),
    }


# ---------- index / delete ----------


def index_note(
    note_id: str,
    content: str,
    frontmatter: dict,
    vault_relpath: str,
) -> int:
    """Index a note's content. Replaces all existing chunks for this note_id.
    Returns the number of chunks written.
    """
    coll = _coll()

    # Drop old chunks first so deletions/edits don't leave stale entries.
    try:
        coll.delete(where={"note_id": note_id})
    except Exception as e:
        log.debug("delete-by-note_id failed (likely empty collection): %s", e)

    # Strip auto-link sections so they never pollute embeddings (local import to avoid cycle).
    from app.services.linker import strip_linker_sections
    cleaned = strip_linker_sections(content)
    chunks = chunk_text(cleaned)
    if not chunks:
        return 0

    ids = [f"{note_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [_build_meta(note_id, i, frontmatter, vault_relpath) for i in range(len(chunks))]
    coll.upsert(ids=ids, documents=chunks, metadatas=metadatas)
    return len(chunks)


def delete_note(note_id: str) -> None:
    try:
        _coll().delete(where={"note_id": note_id})
    except Exception as e:
        log.warning("delete_note failed: %s", e)


# ---------- search ----------


def search(
    query: str,
    limit: int = 10,
    filters: Optional[dict] = None,
) -> list[dict]:
    """Semantic search. Returns deduped hits (best chunk per note), highest score first.

    Each hit: {id, title, path, text, score, type, source, date, tags, category, summary}.
    """
    coll = _coll()

    where: dict = {}
    if filters:
        for key in ("source", "type", "category"):
            v = filters.get(key)
            if v:
                where[key] = v

    # Pull more than `limit` so dedup-by-note still has enough left
    n = max(limit * 3, 10)
    raw = coll.query(
        query_texts=[query],
        n_results=n,
        where=where if where else None,
    )

    if not raw or not raw.get("ids") or not raw["ids"]:
        return []

    ids = raw["ids"][0] or []
    docs = (raw.get("documents") or [[]])[0] or []
    metas = (raw.get("metadatas") or [[]])[0] or []
    dists = (raw.get("distances") or [[]])[0] or []

    seen: set[str] = set()
    out: list[dict] = []
    for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists):
        meta = meta or {}
        note_id = meta.get("note_id") or chunk_id
        if note_id in seen:
            continue
        seen.add(note_id)

        tags_raw = meta.get("tags", "")
        tags = [t for t in str(tags_raw).split(",") if t] if tags_raw else []

        out.append(
            {
                "id": str(note_id),
                "title": str(meta.get("title", "")),
                "path": str(meta.get("path", "")),
                "text": doc or "",
                "score": round(1.0 - float(dist), 4),
                "type": str(meta.get("type", "")),
                "source": str(meta.get("source", "")),
                "date": str(meta.get("date", "")),
                "category": str(meta.get("category", "")),
                "tags": tags,
                "summary": str(meta.get("summary", "")),
            }
        )
        if len(out) >= limit:
            break

    return out


# ---------- bulk reindex ----------


SKIP_TOP_LEVEL = {"_meta", "Templates", "Tags"}


def _stable_id_for_path(rel_posix: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, rel_posix))


def reindex_vault(*, log_each: bool = False) -> dict[str, int]:
    """Rebuild the entire index from .md files in the vault.

    Returns counts: {indexed, chunks, skipped, errors}.
    """
    from app.services import vault as vault_svc  # local to avoid cycles

    coll = _coll()
    # Wipe and recreate so deletions on disk are reflected.
    try:
        global _client, _collection
        if _client is not None:
            _client.delete_collection(COLLECTION_NAME)
        _collection = None
        coll = _coll()
    except Exception as e:
        log.warning("Could not delete existing collection (continuing with upsert): %s", e)

    indexed = 0
    chunks_total = 0
    skipped = 0
    errors = 0

    for md_path in settings.vault_root.rglob("*.md"):
        rel = md_path.relative_to(settings.vault_root)
        parts = rel.parts
        if parts and parts[0] in SKIP_TOP_LEVEL:
            skipped += 1
            continue

        try:
            frontmatter, content = vault_svc.read_note(md_path)
        except Exception as e:
            log.warning("read failed: %s — %s", rel, e)
            errors += 1
            continue

        # Pick an id: frontmatter.id if present, else daily-DATE for 05_Daily, else stable hash.
        note_id = str(frontmatter.get("id") or "").strip()
        if not note_id:
            if parts and parts[0] == "05_Daily":
                note_id = f"daily-{md_path.stem}"
            else:
                note_id = _stable_id_for_path(rel.as_posix())

        try:
            n = index_note(note_id, content, frontmatter, vault_svc.vault_relative(md_path))
            indexed += 1
            chunks_total += n
            if log_each:
                log.info("indexed %s (%d chunks)", rel, n)
        except Exception as e:
            log.warning("index failed: %s — %s", rel, e)
            errors += 1

    return {
        "indexed": indexed,
        "chunks": chunks_total,
        "skipped": skipped,
        "errors": errors,
    }


# Useful for the daily-append flow without the caller having to know the ID scheme.
def daily_id_for_date_iso(date_iso: str) -> str:
    return f"daily-{date_iso}"
