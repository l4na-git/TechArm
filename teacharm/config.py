"""Application configuration and settings."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Environment driven settings."""

    data_root: Path = Field(default=Path("."))
    materials_dir: Path = Field(default=Path("materials"))
    scripts_dir: Path = Field(default=Path("scripts"))
    config_dir: Path = Field(default=Path("config"))

    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434", env="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="teacharm-llm", env="OLLAMA_MODEL")

    voicevox_base_url: str = Field(
        default="http://127.0.0.1:50021", env="VOICEVOX_BASE_URL"
    )
    voicevox_speaker_name: str = Field(
        default="春日部つむぎ", env="VOICEVOX_SPEAKER_NAME"
    )
    voicevox_style_name: str = Field(default="ノーマル", env="VOICEVOX_STYLE_NAME")

    control_panel_url: Optional[str] = Field(
        default=None,
        env="CONTROL_PANEL_URL",
        description="Tailscale 内で公開するコントロールパネルのURL",
    )

    allowed_origins: List[str] = Field(
        default_factory=lambda: ["*"],
        env="TEACHARM_ALLOWED_ORIGINS",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def resolve_path(self, relative: Path) -> Path:
        """Return an absolute path derived from data_root."""
        base = Path(self.data_root)
        return (base / relative).resolve()


def load_settings() -> Settings:
    """Factory helper used by the FastAPI application."""
    settings = Settings()
    # Normalize key directories
    settings.materials_dir = settings.resolve_path(settings.materials_dir)
    settings.scripts_dir = settings.resolve_path(settings.scripts_dir)
    settings.config_dir = settings.resolve_path(settings.config_dir)
    return settings
