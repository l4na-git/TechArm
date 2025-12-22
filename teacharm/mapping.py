"""Logic for mapping normalized pointer coordinates to material regions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .materials import Material, Region, select_best_region


@dataclass
class MappingResult:
    region: Optional[Region]
    material_id: Optional[str]
    normalized_point: Tuple[float, float]


class MaterialRepository:
    """In-memory repository of materials with selection state."""

    def __init__(self, materials: Dict[str, Material]):
        self._materials = materials
        self._current_id: Optional[str] = next(iter(materials), None)

    @property
    def current(self) -> Optional[Material]:
        if self._current_id is None:
            return None
        return self._materials.get(self._current_id)

    @property
    def current_id(self) -> Optional[str]:
        return self._current_id

    def list_materials(self) -> Dict[str, Material]:
        return self._materials

    def select(self, material_id: str) -> Material:
        if material_id not in self._materials:
            raise KeyError(f"material '{material_id}' is not defined")
        self._current_id = material_id
        return self._materials[material_id]

    def map_point(self, u: float, v: float) -> MappingResult:
        material = self.current
        if material is None:
            return MappingResult(None, None, (u, v))
        hits = material.find_hit_regions(u, v)
        region = select_best_region(hits)
        return MappingResult(region=region, material_id=material.material_id, normalized_point=(u, v))
