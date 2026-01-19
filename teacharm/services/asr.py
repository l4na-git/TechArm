"""ASR service using faster-whisper."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from faster_whisper import WhisperModel

from ..config import Settings
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class ASRSegment:
    """Single ASR segment."""

    start: float
    end: float
    text: str


@dataclass
class ASRResult:
    """ASR result with transcript and segments."""

    text: str
    language: Optional[str]
    segments: List[ASRSegment]


class ASRService:
    """faster-whisper based ASR service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Optional[WhisperModel] = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            logger.info(
                "Loading ASR model %s (device=%s, compute=%s)",
                self._settings.asr_model,
                self._settings.asr_device,
                self._settings.asr_compute_type,
            )
            self._model = WhisperModel(
                self._settings.asr_model,
                device=self._settings.asr_device,
                compute_type=self._settings.asr_compute_type,
            )
        return self._model

    def _transcribe_file(
        self, audio_path: str, language: Optional[str]
    ) -> ASRResult:
        model = self._get_model()
        lang = language or self._settings.asr_language or None
        segments, info = model.transcribe(
            audio_path,
            language=lang,
            beam_size=self._settings.asr_beam_size,
            vad_filter=True,
        )

        transcript_parts: List[str] = []
        result_segments: List[ASRSegment] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                transcript_parts.append(text)
            result_segments.append(
                ASRSegment(start=seg.start, end=seg.end, text=seg.text)
            )

        text = " ".join(transcript_parts)
        return ASRResult(
            text=text,
            language=getattr(info, "language", None),
            segments=result_segments,
        )

    async def transcribe_file(
        self, audio_path: str, language: Optional[str] = None
    ) -> ASRResult:
        return await asyncio.to_thread(
            self._transcribe_file, audio_path, language
        )
