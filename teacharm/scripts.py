"""Dialogue script loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml


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
        negative = [
            NegativeRule(
                id=item.get("id", ""),
                when=item.get("when", ""),
                action=item.get("action", []),
            )
            for item in data.get("negative_rules", [])
        ]
        commands = data.get("commands", {})
        return cls(role=role, negative_rules=negative, commands=commands)


def load_scripts(path: Path) -> ScriptSet:
    """Load YAML file describing dialogue scripts."""
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    return ScriptSet.from_dict(content)
