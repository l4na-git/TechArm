"""Marker-based UV -> XY mapping for fixed workspaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from ..logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class MarkerCorner:
    """Single marker corner mapping."""

    id: str
    u: float
    v: float
    x: float
    y: float


class MarkerMapping:
    """Map normalized (u,v) to arm (x,y) using 4 marker corners."""

    def __init__(self) -> None:
        self.corners: Dict[str, MarkerCorner] = {}
        self._homography: Optional[np.ndarray] = None

    @classmethod
    def from_file(cls, filepath: Path) -> "MarkerMapping":
        mapping = cls()
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            logger.warning("Failed to load marker mapping file: %s", exc)
            return mapping

        for item in data.get("corners", []):
            try:
                corner = MarkerCorner(
                    id=item["id"],
                    u=float(item["u"]),
                    v=float(item["v"]),
                    x=float(item["x"]),
                    y=float(item["y"]),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Skipping invalid marker corner: %s", item)
                continue
            mapping.corners[corner.id] = corner

        if mapping.is_complete():
            mapping._homography = mapping._compute_homography()
            logger.info("Loaded marker mapping with %d corners", len(mapping.corners))
        else:
            logger.warning("Marker mapping incomplete (%d corners)", len(mapping.corners))
        return mapping

    def is_complete(self) -> bool:
        required = {"top_left", "top_right", "bottom_right", "bottom_left"}
        return required.issubset(self.corners.keys())

    def uv_to_xyz(self, u: float, v: float) -> Tuple[float, float, float]:
        if self._homography is None and not self.is_complete():
            raise ValueError("Marker mapping incomplete: missing corners")
        if self._homography is None:
            self._homography = self._compute_homography()
        point = np.array([u, v, 1.0], dtype=float)
        mapped = self._homography @ point
        if mapped[2] == 0:
            raise ValueError("Marker mapping failed: invalid homography")
        x = mapped[0] / mapped[2]
        y = mapped[1] / mapped[2]
        return float(x), float(y), 0.0

    def _compute_homography(self) -> np.ndarray:
        src = np.array(
            [
                [self.corners["top_left"].u, self.corners["top_left"].v],
                [self.corners["top_right"].u, self.corners["top_right"].v],
                [self.corners["bottom_right"].u, self.corners["bottom_right"].v],
                [self.corners["bottom_left"].u, self.corners["bottom_left"].v],
            ],
            dtype=float,
        )
        dst = np.array(
            [
                [self.corners["top_left"].x, self.corners["top_left"].y],
                [self.corners["top_right"].x, self.corners["top_right"].y],
                [self.corners["bottom_right"].x, self.corners["bottom_right"].y],
                [self.corners["bottom_left"].x, self.corners["bottom_left"].y],
            ],
            dtype=float,
        )

        a_rows = []
        for (u, v), (x, y) in zip(src, dst):
            a_rows.append([-u, -v, -1.0, 0.0, 0.0, 0.0, u * x, v * x, x])
            a_rows.append([0.0, 0.0, 0.0, -u, -v, -1.0, u * y, v * y, y])
        a = np.array(a_rows, dtype=float)
        _, _, vt = np.linalg.svd(a)
        h = vt[-1].reshape(3, 3)
        return h / h[2, 2]
