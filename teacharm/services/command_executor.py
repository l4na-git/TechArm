"""Command executor for TeachArm dialogue commands.

Handles execution of ARM_* commands returned by the dialogue system.
Implements:
- Command normalization (dict -> standard format)
- Serial execution (FIFO queue)
- Error handling (WARN mode - never fail)
- Latest-priority queue (newest pointer cancels pending)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Tuple
from enum import Enum

from ..logger import get_logger

logger = get_logger(__name__)


class CommandType(str, Enum):
    """Enumeration of valid ARM commands."""
    ARM_SAFE_POSE = "ARM_SAFE_POSE"
    ARM_INIT_POSE = "ARM_INIT_POSE"
    ARM_POINT_CENTER = "ARM_POINT_CENTER"
    ARM_POINT_REGION = "ARM_POINT_REGION"


class ErrorCode(str, Enum):
    """Error codes for command execution."""
    E_ARM = "E_ARM"  # Arm connection/execution failure
    E_ARM_CALIB = "E_ARM_CALIB"  # Calibration incomplete
    E_BAD_COMMAND = "E_BAD_COMMAND"  # Invalid command format


@dataclass
class Command:
    """Normalized command representation."""
    type: CommandType
    region_id: Optional[str] = None  # For ARM_POINT_REGION
    
    def __post_init__(self):
        if isinstance(self.type, str):
            self.type = CommandType(self.type)


@dataclass
class CommandError:
    """Command execution error details."""
    command: Command
    code: ErrorCode
    detail: Optional[str] = None


@dataclass
class CommandExecutorState:
    """State tracking for command executor."""
    queue: List[Command] = field(default_factory=list)
    current_command: Optional[Command] = None
    executing: bool = False
    executed_commands: List[Command] = field(default_factory=list)
    command_errors: List[CommandError] = field(default_factory=list)


class CommandExecutor:
    """Execute dialogue commands with error tolerance.
    
    Patterns:
    - FIFO queue with latest-priority (new pointer discards pending)
    - Commands execute serially (one at a time)
    - Errors are WARNed and execution continues (never fail)
    - Thread-safe for async contexts
    """

    def __init__(self, arm_service: Any, calibration: Any = None):
        """Initialize command executor.
        
        Args:
            arm_service: ArmService instance for ARM_* commands
            calibration: ArmCalibration instance for coordinate transforms
        """
        self.arm = arm_service
        self.calibration = calibration  # Optional, for coordinate transforms
        self._state = CommandExecutorState()
        self._lock = asyncio.Lock()

    async def execute_commands(
        self,
        commands_input: Union[Dict[str, Any], List[Dict[str, Any]], None],
    ) -> Tuple[List[Command], List[CommandError]]:
        """Execute commands from dialogue response.
        
        Args:
            commands_input: Commands dict/list from dialogue response,
                          or None if no commands.
        
        Returns:
            (executed_commands, command_errors) tuple
        """
        if not commands_input:
            return [], []
        
        # Normalize input to list of Command objects
        normalized = self._normalize_commands(commands_input)
        
        async with self._lock:
            # Clear pending queue (latest-priority)
            self._state.queue.clear()
            
            # Queue normalized commands
            for cmd in normalized:
                self._state.queue.append(cmd)
            
            # Process queue
            while self._state.queue:
                cmd = self._state.queue.pop(0)
                await self._execute_single(cmd)
        
        return self._state.executed_commands, self._state.command_errors

    def _normalize_commands(
        self,
        commands_input: Union[Dict[str, Any], List[Dict[str, Any]]],
    ) -> List[Command]:
        """Normalize commands to standard format.
        
        Input formats:
        - Dict: {"ARM_SAFE_POSE": true, "ARM_POINT_CENTER": true}
        - Dict: {"ARM_POINT_REGION": "region_id"}
        - List: [{type: "ARM_SAFE_POSE"}, ...]
        
        Args:
            commands_input: Raw commands from dialogue
        
        Returns:
            List of normalized Command objects
        """
        normalized = []
        
        # Handle dict format (from YAML scripts)
        if isinstance(commands_input, dict):
            for key, value in commands_input.items():
                try:
                    cmd_type = CommandType(key)
                    
                    # Handle region_id for ARM_POINT_REGION
                    if cmd_type == CommandType.ARM_POINT_REGION and isinstance(value, str):
                        normalized.append(Command(type=cmd_type, region_id=value))
                    elif value is True:
                        normalized.append(Command(type=cmd_type))
                    else:
                        logger.warning("Skipping %s with invalid value: %s", key, value)
                
                except ValueError:
                    logger.warning("Skipping unknown command key: %s", key)
            
            return normalized
        
        # Handle list format (already normalized)
        if isinstance(commands_input, list):
            for item in commands_input:
                if isinstance(item, dict) and "type" in item:
                    try:
                        cmd_type = CommandType(item["type"])
                        region_id = item.get("region_id")
                        normalized.append(Command(type=cmd_type, region_id=region_id))
                    except ValueError:
                        logger.warning("Skipping unknown command type: %s", item.get("type"))
                else:
                    logger.warning("Skipping malformed command item: %s", item)
            
            return normalized
        
        logger.warning("Unexpected commands format: %s", type(commands_input))
        return []

    async def _execute_single(self, cmd: Command) -> None:
        """Execute a single command.
        
        Args:
            cmd: Command to execute
        """
        logger.info("Executing command: %s", cmd.type.value)
        
        try:
            if cmd.type == CommandType.ARM_SAFE_POSE:
                await self.arm.go_safe_pose()
            
            elif cmd.type == CommandType.ARM_INIT_POSE:
                await self.arm.go_init_pose()
            
            elif cmd.type == CommandType.ARM_POINT_CENTER:
                await self._execute_point_center(cmd)
            
            elif cmd.type == CommandType.ARM_POINT_REGION:
                await self._execute_point_region(cmd)
            
            else:
                raise ValueError(f"Unknown command type: {cmd.type}")
            
            # Record successful execution
            self._state.executed_commands.append(cmd)
            logger.info("Command executed successfully: %s", cmd.type.value)
        
        except Exception as exc:
            # Determine error code
            error_code = ErrorCode.E_ARM
            if "calibration" in str(exc).lower():
                error_code = ErrorCode.E_ARM_CALIB
            
            error = CommandError(
                command=cmd,
                code=error_code,
                detail=str(exc),
            )
            self._state.command_errors.append(error)
            logger.warning(
                "Command execution failed [%s]: %s - %s",
                error_code.value,
                cmd.type.value,
                str(exc),
            )

    async def _execute_point_center(self, cmd: Command) -> None:
        """Execute ARM_POINT_CENTER: point to (u=0.5, v=0.5).
        
        Uses calibration to convert normalized coordinates to (x,y,z),
        then moves arm to that position.
        
        Args:
            cmd: ARM_POINT_CENTER command
        
        Raises:
            ValueError: If calibration incomplete or coordinate out of bounds
        """
        if not self.calibration:
            raise ValueError("ARM_POINT_CENTER: Calibration service not available")
        
        # Convert center coordinates (u=0.5, v=0.5) to arm coordinates
        try:
            x, y, z = self.calibration.uv_to_xyz(0.5, 0.5)
            logger.info("ARM_POINT_CENTER: Converted (0.5, 0.5) -> (%.1f, %.1f, %.1f) mm",
                       x, y, z)
        except ValueError as exc:
            raise ValueError(f"ARM_POINT_CENTER: Calibration transform failed - {exc}")
        
        # Move arm to the computed position
        from .arm import ArmCommand
        cmd_arm = ArmCommand(x=x, y=y, z=z, speed=0.2)
        await self.arm.move_to(cmd_arm)

    async def _execute_point_region(self, cmd: Command) -> None:
        """Execute ARM_POINT_REGION: point to region bbox center.
        
        Looks up region bbox center, converts to arm coordinates via
        calibration, and moves arm to that position.
        
        Args:
            cmd: ARM_POINT_REGION command with region_id
        
        Raises:
            ValueError: If region not found, calibration incomplete, or IK fails
        """
        if not cmd.region_id:
            raise ValueError("ARM_POINT_REGION: region_id required")
        
        if not self.calibration:
            raise ValueError("ARM_POINT_REGION: Calibration service not available")
        
        # TODO: Require region/material context in __init__ for region lookup
        # For now, raise not-implemented
        raise ValueError(
            f"ARM_POINT_REGION: Not yet implemented - requires material context (region_id={cmd.region_id})"
        )

    def reset(self) -> None:
        """Reset executor state (for testing/debugging)."""
        self._state = CommandExecutorState()

    def get_state(self) -> Dict[str, Any]:
        """Get current executor state for debugging."""
        return {
            "queue_size": len(self._state.queue),
            "executing": self._state.executing,
            "executed_count": len(self._state.executed_commands),
            "error_count": len(self._state.command_errors),
            "last_executed": (
                self._state.executed_commands[-1].type.value
                if self._state.executed_commands
                else None
            ),
            "last_error": (
                {
                    "command": self._state.command_errors[-1].command.type.value,
                    "code": self._state.command_errors[-1].code.value,
                }
                if self._state.command_errors
                else None
            ),
        }
