"""Utilities for loading material definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

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
            raise ValueError(
                "Bounding box coordinates must be normalized (0-1)"
            )
        return value

    def contains(self, u: float, v: float) -> bool:
        in_x = self.x <= u <= self.x + self.w
        in_y = self.y <= v <= self.y + self.h
        return in_x and in_y


class Region(BaseModel):
    """A region mapped on a material."""

    id: str
    type: str
    label: Optional[str] = None
    bbox: BoundingBox
    on_point: List[str] = []
    on_help: List[str] = []


class Material(BaseModel):
    """Material definition loaded from JSON."""

    material_id: str
    pdf_file: Optional[str] = None
    regions: List[Region]

    def find_hit_regions(self, u: float, v: float) -> List[Region]:
        return [
            region for region in self.regions
            if region.bbox.contains(u, v)
        ]

    def get_region(self, region_id: str) -> Optional[Region]:
        """Get a region by its ID."""
        for region in self.regions:
            if region.id == region_id:
                return region
        return None


PRIORITY = {
    "instruction": 0,  # 大問の指示文（最優先）
    "question": 1,      # 設問
    "choice": 2,        # 選択肢
    "paragraph": 3,     # 段落
    "line": 4,          # 行
    "word": 5,          # 単語
    "diagram": 6,       # 図表
}


def select_best_region(regions: Sequence[Region]) -> Optional[Region]:
    """Select the highest priority region among hits."""
    if not regions:
        return None

    def sort_key(reg: Region) -> tuple:
        return (PRIORITY.get(reg.type, 99), reg.bbox.w * reg.bbox.h)

    return sorted(regions, key=sort_key)[0]


def load_materials(material_dir: Path) -> Dict[str, Material]:
    """Load all material JSON files from a directory."""
    materials: Dict[str, Material] = {}
    for json_file in sorted(material_dir.glob("*.json")):
        with json_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        material = Material(**data)
        materials[material.material_id] = material
    return materials
