"""Voice transcription via OpenAI Whisper. Always uses OpenAI key (regardless of active provider)."""

from __future__ import annotations

import io

from app.config import settings


def transcribe(
    audio_bytes: bytes,
    filename: str = "voice.webm",
) -> str:
    """Transcribe audio bytes via OpenAI's audio API. Returns plain text."""
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for voice transcription. "
            "Add it to .env or remove voice capture for non-OpenAI setups."
        )

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)

    file_obj = io.BytesIO(audio_bytes)
    # OpenAI uses the filename extension to detect the format. .webm/.m4a/.mp3 all work.
    file_obj.name = filename

    response = client.audio.transcriptions.create(
        model="whisper-1",
        file=file_obj,
    )
    return (response.text or "").strip()
