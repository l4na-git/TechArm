"""Utilities for loading material definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, validator


class BoundingBox(BaseModel):
    """Axis-aligned bounding box in normalized coordinates."""

    x: float
    y: float
    w: float
    h: float

    @validator("*")
    def _ensure_range(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("Bounding box coordinates must be normalized (0-1)")
        return value

    def contains(self, u: float, v: float) -> bool:
        return self.x <= u <= self.x + self.w and self.y <= v <= self.y + self.h


class Region(BaseModel):
    """A region mapped on a material."""

    id: str
    type: str
    bbox: BoundingBox
    on_point: List[str] = []
    on_help: List[str] = []


class Material(BaseModel):
    """Material definition loaded from JSON."""

    material_id: str
    regions: List[Region]

    def find_hit_regions(self, u: float, v: float) -> List[Region]:
        return [region for region in self.regions if region.bbox.contains(u, v)]


PRIORITY = {"question": 0, "line": 1, "word": 2}


def select_best_region(regions: Sequence[Region]) -> Optional[Region]:
    """Select the highest priority region among hits."""
    if not regions:
        return None
    return sorted(
        regions, key=lambda reg: (PRIORITY.get(reg.type, 99), reg.bbox.w * reg.bbox.h)
    )[0]


def load_materials(material_dir: Path) -> Dict[str, Material]:
    """Load all material JSON files from a directory."""
    materials: Dict[str, Material] = {}
    for json_file in sorted(material_dir.glob("*.json")):
        with json_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        material = Material(**data)
        materials[material.material_id] = material
    return materials
