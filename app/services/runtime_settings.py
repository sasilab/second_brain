"""Runtime settings overlay on top of `app.config.settings`.

The .env file holds the boot-time defaults. The Settings UI writes overrides
into vault/_meta/config.json under a `settings` key. On startup (and after
each PUT) we apply those overrides by mutating the in-memory settings instance.

NOTE: stored as plain JSON. The vault/_meta/ directory is gitignored, so the
file lives only on the user's machine — but it is NOT encrypted on disk.
Filesystem permissions are the protection.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import settings as env_settings


# Whitelist of keys the UI is allowed to override.
RUNTIME_KEYS: tuple[str, ...] = (
    "active_provider",
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "openai_model",
    "anthropic_model",
    "google_model",
    "vault_name",
)


def _read_full() -> dict:
    if not env_settings.config_json_path.exists():
        return {}
    try:
        return json.loads(env_settings.config_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_full(data: dict) -> None:
    env_settings.meta_dir.mkdir(parents=True, exist_ok=True)
    env_settings.config_json_path.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def load_overrides() -> dict[str, Any]:
    """Return the persisted runtime overrides (may be empty)."""
    return (_read_full().get("settings") or {})


def save_overrides(overrides: dict[str, Any]) -> None:
    full = _read_full()
    full["settings"] = overrides
    _write_full(full)


def apply_overrides() -> None:
    """Mutate the env-loaded settings instance with persisted overrides."""
    overrides = load_overrides()
    for key in RUNTIME_KEYS:
        if key in overrides and overrides[key] not in (None, ""):
            try:
                setattr(env_settings, key, overrides[key])
            except Exception:
                pass


def update(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge new key/values into the override file. Empty string clears an override.

    Returns the resulting full overrides dict (after merge).
    """
    current = load_overrides()
    for key, value in updates.items():
        if key not in RUNTIME_KEYS:
            continue
        if value in (None, ""):
            current.pop(key, None)
        else:
            current[key] = value
    save_overrides(current)
    apply_overrides()
    return current
