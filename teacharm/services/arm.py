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
import inspect
from typing import Any, Dict, List, Optional
import math

from ..logger import get_logger
from ..kinematics import solve_ik

logger = get_logger(__name__)

try:
    from lerobot.common.robot_devices.motors.feetech import FeetechMotorsBus
    try:
        from lerobot.common.robot_devices.motors.feetech import FeetechMotor
    except ImportError:
        FeetechMotor = None
    Motor = None
    MotorNormMode = None
except ImportError:
    try:
        from lerobot.motors.feetech import FeetechMotorsBus
    except ImportError:
        FeetechMotorsBus = None
    FeetechMotor = None
    try:
        from lerobot.motors.motors_bus import Motor, MotorNormMode
    except ImportError:
        Motor = None
        MotorNormMode = None


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

    def __init__(
        self,
        config: Dict,
        port: Optional[str] = None,
        baudrate: Optional[int] = None,
    ):
        self._config = config
        self._connected = False
        self._calibrated = False
        self._port = port
        self._baudrate = (
            baudrate
            if baudrate is not None
            else config.get("motor_config", {}).get("baudrate", 1000000)
        )
        self._joints = self._load_joint_configs(config)
        self._max_speed = config.get("motion", {}).get("max_speed", 0.3)
        self._motor_bus = None
        self._last_joint_angles = [0.0] * len(self._joints)

    def _load_joint_configs(self, config: Dict) -> List[JointConfig]:
        joints = config.get("motor_config", {}).get("joints")
        if not joints:
            return SO101_JOINTS
        parsed = []
        for joint in joints:
            parsed.append(
                JointConfig(
                    id=joint["id"],
                    name=joint["name"],
                    gear_ratio=joint.get("gear_ratio", ""),
                    min_angle=joint.get("min_deg"),
                    max_angle=joint.get("max_deg"),
                )
            )
        return parsed

    def _build_motor_list(self) -> Any:
        if FeetechMotor:
            return [
                FeetechMotor(
                    id=joint.id,
                    name=joint.name,
                    gear_ratio=joint.gear_ratio,
                )
                for joint in self._joints
            ]
        if Motor and MotorNormMode:
            motors = {}
            for joint in self._joints:
                norm_mode = (
                    MotorNormMode.RANGE_0_100
                    if joint.name == "gripper"
                    else MotorNormMode.DEGREES
                )
                motors[joint.name] = Motor(joint.id, "sts3215", norm_mode)
            return motors
        return [
            {"id": joint.id, "name": joint.name, "gear_ratio": joint.gear_ratio}
            for joint in self._joints
        ]

    def _build_motor_bus(self, port: str) -> Any:
        if FeetechMotorsBus is None:
            raise RuntimeError(
                "LeRobot Feetech SDK is not installed. "
                "Install with `pip install 'lerobot[feetech]'` "
                "or `pip install 'lerobot[feetech]>=2.0.0'`."
            )
        motors = self._build_motor_list()
        kwargs: Dict[str, Any] = {"port": port, "motors": motors}
        try:
            signature = inspect.signature(FeetechMotorsBus)
            if "baudrate" in signature.parameters:
                kwargs["baudrate"] = self._baudrate
        except (TypeError, ValueError):
            kwargs["baudrate"] = self._baudrate
        return FeetechMotorsBus(**kwargs)

    async def _maybe_await(self, result: Any) -> Any:
        if inspect.isawaitable(result):
            return await result
        return result

    async def _bus_write(self, item: str, value: Any) -> None:
        if not self._motor_bus:
            raise RuntimeError("Motor bus not connected")
        write = getattr(self._motor_bus, "write", None)
        if write is None:
            raise RuntimeError("Motor bus does not support write()")
        try:
            await self._maybe_await(write(item, value))
            return
        except TypeError:
            pass
        motors = getattr(self._motor_bus, "motors", {})
        if not motors:
            raise
        if isinstance(value, list):
            if len(value) != len(self._joints):
                raise ValueError("Value list length does not match joints")
            for joint, joint_value in zip(self._joints, value):
                await self._maybe_await(write(item, joint.name, joint_value))
            return
        for joint in self._joints:
            await self._maybe_await(write(item, joint.name, value))

    async def _bus_read(self, item: str) -> Any:
        if not self._motor_bus:
            raise RuntimeError("Motor bus not connected")
        read = getattr(self._motor_bus, "read", None)
        if read is None:
            raise RuntimeError("Motor bus does not support read()")
        try:
            return await self._maybe_await(read(item))
        except TypeError:
            pass
        motors = getattr(self._motor_bus, "motors", {})
        if not motors:
            raise
        values = []
        for joint in self._joints:
            values.append(await self._maybe_await(read(item, joint.name)))
        return values

    async def connect(self, port: Optional[str] = None) -> None:
        """Connect to SO-101 arm via USB serial port.
        
        Args:
            port: Serial port path (e.g., /dev/ttyUSB0, /dev/ttyACM0)
                  Use lerobot-find-port to discover the correct port.
        """
        resolved_port = port or self._port or "/dev/ttyUSB0"
        logger.info("Connecting to SO-101 arm via %s", resolved_port)
        self._port = resolved_port
        self._motor_bus = self._build_motor_bus(resolved_port)
        connect = getattr(self._motor_bus, "connect", None)
        if connect is None:
            raise RuntimeError("Motor bus does not support connect()")
        await self._maybe_await(connect())
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
        calibration = getattr(self._motor_bus, "calibration", None)
        read_calibration = getattr(self._motor_bus, "read_calibration", None)
        if calibration == {} and callable(read_calibration):
            try:
                self._motor_bus.calibration = read_calibration()
            except Exception as exc:  # best-effort, fallback to raw reads
                logger.warning("Failed to read motor calibration: %s", exc)
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
        ik_angles, error, converged = solve_ik(
            (command.x, command.y, command.z),
            initial_angles_deg=self._last_joint_angles[:5],
        )
        if not converged:
            logger.warning("IK did not converge (error %.4f m)", error)
        if error > 0.01:
            raise ValueError(
                f"IK did not converge (error {error:.4f} m)"
            )
        gripper_angle = self._last_joint_angles[5]
        await self.move_joints(
            JointCommand(
                angles=ik_angles + [gripper_angle],
                speed=command.speed,
            )
        )
    
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
        
        speed = command.speed
        if speed > self._max_speed:
            logger.warning(
                "Requested speed %.2f exceeds max_speed %.2f; clamping",
                speed,
                self._max_speed,
            )
            speed = self._max_speed

        logger.info(
            "Moving SO-101 joints: [%.1f, %.1f, %.1f, %.1f, %.1f, %.1f] deg @ speed=%.2f",
            *command.angles,
            speed,
        )
        await self._bus_write("Torque_Enable", [1] * len(self._joints))
        await self._bus_write("Goal_Position", command.angles)
        self._last_joint_angles = list(command.angles)

    async def go_safe_pose(self, speed: float = 0.2) -> None:
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
                JointCommand(angles=pose["angles"], speed=speed)
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
        positions = await self._bus_read("Present_Position")
        logger.info("Reading SO-101 joint positions")
        self._last_joint_angles = list(positions)
        return list(positions)
    
    async def stop(self) -> None:
        """Emergency stop - halt all motors immediately."""
        logger.info("Stopping SO-101 arm")
        if not self._motor_bus:
            return
        try:
            await self._bus_write("Torque_Enable", [0] * len(self._joints))
        except RuntimeError:
            logger.warning("Motor bus torque disable failed")
    
    async def disconnect(self, stop: bool = True) -> None:
        """Safely disconnect from SO-101 motors."""
        if self._connected:
            if stop:
                await self.stop()
            disconnect = getattr(self._motor_bus, "disconnect", None)
            if disconnect:
                await self._maybe_await(disconnect())
            self._connected = False
            logger.info("Disconnected from SO-101")
