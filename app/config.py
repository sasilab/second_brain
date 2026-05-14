from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    vault_path: Path = Field(default=PROJECT_ROOT / "vault")
    vault_name: str = ""  # used to build obsidian:// URLs; falls back to vault folder name

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    active_provider: Literal["openai", "anthropic", "google"] = "openai"

    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-sonnet-4-20250514"
    google_model: str = "gemini-2.0-flash"

    host: str = "0.0.0.0"
    port: int = 8000

    app_password: str = ""

    @property
    def vault_root(self) -> Path:
        path = self.vault_path
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path

    @property
    def effective_vault_name(self) -> str:
        return self.vault_name.strip() or self.vault_root.name

    @property
    def meta_dir(self) -> Path:
        return self.vault_root / "_meta"

    @property
    def chroma_dir(self) -> Path:
        return self.meta_dir / "chroma"

    @property
    def sqlite_path(self) -> Path:
        return self.meta_dir / "second_brain.db"

    @property
    def config_json_path(self) -> Path:
        return self.meta_dir / "config.json"

    @property
    def inbox_dir(self) -> Path:
        return self.vault_root / "00_Inbox"

    @property
    def projects_dir(self) -> Path:
        return self.vault_root / "01_Projects"

    @property
    def areas_dir(self) -> Path:
        return self.vault_root / "02_Areas"

    @property
    def resources_dir(self) -> Path:
        return self.vault_root / "03_Resources"

    @property
    def archive_dir(self) -> Path:
        return self.vault_root / "04_Archive"

    @property
    def daily_dir(self) -> Path:
        return self.vault_root / "05_Daily"

    @property
    def chats_dir(self) -> Path:
        return self.vault_root / "06_Chats"

    @property
    def references_dir(self) -> Path:
        return self.vault_root / "07_References"

    @property
    def attachments_dir(self) -> Path:
        return self.vault_root / "08_Attachments"

    def ensure_vault_dirs(self) -> None:
        for d in (
            self.vault_root,
            self.meta_dir,
            self.chroma_dir,
            self.inbox_dir,
            self.projects_dir,
            self.areas_dir,
            self.resources_dir,
            self.archive_dir,
            self.daily_dir,
            self.chats_dir,
            self.chats_dir / "ChatGPT",
            self.chats_dir / "Claude",
            self.chats_dir / "Gemini",
            self.references_dir,
            self.attachments_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
