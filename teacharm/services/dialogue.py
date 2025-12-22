"""Dialogue orchestration built on top of scripts and Ollama."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from ..config import Settings
from ..logger import get_logger
from ..materials import Region
from ..scripts import ScriptSet

logger = get_logger(__name__)


@dataclass
class DialogueResponse:
    text: str
    commands: List[Dict]
    source: str  # "script" | "command" | "llm"


class DialogueService:
    """Map events to dialogue responses."""

    def __init__(self, settings: Settings, scripts: ScriptSet):
        self._settings = settings
        self._scripts = scripts

    async def on_region_event(self, region: Region, event: str) -> DialogueResponse:
        command_names = getattr(region, event, [])
        if not command_names:
            return await self._call_llm([{"role": "user", "content": f"{region.id}"}])
        return await self._run_commands(command_names, source="script")

    async def on_text(self, user_text: str) -> DialogueResponse:
        # Negative rule check
        lowered = user_text.lower()
        for rule in self._scripts.negative_rules:
            if "関係" in rule.when and "?" not in lowered:
                return await self._run_commands(rule.action, source="negative")
        return await self._call_llm(
            [
                {
                    "role": "system",
                    "content": f"{self._scripts.role.name}:{self._scripts.role.tone}",
                },
                {"role": "user", "content": user_text},
            ]
        )

    async def _run_commands(self, names: List[str], source: str) -> DialogueResponse:
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

    async def _call_llm(self, messages: List[Dict]) -> DialogueResponse:
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._settings.ollama_model,
            "messages": messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM call failed: %s", exc)
            message = "今はうまくお話ができないみたい。また教えてね。"
        return DialogueResponse(text=message, commands=[], source="llm")
