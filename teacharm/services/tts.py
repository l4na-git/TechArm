"""VOICEVOX Engine client helper."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import httpx
import yaml

from ..config import Settings
from ..logger import get_logger

logger = get_logger(__name__)


class VoiceVoxService:
    """Handles audio generation requests and caching."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache_dir = Path("cache/tts")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._params = self._load_params()
        self._speaker_id: Optional[int] = None

    async def ensure_speaker_id(self) -> Optional[int]:
        """Resolve the speaker ID lazily."""
        if self._speaker_id is not None:
            return self._speaker_id
        url = f"{self._settings.voicevox_base_url.rstrip('/')}/speakers"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                speakers = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("VOICEVOX speakers fetch failed: %s", exc)
            return None
        for speaker in speakers:
            if speaker.get("name") != self._settings.voicevox_speaker_name:
                continue
            for style in speaker.get("styles", []):
                if style.get("name") == self._settings.voicevox_style_name:
                    self._speaker_id = style.get("id")
                    return self._speaker_id
        logger.warning(
            "VOICEVOX speaker %s not found",
            self._settings.voicevox_speaker_name
        )
        return None

    async def synthesize(self, text: str) -> Optional[Path]:
        """Generate a WAV file using VOICEVOX."""
        speaker_id = await self.ensure_speaker_id()
        if speaker_id is None:
            return None
        cache_key = self._build_cache_key(text, speaker_id)
        cached = self._cache_dir / f"{cache_key}.wav"
        if cached.exists():
            return cached

        base_url = self._settings.voicevox_base_url.rstrip("/")
        audio_query_url = f"{base_url}/audio_query"
        synthesis_url = f"{base_url}/synthesis"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                query_resp = await client.post(
                    audio_query_url,
                    params={"text": text, "speaker": speaker_id},
                )
                query_resp.raise_for_status()
                query = query_resp.json()
                query.update(self._params)
                synth_resp = await client.post(
                    synthesis_url,
                    params={"speaker": speaker_id},
                    json=query,
                )
                synth_resp.raise_for_status()
                cached.write_bytes(synth_resp.content)
                return cached
        except Exception as exc:  # noqa: BLE001
            logger.warning("VOICEVOX synthesis failed: %s", exc)
            return None

    def _build_cache_key(self, text: str, speaker_id: int) -> str:
        digest = hashlib.sha256()
        payload = json.dumps(
            {"text": text, "speaker": speaker_id, **self._params},
            ensure_ascii=False
        )
        digest.update(payload.encode("utf-8"))
        return digest.hexdigest()

    def _load_params(self) -> dict:
        path = Path(self._settings.config_dir) / "voicevox_params.yaml"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
