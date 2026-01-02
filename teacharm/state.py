"""Runtime application state container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class AppState:
    """Holds mutable state for the running server."""

    active_material: Optional[str] = None
    last_region: Optional[str] = None
    status_flags: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict:
        return {
            "active_material": self.active_material,
            "last_region": self.last_region,
            "status_flags": self.status_flags,
        }
