"""FunctionGemma-based routing service for action decision."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class RouterInput:
    """Input structure for FunctionGemma router."""

    version: str = "1"
    state: str = "IDLE"
    error_code: Optional[str] = None
    asr_text: Optional[str] = None
    material_id: Optional[str] = None
    current_region_id: Optional[str] = None
    last_region_id: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "state": self.state,
            "error_code": self.error_code,
            "asr_text": self.asr_text,
            "material_id": self.material_id,
            "current_region_id": self.current_region_id,
            "last_region_id": self.last_region_id,
            "candidates": self.candidates or [],
        }


@dataclass
class RouterOutput:
    """Output structure from FunctionGemma router."""

    action: str
    args: Dict[str, Any]
    raw_response: str
    fallback_used: bool = False


# Whitelist of allowed actions
ALLOWED_ACTIONS = {
    "respond_script",
    "repeat_last",
    "next_region",
    "generate_explanation",
    "reject",
    "clarify",
    "recover_suggest",
}


class RouterService:
    """FunctionGemma-based routing service for determining next action."""

    def __init__(self, settings: Settings):
        self._base_url = settings.function_gemma_base_url
        self._model = settings.function_gemma_model
        self._timeout = 10.0
        self._fallback_count = 0
        self._total_requests = 0

    async def route(self, router_input: RouterInput) -> RouterOutput:
        """
        Call FunctionGemma to determine the next action.
        Returns RouterOutput with action/args or falls back to
        rule-based logic.
        """
        self._total_requests += 1

        try:
            raw_response = await self._call_function_gemma(router_input)
            parsed = self._parse_and_validate(raw_response)
            if parsed:
                return RouterOutput(
                    action=parsed["action"],
                    args=parsed.get("args", {}),
                    raw_response=raw_response,
                    fallback_used=False,
                )
        except Exception as e:
            logger.warning("FunctionGemma call failed: %s", e)

        # Fallback to rule-based routing
        self._fallback_count += 1
        return self._fallback_route(router_input)

    async def _call_function_gemma(self, router_input: RouterInput) -> str:
        """Call FunctionGemma API and return raw JSON string."""
        system_prompt = self._build_system_prompt()
        user_message = json.dumps(router_input.to_dict(), ensure_ascii=False)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
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

    def _build_system_prompt(self) -> str:
        """Build system prompt for FunctionGemma."""
        return """あなたはTeachArmのルーティング判定専用AIです。
入力されたJSON(state, error_code, asr_text, material_id,
current_region_id等)から、次に実行すべきactionを決定してください。

出力は必ずJSONのみで、以下の形式に従ってください:
{"action": "ACTION_NAME", "args": {...}}

許可されているaction:
- respond_script: region.scriptを読む
  {"mode": "point"|"help", "region_id": "..."}
- repeat_last: 直前の説明を繰り返す {}
- next_region: 次の候補regionを提示 {}
- generate_explanation: 台本が無い場合にDeepSeekで生成
  {"style": "hint"|"explain", "region_id": "..."}
- reject: 学習外・個人情報・不適切要求を拒否
  {"reason": "..."}
- clarify: regionが特定できない等、聞き返し
  {"question": "..."}
- recover_suggest: エラー復帰誘導 {"error_code": "..."}

判定優先順位:
1. error_code != null → recover_suggest
2. コマンド(もう一回/次/ヒント) →
   repeat_last / next_region / respond_script
3. current_region_id があり region.script が使える →
   respond_script
4. current_region_id があるが台本が無い →
   generate_explanation
5. 上記以外 → clarify または reject

JSONのみを出力し、他の文字は一切含めないでください。"""

    def _parse_and_validate(self, raw: str) -> Optional[Dict[str, Any]]:
        """Parse JSON and validate against whitelist."""
        try:
            # Extract JSON from potential markdown code blocks
            clean = raw.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            if clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            obj = json.loads(clean)
            action = obj.get("action")
            if action not in ALLOWED_ACTIONS:
                logger.warning("Invalid action: %s", action)
                return None

            return obj
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed: %s", e)
            return None

    def _fallback_route(self, router_input: RouterInput) -> RouterOutput:
        """Rule-based fallback routing when FunctionGemma fails."""
        # Error recovery
        if router_input.error_code:
            return RouterOutput(
                action="recover_suggest",
                args={"error_code": router_input.error_code},
                raw_response="fallback",
                fallback_used=True,
            )

        # Has current region
        if router_input.current_region_id:
            return RouterOutput(
                action="respond_script",
                args={
                    "mode": "point",
                    "region_id": router_input.current_region_id,
                },
                raw_response="fallback",
                fallback_used=True,
            )

        # Default: clarify
        return RouterOutput(
            action="clarify",
            args={"question": "どの問題や文章のことか教えてね。"},
            raw_response="fallback",
            fallback_used=True,
        )

    def get_stats(self) -> Dict[str, int]:
        """Return statistics for monitoring."""
        return {
            "total_requests": self._total_requests,
            "fallback_count": self._fallback_count,
        }
