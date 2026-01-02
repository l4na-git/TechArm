"""Stub implementation for controlling the so-101 arm."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class ArmCommand:
    x: float
    y: float
    z: float
    speed: float = 0.2


class ArmService:
    """A lightweight placeholder for the so-101 control layer."""

    def __init__(self, config: Dict):
        self._config = config
        self._connected = False

    async def connect(self, port: str = "/dev/ttyUSB0") -> None:
        logger.info("Connecting to so-101 arm via %s", port)
        self._connected = True

    async def ensure_calibrated(self) -> None:
        if not self._connected:
            await self.connect()
        logger.info("Ensuring calibration (stub)")

    async def move_to(self, command: ArmCommand) -> None:
        await self.ensure_calibrated()
        logger.info(
            "Moving arm to (%.3f, %.3f, %.3f) speed=%.2f",
            command.x, command.y, command.z, command.speed
        )

    async def go_safe_pose(self) -> None:
        await self.ensure_calibrated()
        pose = self._config.get("safe_pose")
        if not pose:
            logger.warning("Safe pose not configured")
            return
        await self.move_to(
            ArmCommand(x=pose["x"], y=pose["y"], z=pose["z"])
        )

    async def stop(self) -> None:
        logger.info("Stopping arm (stub)")
