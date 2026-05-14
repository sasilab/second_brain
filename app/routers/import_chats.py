"""Chat-export import endpoints.

Each endpoint comes in two flavours:
  POST /api/import/{source}          → JSON response with final counts
  POST /api/import/{source}/stream   → SSE stream of progress events

Both accept ZIPs (containing conversations.json or My Activity.html/.json)
as well as the raw JSON/HTML file directly. For Gemini, Google Takeout's
sidecar directories (gemini_scheduled_actions_data, gemini_gems_data) are
skipped automatically.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.auth import require_auth
from app.models.schemas import ImportResponse
from app.parsers import chatgpt, claude, gemini
from app.services import import_helpers
from app.services.chat_importer import import_conversations, iter_import


router = APIRouter(prefix="/api/import", tags=["import"], dependencies=[Depends(require_auth)])


# ---------- shared parsing ----------


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    return data


# Map source → parser module. Each parser has at minimum `parse(json_bytes_or_str)`.
# Gemini additionally has `parse_html(html_str)` for Takeout My Activity HTML.
_PARSERS = {
    "chatgpt": chatgpt,
    "claude": claude,
    "gemini": gemini,
}


def _parse_payload(source: str, payload: bytes | str, fmt: str) -> list[dict]:
    mod = _PARSERS[source]
    if fmt == "html":
        if not hasattr(mod, "parse_html"):
            raise ValueError(f"HTML payload not supported for {source}")
        return mod.parse_html(payload)
    return mod.parse(payload)


def _prepare_import(raw: bytes, source: str, limit: Optional[int]) -> list[dict]:
    """Run ZIP extraction + parsing. Raises HTTPException on failure."""
    try:
        payload, fmt = import_helpers.extract_payload(raw, source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        conversations = _parse_payload(source, payload, fmt)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Couldn't parse {source} export: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't parse {source} export: {e}")

    if limit is not None:
        conversations = conversations[:limit]
    return conversations


# ---------- JSON endpoints ----------


def _build_json_handler(source: str) -> Callable:
    async def handler(
        file: UploadFile = File(...),
        process: bool = Form(True),
        limit: Optional[int] = Form(None),
    ) -> ImportResponse:
        raw = await _read_upload(file)
        conversations = _prepare_import(raw, source, limit)
        if not conversations:
            return ImportResponse(source=source, total=0, imported=0, skipped=0, failed=0)
        try:
            counts = import_conversations(conversations, source=source, process=process)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        return ImportResponse(source=source, **counts)

    return handler


# ---------- SSE endpoints ----------


def _sse_pack(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream_events(conversations: list[dict], source: str, process: bool):
    """Run the sync iter_import in a worker thread; surface events via asyncio.Queue."""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    sentinel = object()

    def worker():
        try:
            for event in iter_import(conversations, source=source, process=process):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"phase": "error", "detail": str(e)}
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        event = await queue.get()
        if event is sentinel:
            return
        yield _sse_pack(event)


def _build_stream_handler(source: str) -> Callable:
    async def handler(
        file: UploadFile = File(...),
        process: bool = Form(True),
        limit: Optional[int] = Form(None),
    ) -> StreamingResponse:
        raw = await _read_upload(file)
        conversations = _prepare_import(raw, source, limit)

        if not conversations:
            async def empty_gen():
                yield _sse_pack({"phase": "done", "total": 0, "imported": 0, "skipped": 0, "failed": 0})
            return StreamingResponse(empty_gen(), media_type="text/event-stream")

        return StreamingResponse(
            _stream_events(conversations, source, process),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return handler


# ---------- route registration ----------


for _src in ("chatgpt", "claude", "gemini"):
    router.add_api_route(
        f"/{_src}",
        _build_json_handler(_src),
        methods=["POST"],
        response_model=ImportResponse,
        name=f"import_{_src}",
        summary=f"Import {_src} export (JSON, returns final counts)",
    )
    router.add_api_route(
        f"/{_src}/stream",
        _build_stream_handler(_src),
        methods=["POST"],
        name=f"import_{_src}_stream",
        summary=f"Import {_src} export (SSE stream of progress events)",
    )
