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
            logger.info("FunctionGemma raw response: %s", raw_response)
            parsed = self._parse_and_validate(raw_response)
            if parsed:
                logger.info("FunctionGemma parsed action: %s", parsed["action"])
                return RouterOutput(
                    action=parsed["action"],
                    args=parsed.get("args", {}),
                    raw_response=raw_response,
                    fallback_used=False,
                )
            else:
                logger.warning("FunctionGemma response failed validation")
        except Exception as e:
            logger.warning("FunctionGemma call failed: %s", e)

        # Fallback to rule-based routing
        self._fallback_count += 1
        logger.info("Using fallback routing for input: %s", router_input.to_dict())
        return self._fallback_route(router_input)

    async def _call_function_gemma(self, router_input: RouterInput) -> str:
        """Call FunctionGemma API using Ollama's /api/chat endpoint with tools."""
        # Build user message in English for better tool calling
        input_data = router_input.to_dict()
        user_text = input_data.get("asr_text", "")
        state = input_data.get("state", "IDLE")
        current_region = input_data.get("current_region_id")
        
        user_message = f"User request: '{user_text}'. What should the system do?"

        # Define available actions as tools (order matters - reject first for priority)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "reject",
                    "description": "Reject requests about games, playing, chatting, personal information, age, location, or anything unrelated to learning. Examples: 'let's play a game', 'I'm bored', 'how old are you', 'where do you live'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Why rejected: out_of_scope, inappropriate, or personal_info"
                            }
                        },
                        "required": ["reason"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "respond_script",
                    "description": "Use when user asks about learning content or points to a specific question/text on the material",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "description": "point for explanation, help for hints"
                            }
                        },
                        "required": ["mode"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "repeat_last",
                    "description": "Use when user asks to repeat or say again",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "clarify",
                    "description": "Use when user request is unclear or ambiguous",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
        ]

        payload = {
            "model": self._model,
            "messages": [
                # Few-shot examples to guide the model
                {"role": "user", "content": "User request: 'let's play a game'. What should the system do?"},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "reject", "arguments": {"reason": "out_of_scope"}}}]},
                {"role": "user", "content": "User request: 'I'm bored'. What should the system do?"},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "reject", "arguments": {"reason": "out_of_scope"}}}]},
                {"role": "user", "content": "User request: 'how old are you?'. What should the system do?"},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "reject", "arguments": {"reason": "personal_info"}}}]},
                {"role": "user", "content": "User request: 'explain this question'. What should the system do?"},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "respond_script", "arguments": {"mode": "point"}}}]},
                {"role": "user", "content": "User request: 'say that again'. What should the system do?"},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "repeat_last", "arguments": {}}}]},
                # Actual user request
                {"role": "user", "content": user_message}
            ],
            "tools": tools,
            "stream": False,
        }

        logger.debug("Calling FunctionGemma with model: %s", self._model)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            logger.info("FunctionGemma API response: %s", data)
            
            # Check if tool_calls exist
            message = data.get("message", {})
            tool_calls = message.get("tool_calls")
            
            if tool_calls and len(tool_calls) > 0:
                # Extract first tool call
                tool_call = tool_calls[0]
                function_data = tool_call.get("function", {})
                action = function_data.get("name")
                args = function_data.get("arguments", {})
                
                # Return as JSON
                result = {"action": action, "args": args}
                return json.dumps(result, ensure_ascii=False)
            else:
                # No tool call, return empty (will trigger fallback)
                logger.warning("No tool_calls in FunctionGemma response, message content: %s", 
                             message.get("content", ""))
                return ""

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
  {"reason": "out_of_scope"|"inappropriate"|"personal_info"}
- clarify: regionが特定できない等、聞き返し
  {"question": "..."}
- recover_suggest: エラー復帰誘導 {"error_code": "..."}

判定優先順位:
1. error_code != null → recover_suggest
2. asr_textが学習外の内容（ゲーム、雑談、個人情報等） → reject
   例: 「ゲームしよう」「遊ぼう」「何歳？」「どこに住んでる？」
3. コマンド(もう一回/次/ヒント) →
   repeat_last / next_region / respond_script
4. current_region_id があり region.script が使える →
   respond_script
5. current_region_id があるが台本が無い →
   generate_explanation
6. 上記以外 → clarify

重要: 学習（教材の問題や文章）に関係ない要求は必ずrejectすること。

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

        # Check for out-of-scope requests (simple pattern matching)
        if router_input.asr_text:
            text_lower = router_input.asr_text.lower()
            out_of_scope_keywords = [
                "ゲーム", "遊", "暇", "雑談", "天気", "何歳", "年齢", 
                "どこ住", "住所", "電話", "名前", "恋", "好き", "彼女", "彼氏"
            ]
            if any(keyword in text_lower for keyword in out_of_scope_keywords):
                return RouterOutput(
                    action="reject",
                    args={"reason": "out_of_scope"},
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
