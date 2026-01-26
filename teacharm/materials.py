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
    extracted_text: Optional[str] = None  # PDF抽出テキスト
    refs_hint: List[str] = []  # ヒント向け参照先（優先順）
    refs_explain: List[str] = []  # 解説向け参照先（優先順）


class Material(BaseModel):
    """Material definition loaded from JSON."""

    material_id: str
    pdf_file: Optional[str] = None
    regions: List[Region]
    full_text: Optional[str] = None  # PDF全文（全ページ統合）
    pages: Optional[List[Dict]] = None  # ページごとの構造化データ

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
    # Load material_*.json files only
    for json_file in sorted(material_dir.glob("material_*.json")):
        with json_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        material = Material(**data)
        
        # PDF抽出テキストがあれば読み込む
        text_file = material_dir / f"{material.material_id}_text.json"
        if text_file.exists():
            with text_file.open("r", encoding="utf-8") as tf:
                text_data = json.load(tf)
                # 全ページテキストを統合
                full_text_parts = []
                for page in text_data.get("pages", []):
                    for block in page.get("blocks", []):
                        full_text_parts.append(block.get("text", ""))
                material.full_text = "\n".join(full_text_parts)
                material.pages = text_data.get("pages")
                
                # regionごとの抽出テキストをマージ
                for text_region in text_data.get("regions", []):
                    region_id = text_region.get("id")
                    extracted = text_region.get("extracted_text", "")
                    region_obj = material.get_region(region_id)
                    if region_obj:
                        region_obj.extracted_text = extracted
        
        materials[material.material_id] = material
    return materials
