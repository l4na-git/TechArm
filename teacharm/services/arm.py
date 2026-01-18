"""SO-101 arm controller implementation.

SO-101 is a 6-DOF robot arm using Feetech STS3215 servo motors.
Motor configuration:
  - Joint 1 (Base/Shoulder Pan): ID=1, gear ratio 1/191
  - Joint 2 (Shoulder Lift):     ID=2, gear ratio 1/345
  - Joint 3 (Elbow Flex):        ID=3, gear ratio 1/191
  - Joint 4 (Wrist Flex):        ID=4, gear ratio 1/147
  - Joint 5 (Wrist Roll):        ID=5, gear ratio 1/147
  - Joint 6 (Gripper):           ID=6, gear ratio 1/147

Reference: https://huggingface.co/docs/lerobot/en/so101
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import math

from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class JointConfig:
    """Configuration for a single SO-101 motor/joint."""
    id: int
    name: str
    gear_ratio: str
    min_angle: Optional[float] = None  # degrees
    max_angle: Optional[float] = None  # degrees


# SO-101 motor specifications from LeRobot documentation
SO101_JOINTS = [
    JointConfig(1, "shoulder_pan", "1/191"),
    JointConfig(2, "shoulder_lift", "1/345"),
    JointConfig(3, "elbow_flex", "1/191"),
    JointConfig(4, "wrist_flex", "1/147"),
    JointConfig(5, "wrist_roll", "1/147"),
    JointConfig(6, "gripper", "1/147"),
]


@dataclass
class ArmCommand:
    """Cartesian position command for arm end-effector."""
    x: float
    y: float
    z: float
    speed: float = 0.2


@dataclass
class JointCommand:
    """Joint angle command for SO-101 motors."""
    angles: List[float]  # 6 angles in degrees, one per joint
    speed: float = 0.2


class ArmService:
    """SO-101 arm control service using Feetech motors."""

    def __init__(self, config: Dict):
        self._config = config
        self._connected = False
        self._calibrated = False
        self._port = None
        self._joints = SO101_JOINTS
        # TODO: Initialize Feetech SDK connection when implementing real control
        # from lerobot.common.robot_devices.motors.feetech import FeetechMotorsBus
        # self._motor_bus = None

    async def connect(self, port: str = "/dev/ttyUSB0") -> None:
        """Connect to SO-101 arm via USB serial port.
        
        Args:
            port: Serial port path (e.g., /dev/ttyUSB0, /dev/ttyACM0)
                  Use lerobot-find-port to discover the correct port.
        """
        logger.info("Connecting to SO-101 arm via %s", port)
        self._port = port
        # TODO: Initialize motor bus connection
        # self._motor_bus = FeetechMotorsBus(port=port, motors=self._joints)
        # await self._motor_bus.connect()
        self._connected = True

    async def ensure_calibrated(self) -> None:
        """Ensure SO-101 is calibrated and ready for motion.
        
        Calibration establishes joint angle offsets to ensure consistent
        positioning across different SO-101 units. Required before any motion.
        """
        if not self._connected:
            await self.connect()
        if self._calibrated:
            return
        
        logger.info("Ensuring SO-101 calibration")
        # TODO: Load calibration from config or perform calibration
        # Calibration data should be loaded from arm_calibration.json
        # Reference: lerobot-calibrate command from LeRobot
        self._calibrated = True

    async def move_to(self, command: ArmCommand) -> None:
        """Move end-effector to Cartesian position (requires IK).
        
        Args:
            command: Target position and speed
            
        Note:
            Requires inverse kinematics to convert (x,y,z) to joint angles.
            Currently stubbed - implement IK solver for SO-101 kinematics.
        """
        await self.ensure_calibrated()
        logger.info(
            "Moving SO-101 to (%.3f, %.3f, %.3f) speed=%.2f",
            command.x, command.y, command.z, command.speed
        )
        # TODO: Implement inverse kinematics
        # joint_angles = self._inverse_kinematics(command.x, command.y, command.z)
        # await self.move_joints(JointCommand(angles=joint_angles, speed=command.speed))
    
    async def move_joints(self, command: JointCommand) -> None:
        """Move joints to specified angles.
        
        Args:
            command: Target joint angles (6 values in degrees) and speed
            
        Raises:
            ValueError: If angle count != 6 or angles exceed joint limits
        """
        await self.ensure_calibrated()
        
        if len(command.angles) != 6:
            raise ValueError(f"SO-101 requires 6 joint angles, got {len(command.angles)}")
        
        # Validate joint limits if configured
        for i, (joint, angle) in enumerate(zip(self._joints, command.angles)):
            if joint.min_angle is not None and angle < joint.min_angle:
                logger.warning(f"Joint {i+1} ({joint.name}): {angle}° below min {joint.min_angle}°")
            if joint.max_angle is not None and angle > joint.max_angle:
                logger.warning(f"Joint {i+1} ({joint.name}): {angle}° exceeds max {joint.max_angle}°")
        
        logger.info(
            "Moving SO-101 joints: [%.1f, %.1f, %.1f, %.1f, %.1f, %.1f] deg @ speed=%.2f",
            *command.angles, command.speed
        )
        # TODO: Send joint commands via motor bus
        # await self._motor_bus.write("Goal_Position", command.angles)

    async def go_safe_pose(self) -> None:
        """Move arm to configured safe pose.
        
        Safe pose can be defined as joint angles (preferred) or Cartesian coordinates.
        """
        await self.ensure_calibrated()
        pose = self._config.get("safe_pose")
        if not pose:
            logger.warning("Safe pose not configured")
            return
        
        if pose.get("type") == "joint_angles" and pose.get("angles"):
            # Preferred: Use joint angle specification
            await self.move_joints(
                JointCommand(angles=pose["angles"], speed=0.2)
            )
        elif pose.get("x") is not None:
            # Legacy: Use Cartesian coordinates (requires IK)
            await self.move_to(
                ArmCommand(x=pose["x"], y=pose["y"], z=pose["z"])
            )
        else:
            logger.warning("Safe pose not properly configured (missing angles or xyz)")

    async def get_joint_positions(self) -> List[float]:
        """Read current joint angles from motors.
        
        Returns:
            List of 6 joint angles in degrees
        """
        await self.ensure_calibrated()
        # TODO: Read from motor bus
        # positions = await self._motor_bus.read("Present_Position")
        # return positions
        logger.info("Reading SO-101 joint positions (stub)")
        return [0.0] * 6
    
    async def stop(self) -> None:
        """Emergency stop - halt all motors immediately."""
        logger.info("Stopping SO-101 arm")
        # TODO: Send stop command to all motors
        # await self._motor_bus.write("Torque_Enable", [0] * 6)
    
    async def disconnect(self) -> None:
        """Safely disconnect from SO-101 motors."""
        if self._connected:
            await self.stop()
            # TODO: Close motor bus connection
            # await self._motor_bus.disconnect()
            self._connected = False
            logger.info("Disconnected from SO-101")
