"""Dialogue orchestration built on top of scripts and Ollama."""

from __future__ import annotations

import json
import json
from dataclasses import dataclass
from typing import Dict, List

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

    async def on_region_event(
        self, region: Region, event: str
    ) -> DialogueResponse:
        command_names = getattr(region, event, [])
        if not command_names:
            return await self._call_llm(
                [{"role": "user", "content": f"{region.id}"}]
            )
        return await self._run_commands(command_names, source="script")

    async def on_text(self, user_text: str) -> DialogueResponse:
        text = user_text.strip()
        intent_cfg = self._scripts.intent

        # 1) Greeting is always allowed.
        if self._is_greeting(text, intent_cfg.greeting_terms):
            msg = intent_cfg.greeting_reply
            return DialogueResponse(
                text=msg, commands=[{"SAY": msg}], source="script"
            )

        # 2) Ask LLM to classify intent via JSON.
        role = self._scripts.role
        on_topic = "\n".join([f"- {item}" for item in intent_cfg.on_topic])
        off_topic = "\n".join([f"- {item}" for item in intent_cfg.off_topic])
        system = "\n".join(
            [
                f"あなたは{role.name}。口調:{role.tone}。",
                "次のJSONだけを返して。他の文字は絶対に出さない。",
                '{"intent":"GREETING|ON_TOPIC|OFF_TOPIC","reply":"..."}',
                "intentの基準:",
                "- GREETING: 挨拶、短い返事",
                "- ON_TOPIC: 教材の内容/問題/このアプリの使い方/学習の進め方/TeachArmの操作など",
                "- OFF_TOPIC: ゲームに誘う、雑談を続ける、学習と無関係な話題（天気/恋バナ/暇つぶし等）",
                "ON_TOPICの具体例:",
                on_topic,
                "OFF_TOPICの具体例:",
                off_topic,
                "ON_TOPICの返答ルール:",
                *[f"- {r}" for r in role.rules],
                "OFF_TOPICのとき reply は短く断って、学習に戻す質問を1つ添える。",
            ]
        )

        raw = await self._call_llm(
            [{"role": "system", "content": system}, {"role": "user", "content": text}]
        )

        intent = "ON_TOPIC"
        reply = raw.text
        try:
            obj = json.loads(raw.text)
            intent = obj.get("intent", "ON_TOPIC")
            reply = obj.get("reply", "") or ""
        except Exception:  # noqa: BLE001
            pass

        # 3) OFF_TOPIC is forced to negative command.
        if intent == "OFF_TOPIC":
            return await self._run_commands(["SAY_OUT_OF_SCOPE"], source="negative")

        if not reply:
            reply = intent_cfg.fallback_reply
        return DialogueResponse(text=reply, commands=[], source="llm")

    @staticmethod
    def _is_greeting(text: str, terms: List[str]) -> bool:
        if len(text) > 20:
            return False
        return any(word in text for word in terms)

    async def _run_commands(
        self, names: List[str], source: str
    ) -> DialogueResponse:
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
