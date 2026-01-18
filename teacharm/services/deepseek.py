"""DeepSeek text generation service for explanations and hints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from ..config import Settings
from ..logger import get_logger
from ..materials import Region

logger = get_logger(__name__)


@dataclass
class GenerationRequest:
    """Request structure for DeepSeek generation."""

    task: str = "generate_explanation"
    style: str = "hint"  # "hint" or "explain"
    material_id: str = ""
    region_id: str = ""
    region_label: str = ""
    region_type: str = ""
    region_text: Optional[str] = None
    script_on_help: Optional[str] = None
    script_on_point: Optional[str] = None
    max_sentences: int = 2
    audience: str = "小学3年生"


@dataclass
class GenerationResponse:
    """Response structure from DeepSeek."""

    text: str
    request_time_ms: int
    rejected: bool = False
    rejection_reason: Optional[str] = None


class DeepSeekService:
    """DeepSeek text generation service for educational content."""

    def __init__(self, settings: Settings):
        self._base_url = settings.deepseek_base_url
        self._model = settings.deepseek_model
        self._timeout = 15.0
        self._total_requests = 0
        self._total_time_ms = 0

    async def generate_explanation(
        self,
        region: Region,
        material_id: str,
        style: str = "hint",
    ) -> GenerationResponse:
        """
        Generate a short explanation or hint for a region.
        Returns 1-2 sentences suitable for elementary students.
        """
        import time

        start_time = time.time()
        self._total_requests += 1

        request = GenerationRequest(
            style=style,
            material_id=material_id,
            region_id=region.id,
            region_label=region.label or region.id,
            region_type=region.type,
            region_text=getattr(region, "text", None),
            script_on_help=self._get_script_text(region, "on_help"),
            script_on_point=self._get_script_text(region, "on_point"),
        )

        try:
            text = await self._call_deepseek(request)
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._total_time_ms += elapsed_ms

            return GenerationResponse(
                text=text,
                request_time_ms=elapsed_ms,
                rejected=False,
            )
        except Exception as e:
            logger.error("DeepSeek generation failed: %s", e)
            elapsed_ms = int((time.time() - start_time) * 1000)
            return GenerationResponse(
                text="うまく説明できなかったから、別の聞き方で教えてね。",
                request_time_ms=elapsed_ms,
                rejected=True,
                rejection_reason=str(e),
            )

    async def _call_deepseek(self, request: GenerationRequest) -> str:
        """Call DeepSeek API and return generated text."""
        system_prompt = self._build_system_prompt(request)
        user_message = self._build_user_message(request)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 150,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()

    def _build_system_prompt(self, request: GenerationRequest) -> str:
        """Build system prompt for DeepSeek."""
        return f"""あなたは小学生向けの学習支援AIです。

役割:
- 教材内容について、{request.audience}にわかりやすく説明する
- 1〜2文で簡潔に答える
- 次に何を見ればいいか、具体的なヒントを含める

制約:
- 教材の範囲内のみ回答する
- 教材外の質問は丁寧に断り、学習に戻す
- 個人情報は聞かない、答えない
- 答えを直接言わず、考え方や手がかりを示す

スタイル: {request.style}
- hint: ヒントや手がかりを示す（答えは言わない）
- explain: 言い換えや別の表現で説明する"""

    def _build_user_message(self, request: GenerationRequest) -> str:
        """Build user message for DeepSeek."""
        parts = [
            f"教材ID: {request.material_id}",
            f"対象: {request.region_label} ({request.region_type})",
        ]

        if request.region_text:
            parts.append(f"内容: {request.region_text}")

        if request.script_on_point:
            parts.append(f"既存の説明: {request.script_on_point}")

        if request.style == "hint":
            parts.append(
                "この問題について、考え方のヒントを1〜2文で教えてください。"
            )
        else:
            parts.append("この内容を別の言い方で説明してください。")

        return "\n".join(parts)

    @staticmethod
    def _get_script_text(region: Region, event: str) -> Optional[str]:
        """Extract script text from region if it exists."""
        script = getattr(region, "script", None)
        if not script:
            return None
        event_commands = script.get(event, [])
        if not event_commands:
            return None
        # Find SAY command
        for cmd in event_commands:
            if isinstance(cmd, dict) and "SAY" in cmd:
                return cmd["SAY"]
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics for monitoring."""
        avg_time = (
            self._total_time_ms // self._total_requests
            if self._total_requests > 0
            else 0
        )
        return {
            "total_requests": self._total_requests,
            "total_time_ms": self._total_time_ms,
            "avg_time_ms": avg_time,
        }
