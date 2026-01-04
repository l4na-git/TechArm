"""Dialogue script loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml


@dataclass
class IntentConfig:
    greeting_reply: str
    fallback_reply: str
    greeting_terms: List[str]
    on_topic: List[str]
    off_topic: List[str]


@dataclass
class RoleProfile:
    name: str
    tone: str
    rules: List[str]


@dataclass
class NegativeRule:
    id: str
    when: str
    action: List[str]


@dataclass
class ScriptSet:
    role: RoleProfile
    intent: IntentConfig
    negative_rules: List[NegativeRule]
    commands: Dict[str, List[Dict[str, str]]]

    @classmethod
    def from_dict(cls, data: Dict) -> "ScriptSet":
        role_data = data.get("role", {})
        role = RoleProfile(
            name=role_data.get("name", "Teacher"),
            tone=role_data.get("tone", ""),
            rules=role_data.get("rules", []),
        )
        intent_data = data.get("intent", {})
        intent = IntentConfig(
            greeting_reply=intent_data.get(
                "greeting_reply",
                "こんにちは！今日はどの教材の、どのあたりで困ってる？（文章/選択肢/言葉など）",
            ),
            fallback_reply=intent_data.get(
                "fallback_reply",
                "どの教材のどこが気になる？（文章/選択肢/言葉）",
            ),
            greeting_terms=intent_data.get(
                "greeting_terms",
                ["こんにちは", "おはよう", "こんばんは", "やあ", "はじめまして", "こんちは"],
            ),
            on_topic=intent_data.get(
                "on_topic",
                [
                    "教材の内容",
                    "問題",
                    "このアプリの使い方",
                    "学習の進め方",
                    "TeachArmの操作",
                ],
            ),
            off_topic=intent_data.get(
                "off_topic",
                [
                    "ゲームに誘う",
                    "雑談を続ける",
                    "学習と無関係な話題（天気/恋バナ/暇つぶし等）",
                ],
            ),
        )
        negative = [
            NegativeRule(
                id=item.get("id", ""),
                when=item.get("when", ""),
                action=item.get("action", []),
            )
            for item in data.get("negative_rules", [])
        ]
        commands = data.get("commands", {})
        return cls(role=role, intent=intent, negative_rules=negative, commands=commands)


def load_scripts(path: Path) -> ScriptSet:
    """Load YAML file describing dialogue scripts."""
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    return ScriptSet.from_dict(content)
