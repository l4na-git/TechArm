"""Dialogue orchestration with Router (rule-based) and DeepSeek."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..logger import get_logger
from ..materials import Region
from ..scripts import ScriptSet
from .deepseek import DeepSeekService
from .router import RouterInput, RouterService

logger = get_logger(__name__)


@dataclass
class DialogueResponse:
    text: str
    commands: List[Dict]
    source: str  # "script" | "router" | "deepseek" | "error_recovery"
    router_action: Optional[str] = None
    router_fallback: bool = False
    deepseek_time_ms: int = 0


class DialogueService:
    """Orchestrate dialogue using Router → Script → DeepSeek flow."""

    def __init__(
        self,
        settings: Settings,
        scripts: ScriptSet,
        router: RouterService,
        deepseek: DeepSeekService,
    ):
        self._settings = settings
        self._scripts = scripts
        self._router = router
        self._deepseek = deepseek
        self._last_response: Optional[DialogueResponse] = None
        self._last_region_id: Optional[str] = None

    async def on_region_event(
        self,
        region: Region,
        event: str,
        material_id: str,
        state: str = "TARGET_SELECTED",
        error_code: Optional[str] = None,
    ) -> DialogueResponse:
        """Handle region pointer event (on_point / on_help)."""
        # Build router input
        router_input = RouterInput(
            state=state,
            error_code=error_code,
            material_id=material_id,
            current_region_id=region.id,
            last_region_id=self._last_region_id,
            candidates=self._build_candidates([region]),
        )

        # Call router to determine action
        router_output = await self._router.route(router_input)
        action = router_output.action
        args = router_output.args

        # Execute action
        if action == "recover_suggest":
            return await self._handle_error_recovery(error_code)
        elif action == "respond_script":
            mode = args.get("mode", "point")
            script_event = "on_help" if mode == "help" else "on_point"
            return await self._respond_from_script(
                region, script_event, router_output
            )
        elif action == "generate_explanation":
            style = args.get("style", "hint")
            return await self._generate_with_deepseek(
                region, material_id, style, router_output
            )
        elif action == "repeat_last":
            return self._repeat_last(router_output)
        elif action == "reject":
            reason = args.get("reason", "")
            return await self._reject_request(reason, router_output)
        elif action == "clarify":
            question = args.get("question", "どの問題のことか教えてね。")
            return DialogueResponse(
                text=question,
                commands=[{"SAY": question}],
                source="router",
                router_action=action,
                router_fallback=router_output.fallback_used,
            )
        else:
            # Fallback
            return DialogueResponse(
                text="うまく理解できなかったよ。もう一度教えてね。",
                commands=[{"SAY": "うまく理解できなかったよ。もう一度教えてね。"}],
                source="router",
                router_action=action,
                router_fallback=True,
            )

    async def on_text(
        self,
        user_text: str,
        material_id: Optional[str] = None,
        current_region: Optional[Region] = None,
        state: str = "IDLE",
        require_pointing: bool = False,
        material_visible: Optional[bool] = None,
        pointer_coords: Optional[Dict[str, float]] = None,
        prepend_point_ack: bool = False,
    ) -> DialogueResponse:
        """Handle user text input through Router."""
        text = user_text.strip()

        # Quick greeting check
        if self._is_greeting_only(text):
            msg = self._scripts.intent.greeting_reply
            response = DialogueResponse(
                text=msg,
                commands=[{"SAY": msg}],
                source="script",
            )
            self._last_response = response
            return response

        # Build router input
        router_input = RouterInput(
            state=state,
            asr_text=text,
            material_id=material_id,
            current_region_id=(
                current_region.id if current_region else None
            ),
            last_region_id=self._last_region_id,
            candidates=self._build_candidates(
                [current_region] if current_region else []
            ),
            require_pointing=require_pointing,
            material_visible=material_visible,
        )

        # Call router
        router_output = await self._router.route(router_input)
        action = router_output.action
        args = router_output.args

        # Execute action
        if action == "respond_script" and current_region:
            mode = args.get("mode", "point")
            script_event = "on_help" if mode == "help" else "on_point"
            response = await self._respond_from_script(
                current_region,
                script_event,
                router_output,
                pointer_coords=pointer_coords,
                user_speech=text,
            )
            if prepend_point_ack:
                self._prepend_point_ack(response, current_region)
            return response
        elif action == "generate_explanation" and current_region:
            style = args.get("style", "hint")
            response = await self._generate_with_deepseek(
                current_region,
                material_id or "",
                style,
                router_output,
                pointer_coords=pointer_coords,
                user_speech=text,
            )
            if prepend_point_ack:
                self._prepend_point_ack(response, current_region)
            return response
        elif action == "material_not_visible":
            message = "ごめんね。教材が見えないよ。教材を写してね"
            return DialogueResponse(
                text=message,
                commands=[{"SAY": message}],
                source="router",
                router_action=action,
                router_fallback=router_output.fallback_used,
            )
        elif action == "pointing_unknown":
            message = (
                "ごめんね。どこを指しているか分からなかったよ。もう一度教えて"
            )
            return DialogueResponse(
                text=message,
                commands=[{"SAY": message}],
                source="router",
                router_action=action,
                router_fallback=router_output.fallback_used,
            )
        elif action == "repeat_last":
            return self._repeat_last(router_output)
        elif action == "reject":
            reason = args.get("reason", "")
            return await self._reject_request(reason, router_output)
        elif action == "clarify":
            question = args.get("question", "どの問題のことか教えてね。")
            return DialogueResponse(
                text=question,
                commands=[{"SAY": question}],
                source="router",
                router_action=action,
                router_fallback=router_output.fallback_used,
            )
        else:
            # Fallback
            return DialogueResponse(
                text="うまく理解できなかったよ。もう一度教えてね。",
                commands=[{"SAY": "うまく理解できなかったよ。もう一度教えてね。"}],
                source="router",
                router_action=action,
                router_fallback=True,
            )

    async def _respond_from_script(
        self,
        region: Region,
        event: str,
        router_output: Any,
        pointer_coords: Optional[Dict[str, float]] = None,
        user_speech: Optional[str] = None,
    ) -> DialogueResponse:
        """Generate response from region script."""
        script = getattr(region, "script", None)
        if not script:
            # No script available, generate with DeepSeek
            return await self._generate_with_deepseek(
                region,
                "",
                "hint",
                router_output,
                pointer_coords=pointer_coords,
                user_speech=user_speech,
            )

        command_names = script.get(event, [])
        if not command_names:
            return await self._generate_with_deepseek(
                region,
                "",
                "hint",
                router_output,
                pointer_coords=pointer_coords,
                user_speech=user_speech,
            )

        response = await self._run_commands(command_names, "script")
        response.router_action = router_output.action
        response.router_fallback = router_output.fallback_used
        self._last_response = response
        self._last_region_id = region.id
        return response

    async def _generate_with_deepseek(
        self,
        region: Region,
        material_id: str,
        style: str,
        router_output: Any,
        pointer_coords: Optional[Dict[str, float]] = None,
        user_speech: Optional[str] = None,
    ) -> DialogueResponse:
        """Generate explanation using DeepSeek."""
        result = await self._deepseek.generate_explanation(
            region,
            material_id,
            style,
            pointer_coords=pointer_coords,
            user_speech=user_speech,
        )

        response = DialogueResponse(
            text=result.text,
            commands=[{"SAY": result.text}],
            source="deepseek",
            router_action=router_output.action,
            router_fallback=router_output.fallback_used,
            deepseek_time_ms=result.request_time_ms,
        )
        self._last_response = response
        self._last_region_id = region.id
        return response

    def _prepend_point_ack(
        self, response: DialogueResponse, region: Region
    ) -> None:
        """Prefix response with a pointing acknowledgement."""
        if not response.text:
            return
        label = region.label or region.id
        ack = f"{label}の問題だね。"
        response.text = f"{ack} {response.text}".strip()
        response.commands = [{"SAY": ack}] + response.commands

    def _repeat_last(self, router_output: Any) -> DialogueResponse:
        """Repeat the last response."""
        if not self._last_response:
            return DialogueResponse(
                text="まだ何も説明していないよ。",
                commands=[{"SAY": "まだ何も説明していないよ。"}],
                source="router",
                router_action="repeat_last",
                router_fallback=router_output.fallback_used,
            )

        response = DialogueResponse(
            text=self._last_response.text,
            commands=self._last_response.commands,
            source="router",
            router_action="repeat_last",
            router_fallback=router_output.fallback_used,
        )
        return response

    async def _reject_request(
        self, reason: str, router_output: Any
    ) -> DialogueResponse:
        """Reject out-of-scope request."""
        return await self._run_commands_with_router(
            ["SAY_OUT_OF_SCOPE"], "script", router_output
        )

    async def _handle_error_recovery(
        self, error_code: Optional[str]
    ) -> DialogueResponse:
        """Handle error recovery suggestions."""
        recovery_messages = {
            "E_CAM": "カメラが見えないみたい。接続を確認してね。",
            "E_MARKER": "マーカーが見えないよ。4つ全部が映るようにしてね。",
            "E_HAND": "手が見えないよ。カメラの前に手を出してみて。",
            "E_ARM": "アームが動かないみたい。接続を確認してね。",
            "E_INTERNAL": "ちょっと調子が悪いみたい。もう一度やってみて。",
        }

        message = recovery_messages.get(
            error_code or "",
            "何か問題があるみたい。もう一度やってみてね。",
        )

        return DialogueResponse(
            text=message,
            commands=[{"SAY": message}],
            source="error_recovery",
            router_action="recover_suggest",
        )

    async def _run_commands(
        self, names: List[str], source: str
    ) -> DialogueResponse:
        """Execute command list from scripts."""
        steps: List[Dict] = []
        speech: List[str] = []
        for name in names:
            command_steps = self._scripts.commands.get(name)
            if not command_steps:
                continue
            for step in command_steps:
                if "SAY" in step:
                    speech.append(step["SAY"])
                steps.append(step)
        text = " ".join(speech) if speech else ""
        return DialogueResponse(text=text, commands=steps, source=source)

    async def _run_commands_with_router(
        self, names: List[str], source: str, router_output: Any
    ) -> DialogueResponse:
        """Execute command list and attach router info."""
        response = await self._run_commands(names, source)
        response.router_action = router_output.action
        response.router_fallback = router_output.fallback_used
        return response

    def _is_greeting_only(self, text: str) -> bool:
        """Check if text is a greeting only."""
        if len(text) > 30:
            return False
        normalized = re.sub(r"[\s、。,.!！?？ー-]", "", text)
        terms = self._scripts.intent.greeting_terms
        return any(normalized == word for word in terms)

    def _build_candidates(
        self, regions: List[Optional[Region]]
    ) -> List[Dict[str, Any]]:
        """Build candidate list for router input."""
        candidates = []
        for region in regions:
            if not region:
                continue
            script = getattr(region, "script", None)
            candidates.append({
                "id": region.id,
                "type": region.type,
                "label": region.label or region.id,
                "has_help": bool(script and script.get("on_help")),
                "has_point": bool(script and script.get("on_point")),
            })
        return candidates
