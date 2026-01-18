"""Rule-based routing service for action decision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class RouterInput:
    """Input structure for router."""

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
    """Output structure from router."""

    action: str
    args: Dict[str, Any]
    raw_response: str
    fallback_used: bool = False


class RouterService:
    """Rule-based routing service for determining next action."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._total_requests = 0
        self._reject_count = 0

    async def route(self, router_input: RouterInput) -> RouterOutput:
        """
        Determine the next action using rule-based logic.
        Fast, reliable, and easy to debug.
        """
        self._total_requests += 1

        # Rule 1: Error recovery
        if router_input.error_code:
            return RouterOutput(
                action="recover_suggest",
                args={"error_code": router_input.error_code},
                raw_response="rule_based",
                fallback_used=False,
            )

        # Rule 2: Out-of-scope rejection (games, chitchat, personal info)
        if router_input.asr_text:
            text_lower = router_input.asr_text.lower()
            
            # Learning-unrelated keywords
            out_of_scope_keywords = [
                "ゲーム", "遊", "暇", "つまらない", "退屈",
                "何歳", "年齢", "どこ住", "住所", "行きたい", "出かけ",
                "電話", "名前", "恋", "好き", "彼女", "彼氏",
                "game", "play", "bored", "age", "old"
            ]
            if any(keyword in text_lower for keyword in out_of_scope_keywords):
                self._reject_count += 1
                logger.info(
                    "Rejected out-of-scope request: %s", router_input.asr_text
                )
                return RouterOutput(
                    action="reject",
                    args={"reason": "out_of_scope"},
                    raw_response="rule_based",
                    fallback_used=False,
                )

            # Rule 3: Repeat commands
            repeat_keywords = ["もう一回", "もう一度", "繰り返", "again", "repeat"]
            if any(keyword in text_lower for keyword in repeat_keywords):
                return RouterOutput(
                    action="repeat_last",
                    args={},
                    raw_response="rule_based",
                    fallback_used=False,
                )

            # Rule 4: Help/hint requests
            help_keywords = ["ヒント", "わからない", "難しい", "教えて", "hint", "help"]
            if any(keyword in text_lower for keyword in help_keywords):
                if router_input.current_region_id:
                    return RouterOutput(
                        action="respond_script",
                        args={
                            "mode": "help",
                            "region_id": router_input.current_region_id,
                        },
                        raw_response="rule_based",
                        fallback_used=False,
                    )
                else:
                    return RouterOutput(
                        action="clarify",
                        args={"question": "どの問題のヒントがほしい？"},
                        raw_response="rule_based",
                        fallback_used=False,
                    )

        # Rule 5: Current region exists -> use script
        if router_input.current_region_id:
            return RouterOutput(
                action="respond_script",
                args={
                    "mode": "point",
                    "region_id": router_input.current_region_id,
                },
                raw_response="rule_based",
                fallback_used=False,
            )

        # Rule 6: Default -> clarify
        return RouterOutput(
            action="clarify",
            args={"question": "どの問題や文章のことか教えてね。"},
            raw_response="rule_based",
            fallback_used=False,
        )

    def get_stats(self) -> Dict[str, int]:
        """Return statistics for monitoring."""
        return {
            "total_requests": self._total_requests,
            "reject_count": self._reject_count,
        }

