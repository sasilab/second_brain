"""LLM provider abstraction. One class per backend; instances are lazy."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import ClassVar

from app.config import settings


class LLMProvider(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str: ...

    def supports_vision(self) -> bool:
        return False

    def describe_image(
        self, image_bytes: bytes, mime_type: str, prompt: str = "Describe this image."
    ) -> str:
        raise NotImplementedError(f"{self.name} provider does not support vision")

    def model(self) -> str:
        return ""


class OpenAIProvider(LLMProvider):
    name = "openai"
    display_name = "OpenAI (GPT)"

    def __init__(self) -> None:
        self._client = None

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    def model(self) -> str:
        return settings.openai_model

    def supports_vision(self) -> bool:
        return True

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.openai_api_key)
        return self._client

    def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        client = self._get_client()
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict = {"model": settings.openai_model, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def describe_image(
        self, image_bytes: bytes, mime_type: str, prompt: str = "Describe this image."
    ) -> str:
        client = self._get_client()
        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime_type};base64,{b64}"
        response = client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=600,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        return response.choices[0].message.content or ""


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    display_name = "Anthropic (Claude)"

    def __init__(self) -> None:
        self._client = None

    def is_configured(self) -> bool:
        return bool(settings.anthropic_api_key)

    def model(self) -> str:
        return settings.anthropic_model

    def supports_vision(self) -> bool:
        return True

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        client = self._get_client()
        kwargs: dict = {
            "model": settings.anthropic_model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""

    def describe_image(
        self, image_bytes: bytes, mime_type: str, prompt: str = "Describe this image."
    ) -> str:
        client = self._get_client()
        b64 = base64.b64encode(image_bytes).decode()
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=600,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""


class GoogleProvider(LLMProvider):
    name = "google"
    display_name = "Google (Gemini)"

    def __init__(self) -> None:
        self._client = None

    def is_configured(self) -> bool:
        return bool(settings.google_api_key)

    def model(self) -> str:
        return settings.google_model

    def supports_vision(self) -> bool:
        return True

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=settings.google_api_key)
        return self._client

    def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        client = self._get_client()
        from google.genai import types

        config_kwargs: dict = {}
        if system:
            config_kwargs["system_instruction"] = system
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        response = client.models.generate_content(
            model=settings.google_model,
            contents=prompt,
            config=config,
        )
        return response.text or ""

    def describe_image(
        self, image_bytes: bytes, mime_type: str, prompt: str = "Describe this image."
    ) -> str:
        from google.genai import types

        client = self._get_client()
        response = client.models.generate_content(
            model=settings.google_model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
        )
        return response.text or ""


PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
}

_instances: dict[str, LLMProvider] = {}


def get_provider(name: str) -> LLMProvider:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}")
    if name not in _instances:
        _instances[name] = PROVIDERS[name]()
    return _instances[name]


def get_active_provider() -> LLMProvider:
    provider = get_provider(settings.active_provider)
    if not provider.is_configured():
        raise RuntimeError(
            f"Active provider '{settings.active_provider}' is not configured. "
            f"Add the corresponding API key to .env."
        )
    return provider


def reset_clients() -> None:
    """Drop cached SDK clients so freshly-saved API keys are picked up."""
    for inst in _instances.values():
        inst._client = None


def list_providers() -> list[dict]:
    out = []
    for name, cls in PROVIDERS.items():
        inst = get_provider(name)
        out.append(
            {
                "name": name,
                "display": cls.display_name,
                "configured": inst.is_configured(),
                "model": inst.model(),
            }
        )
    return out
