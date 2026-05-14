"""Capture endpoints — text, voice, image, link.

All endpoints accept optional `lat`/`lon` from the client. When provided, we
look up weather + reverse-geocoded location (cached 15 min) and attach it to
the resulting note.
"""

from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import require_auth
from app.config import settings
from app.models.schemas import (
    CaptureResponse,
    ImageCaptureResponse,
    LinkCaptureRequest,
    LinkCaptureResponse,
    TextCaptureRequest,
    VoiceCaptureResponse,
)
from app.services import transcriber, weather, web_fetcher
from app.services.llm_providers import get_active_provider
from app.services.processor import (
    process_image_capture,
    process_link_capture,
    process_text_capture,
    process_voice_capture,
)
from app.services.vault import vault_relative


router = APIRouter(
    prefix="/api/capture",
    tags=["capture"],
    dependencies=[Depends(require_auth)],
)


def _resolve_context(lat: Optional[float], lon: Optional[float]) -> Optional[dict]:
    """If we have coords, look up weather + location (best-effort, cached)."""
    if lat is None or lon is None:
        return None
    return weather.get_context(lat, lon)


@router.post("/text", response_model=CaptureResponse)
def capture_text(req: TextCaptureRequest) -> CaptureResponse:
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    ctx = _resolve_context(
        req.context.lat if req.context else None,
        req.context.lon if req.context else None,
    )

    try:
        result = process_text_capture(req.content, context=ctx)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return CaptureResponse(**result)


_VOICE_EXT_BY_MIME = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def _voice_filename(upload: UploadFile) -> str:
    if upload.filename and "." in upload.filename:
        return upload.filename
    ext = _VOICE_EXT_BY_MIME.get((upload.content_type or "").lower(), ".webm")
    return f"voice{ext}"


@router.post("/voice", response_model=VoiceCaptureResponse)
async def capture_voice(
    file: UploadFile = File(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
) -> VoiceCaptureResponse:
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    filename = _voice_filename(file)

    try:
        transcript = transcriber.transcribe(audio_bytes, filename=filename)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")

    if not transcript.strip():
        raise HTTPException(status_code=422, detail="Could not transcribe audio (empty result)")

    ctx = _resolve_context(lat, lon)

    try:
        result = process_voice_capture(transcript, context=ctx)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    result["transcript"] = transcript
    return VoiceCaptureResponse(**result)


_IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def _image_filename_and_ext(upload: UploadFile) -> tuple[str, str]:
    """Return (saved_filename, mime_type) for an uploaded image."""
    mime_type = (upload.content_type or "").lower()
    if not mime_type.startswith("image/"):
        # Try guessing from filename as a fallback
        guess, _ = mimetypes.guess_type(upload.filename or "")
        if guess and guess.startswith("image/"):
            mime_type = guess
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"Not an image: {upload.content_type or 'unknown'}")

    ext = _IMAGE_EXT_BY_MIME.get(mime_type)
    if not ext and upload.filename and "." in upload.filename:
        ext = "." + upload.filename.rsplit(".", 1)[-1].lower()
    if not ext:
        ext = ".jpg"

    short_id = uuid.uuid4().hex[:8]
    saved_filename = f"{datetime.now().strftime('%Y-%m-%d')}-{short_id}{ext}"
    return saved_filename, mime_type


@router.post("/image", response_model=ImageCaptureResponse)
async def capture_image(
    file: UploadFile = File(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
) -> ImageCaptureResponse:
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image file")

    saved_filename, mime_type = _image_filename_and_ext(file)

    # Save the image into 08_Attachments first
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)
    saved_path = settings.attachments_dir / saved_filename
    saved_path.write_bytes(image_bytes)

    # Vision description (active provider)
    provider = get_active_provider()
    if not provider.supports_vision():
        raise HTTPException(
            status_code=501,
            detail=f"Active provider '{provider.name}' does not support image understanding",
        )
    try:
        description = provider.describe_image(
            image_bytes,
            mime_type,
            prompt=(
                "Describe this image in 1-2 paragraphs. Be concrete about what's shown — "
                "objects, people, setting, colors, mood. If it contains readable text, "
                "transcribe the key text verbatim. Keep it factual; no speculation."
            ),
        )
    except Exception as e:
        # Don't leave the orphaned attachment on the disk if vision failed
        try:
            saved_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=502, detail=f"Vision API failed: {e}")

    if not description.strip():
        try:
            saved_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="Vision API returned empty description")

    # All capture-target folders are 1 level deep, so ../08_Attachments/ resolves correctly.
    image_relpath = f"../08_Attachments/{saved_filename}"

    ctx = _resolve_context(lat, lon)

    try:
        result = process_image_capture(description, image_relpath, context=ctx)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    result["description"] = description
    result["image_path"] = vault_relative(saved_path)
    return ImageCaptureResponse(**result)


@router.post("/link", response_model=LinkCaptureResponse)
def capture_link(req: LinkCaptureRequest) -> LinkCaptureResponse:
    url = req.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    try:
        page = web_fetcher.fetch(url)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch URL: {e}")

    ctx = _resolve_context(
        req.context.lat if req.context else None,
        req.context.lon if req.context else None,
    )

    try:
        result = process_link_capture(
            url=page["url"], page_title=page["title"], text=page["text"], context=ctx
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    result["url"] = page["url"]
    result["page_title"] = page["title"]
    return LinkCaptureResponse(**result)
