"""Calibration and coordinate transformation utilities for TeachArm.

Handles arm calibration point management and (u,v) -> (x,y,z) coordinate
transformation using bilinear interpolation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path

from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class CalibrationPoint:
    """A single calibration point (normalized coords -> arm coords)."""
    id: str
    u: float
    v: float
    x: float
    y: float
    z: float


class ArmCalibration:
    """Manages 9-point (3x3) grid arm calibration.
    
    Grid layout (u,v):
        p00(0,0)    p10(0.5,0)    p20(1,0)
        p01(0,0.5)  p11(0.5,0.5)  p21(1,0.5)
        p02(0,1)    p12(0.5,1)    p22(1,1)
    """

    def __init__(self):
        """Initialize with empty calibration."""
        self.points: Dict[str, CalibrationPoint] = {}
    
    @classmethod
    def from_file(cls, filepath: Path) -> ArmCalibration:
        """Load calibration from JSON file.
        
        Args:
            filepath: Path to arm_calibration.json
        
        Returns:
            ArmCalibration instance
        
        Raises:
            ValueError: If file format invalid or points missing
        """
        calib = cls()
        
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            logger.warning("Failed to load calibration file: %s", exc)
            return calib
        
        points_data = data.get("points", [])
        for pt in points_data:
            try:
                calib.points[pt["id"]] = CalibrationPoint(
                    id=pt["id"],
                    u=pt["u"],
                    v=pt["v"],
                    x=pt["x"],
                    y=pt["y"],
                    z=pt["z"],
                )
            except (KeyError, TypeError):
                logger.debug("Skipping invalid calibration point: %s", pt)
        
        logger.info("Loaded %d calibration points", len(calib.points))
        return calib

    def is_complete(self) -> bool:
        """Check if all 9 calibration points are set.
        
        Returns:
            True if all points p00..p22 have (u,v,x,y,z) values
        """
        required = {"p00", "p10", "p20", "p01", "p11", "p21", "p02", "p12", "p22"}
        
        for pt_id in required:
            if pt_id not in self.points:
                return False
            pt = self.points[pt_id]
            if None in (pt.u, pt.v, pt.x, pt.y, pt.z):
                return False
        
        return True

    def uv_to_xyz(self, u: float, v: float) -> tuple[float, float, float]:
        """Transform normalized (u,v) coordinates to arm (x,y,z).
        
        Uses bilinear interpolation within the nearest 2x2 cell.
        
        Args:
            u: Normalized u coordinate [0, 1]
            v: Normalized v coordinate [0, 1]
        
        Returns:
            (x, y, z) in mm
        
        Raises:
            ValueError: If calibration incomplete or point out of bounds
        """
        if not self.is_complete():
            raise ValueError("Calibration incomplete: missing calibration points")
        
        if not (0.0 <= u <= 1.0) or not (0.0 <= v <= 1.0):
            raise ValueError(f"Point out of bounds: u={u}, v={v} (must be in [0,1])")
        
        # Determine which cell and local position
        cell_u = 0 if u <= 0.5 else 1
        cell_v = 0 if v <= 0.5 else 1
        
        # Local position within cell [0, 1]
        if cell_u == 0:
            local_u = u * 2.0  # [0, 0.5] -> [0, 1]
        else:
            local_u = (u - 0.5) * 2.0  # [0.5, 1] -> [0, 1]
        
        if cell_v == 0:
            local_v = v * 2.0  # [0, 0.5] -> [0, 1]
        else:
            local_v = (v - 0.5) * 2.0  # [0.5, 1] -> [0, 1]
        
        # Get corner points for bilinear interpolation
        # Point naming: p<col><row> where col=0/1/2, row=0/1/2
        corners_ids = [
            (cell_u, cell_v),  # top-left (p00, p10, p01, p11, etc.)
            (cell_u + 1, cell_v),  # top-right
            (cell_u, cell_v + 1),  # bottom-left
            (cell_u + 1, cell_v + 1),  # bottom-right
        ]
        
        # Map to actual point IDs
        point_ids = []
        for col, row in corners_ids:
            pt_id = f"p{col}{row}"
            if pt_id not in self.points:
                raise ValueError(f"Missing calibration point: {pt_id}")
            point_ids.append(pt_id)
        
        # Bilinear interpolation
        p00 = self.points[point_ids[0]]
        p10 = self.points[point_ids[1]]
        p01 = self.points[point_ids[2]]
        p11 = self.points[point_ids[3]]
        
        # Interpolate x, y, z separately
        x = self._bilinear(p00.x, p10.x, p01.x, p11.x, local_u, local_v)
        y = self._bilinear(p00.y, p10.y, p01.y, p11.y, local_u, local_v)
        z = self._bilinear(p00.z, p10.z, p01.z, p11.z, local_u, local_v)
        
        return x, y, z

    @staticmethod
    def _bilinear(
        val00: float,
        val10: float,
        val01: float,
        val11: float,
        u: float,
        v: float,
    ) -> float:
        """Bilinear interpolation.
        
        Args:
            val00, val10, val01, val11: Values at (0,0), (1,0), (0,1), (1,1)
            u, v: Local interpolation parameters [0, 1]
        
        Returns:
            Interpolated value
        """
        # Linear interpolation along u axis
        val0 = val00 * (1 - u) + val10 * u
        val1 = val01 * (1 - u) + val11 * u
        
        # Linear interpolation along v axis
        return val0 * (1 - v) + val1 * v

    def set_point(self, pt_id: str, u: float, v: float, x: float, y: float, z: float) -> None:
        """Set or update a calibration point.
        
        Args:
            pt_id: Point ID (p00..p22)
            u, v: Normalized coordinates
            x, y, z: Arm coordinates in mm
        """
        self.points[pt_id] = CalibrationPoint(pt_id, u, v, x, y, z)
        logger.info("Set calibration point %s: (u=%.2f, v=%.2f) -> (%.1f, %.1f, %.1f)",
                   pt_id, u, v, x, y, z)

    def to_dict(self) -> Dict[str, Any]:
        """Export calibration as JSON-serializable dict."""
        return {
            "version": 1,
            "points": [
                {
                    "id": pt.id,
                    "u": pt.u,
                    "v": pt.v,
                    "x": pt.x,
                    "y": pt.y,
                    "z": pt.z,
                }
                for pt in self.points.values()
            ],
        }
