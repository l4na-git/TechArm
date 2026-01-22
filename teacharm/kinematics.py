"""SO-101 kinematics helpers based on URDF parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import math

import numpy as np


@dataclass(frozen=True)
class JointSpec:
    name: str
    origin_xyz: Tuple[float, float, float]
    origin_rpy: Tuple[float, float, float]
    axis: Tuple[float, float, float]
    limit_lower: float
    limit_upper: float


JOINT_SPECS = [
    JointSpec(
        name="shoulder_pan",
        origin_xyz=(0.0388353, -8.97657e-09, 0.0624),
        origin_rpy=(3.14159, 4.18253e-17, -3.14159),
        axis=(0.0, 0.0, 1.0),
        limit_lower=-1.91986,
        limit_upper=1.91986,
    ),
    JointSpec(
        name="shoulder_lift",
        origin_xyz=(-0.0303992, -0.0182778, -0.0542),
        origin_rpy=(-1.5708, -1.5708, 0.0),
        axis=(0.0, 0.0, 1.0),
        limit_lower=-1.74533,
        limit_upper=1.74533,
    ),
    JointSpec(
        name="elbow_flex",
        origin_xyz=(-0.11257, -0.028, 1.73763e-16),
        origin_rpy=(-3.63608e-16, 8.74301e-16, 1.5708),
        axis=(0.0, 0.0, 1.0),
        limit_lower=-1.69,
        limit_upper=1.69,
    ),
    JointSpec(
        name="wrist_flex",
        origin_xyz=(-0.1349, 0.0052, 3.62355e-17),
        origin_rpy=(4.02456e-15, 8.67362e-16, -1.5708),
        axis=(0.0, 0.0, 1.0),
        limit_lower=-1.65806,
        limit_upper=1.65806,
    ),
    JointSpec(
        name="wrist_roll",
        origin_xyz=(5.55112e-17, -0.0611, 0.0181),
        origin_rpy=(1.5708, 0.0486795, 3.14159),
        axis=(0.0, 0.0, 1.0),
        limit_lower=-2.74385,
        limit_upper=2.84121,
    ),
]

TOOL_ORIGIN_XYZ = (-0.0079, -0.000218121, -0.0981274)
TOOL_ORIGIN_RPY = (0.0, 3.14159, 0.0)


def _rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr = math.cos(roll)
    sr = math.sin(roll)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    rot_x = np.array(
        [[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]], dtype=float
    )
    rot_y = np.array(
        [[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]], dtype=float
    )
    rot_z = np.array(
        [[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]], dtype=float
    )
    return rot_z @ rot_y @ rot_x


def _axis_angle_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c = math.cos(angle)
    s = math.sin(angle)
    C = 1.0 - c
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ],
        dtype=float,
    )


def _transform_from_origin(
    xyz: Tuple[float, float, float], rpy: Tuple[float, float, float]
) -> np.ndarray:
    transform = np.eye(4, dtype=float)
    transform[:3, :3] = _rpy_to_matrix(*rpy)
    transform[:3, 3] = np.array(xyz, dtype=float)
    return transform


def forward_kinematics(
    joint_angles_rad: List[float], return_chain: bool = False
) -> Tuple[np.ndarray, Optional[List[np.ndarray]], Optional[List[np.ndarray]]]:
    if len(joint_angles_rad) != len(JOINT_SPECS):
        raise ValueError("Expected 5 joint angles for SO-101 arm chain")

    transform = np.eye(4, dtype=float)
    joint_positions: List[np.ndarray] = []
    joint_axes: List[np.ndarray] = []

    for joint, angle in zip(JOINT_SPECS, joint_angles_rad):
        transform = transform @ _transform_from_origin(
            joint.origin_xyz, joint.origin_rpy
        )
        axis_world = transform[:3, :3] @ np.array(joint.axis, dtype=float)
        joint_positions.append(transform[:3, 3].copy())
        joint_axes.append(axis_world.copy())
        rot = np.eye(4, dtype=float)
        rot[:3, :3] = _axis_angle_matrix(
            np.array(joint.axis, dtype=float), angle
        )
        transform = transform @ rot

    transform = transform @ _transform_from_origin(
        TOOL_ORIGIN_XYZ, TOOL_ORIGIN_RPY
    )

    if return_chain:
        return transform, joint_positions, joint_axes
    return transform, None, None


def solve_ik(
    target_xyz: Tuple[float, float, float],
    initial_angles_deg: Optional[List[float]] = None,
    max_iters: int = 120,
    tol: float = 1e-3,
) -> Tuple[List[float], float, bool]:
    if initial_angles_deg is None:
        angles = np.zeros(len(JOINT_SPECS), dtype=float)
    else:
        if len(initial_angles_deg) != len(JOINT_SPECS):
            raise ValueError("Expected 5 joint angles for IK initial seed")
        angles = np.deg2rad(np.array(initial_angles_deg, dtype=float))

    target = np.array(target_xyz, dtype=float)

    for _ in range(max_iters):
        transform, joint_positions, joint_axes = forward_kinematics(
            angles.tolist(), return_chain=True
        )
        end_effector = transform[:3, 3]
        error = np.linalg.norm(end_effector - target)
        if error <= tol:
            return np.rad2deg(angles).tolist(), error, True

        for joint_index in reversed(range(len(JOINT_SPECS))):
            transform, joint_positions, joint_axes = forward_kinematics(
                angles.tolist(), return_chain=True
            )
            end_effector = transform[:3, 3]
            joint_pos = joint_positions[joint_index]
            axis = joint_axes[joint_index]
            axis_norm = np.linalg.norm(axis)
            if axis_norm == 0.0:
                continue
            axis = axis / axis_norm

            to_end = end_effector - joint_pos
            to_target = target - joint_pos
            end_norm = np.linalg.norm(to_end)
            target_norm = np.linalg.norm(to_target)
            if end_norm == 0.0 or target_norm == 0.0:
                continue
            to_end /= end_norm
            to_target /= target_norm

            end_proj = to_end - axis * np.dot(axis, to_end)
            target_proj = to_target - axis * np.dot(axis, to_target)
            end_proj_norm = np.linalg.norm(end_proj)
            target_proj_norm = np.linalg.norm(target_proj)
            if end_proj_norm == 0.0 or target_proj_norm == 0.0:
                continue
            end_proj /= end_proj_norm
            target_proj /= target_proj_norm

            cross = np.cross(end_proj, target_proj)
            dot = np.clip(np.dot(end_proj, target_proj), -1.0, 1.0)
            angle = math.atan2(np.linalg.norm(cross), dot)
            if np.dot(axis, cross) < 0.0:
                angle = -angle

            angles[joint_index] += angle
            joint = JOINT_SPECS[joint_index]
            angles[joint_index] = np.clip(
                angles[joint_index], joint.limit_lower, joint.limit_upper
            )

    transform, _, _ = forward_kinematics(angles.tolist(), return_chain=False)
    end_effector = transform[:3, 3]
    error = np.linalg.norm(end_effector - target)
    return np.rad2deg(angles).tolist(), error, False
