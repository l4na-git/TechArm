"""Runtime application state container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class AppState:
    """Holds mutable state for the running server."""

    active_material: Optional[str] = None
    last_region: Optional[str] = None
    vision_material_visible: bool = False
    vision_hand_detected: bool = False
    vision_current_region: Optional[str] = None
    vision_current_material: Optional[str] = None
    vision_pointer: Optional[Dict[str, float]] = None
    vision_last_update: Optional[float] = None
    status_flags: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict:
        return {
            "active_material": self.active_material,
            "last_region": self.last_region,
            "vision_material_visible": self.vision_material_visible,
            "vision_hand_detected": self.vision_hand_detected,
            "vision_current_region": self.vision_current_region,
            "vision_current_material": self.vision_current_material,
            "vision_pointer": self.vision_pointer,
            "vision_last_update": self.vision_last_update,
            "status_flags": self.status_flags,
        }
