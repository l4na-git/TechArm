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

    # LLM (Ollama/DeepSeek)
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

    vision_offload_url: Optional[str] = Field(
        default=None,
        env="VISION_OFFLOAD_URL",
        description="Vision処理をオフロードするサーバーのURL",
    )

    asr_model: str = Field(
        default="base",
        env="ASR_MODEL",
        description="faster-whisper model name or local path",
    )
    asr_language: str = Field(
        default="ja",
        env="ASR_LANGUAGE",
        description="Default ASR language code",
    )
    asr_device: str = Field(
        default="cpu",
        env="ASR_DEVICE",
        description="ASR device (cpu/cuda)",
    )
    asr_compute_type: str = Field(
        default="int8",
        env="ASR_COMPUTE_TYPE",
        description="ASR compute type for faster-whisper",
    )
    asr_beam_size: int = Field(
        default=1,
        env="ASR_BEAM_SIZE",
        description="ASR beam size",
    )

    # SO-101 Robot Arm
    so101_port: str = Field(
        default="/dev/ttyUSB0",
        env="SO101_PORT",
        description="USB serial port for SO-101 Follower arm",
    )
    so101_baudrate: int = Field(
        default=1000000, 
        env="SO101_BAUDRATE",
        description="Baudrate for SO-101 motor communication",
    )

    so101_calibration_path: Optional[Path] = Field(
        default=None,
        env="SO101_CALIBRATION_PATH",
        description="Path to LeRobot official calibration JSON (e.g., ~/.cache/huggingface/lerobot/calibration/robots/so101_follower/calibration.json)",
    )

    arm_calibration_path: Optional[Path] = Field(
        default=None,
        env="ARM_CALIBRATION_PATH",
        description="Path to TeachArm UV->XYZ calibration JSON (arm_calibration.json)",
    )

    arm_marker_mapping_path: Optional[Path] = Field(
        default=None,
        env="ARM_MARKER_MAPPING_PATH",
        description="Path to marker-based UV->XY mapping JSON",
    )

    allowed_origins: List[str] = Field(
        default_factory=lambda: ["*"],
        env="TEACHARM_ALLOWED_ORIGINS",
    )

    # Server mode and port
    server_mode: str = Field(
        default="audio",
        env="SERVER_MODE",
        description="'audio' (Vision/ASR/TTS) or 'arm' (LeRobot/ARM_SERVICE)",
    )
    server_port: int = Field(
        default=8000,
        env="SERVER_PORT",
        description="HTTP port for this server instance",
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
    if settings.arm_calibration_path:
        arm_path = Path(settings.arm_calibration_path).expanduser()
        if not arm_path.is_absolute():
            arm_path = settings.resolve_path(arm_path)
        settings.arm_calibration_path = arm_path.resolve()
    if settings.arm_marker_mapping_path:
        marker_path = Path(settings.arm_marker_mapping_path).expanduser()
        if not marker_path.is_absolute():
            marker_path = settings.resolve_path(marker_path)
        settings.arm_marker_mapping_path = marker_path.resolve()
    return settings
