"""CLI helper to move SO-101 joints directly."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import numpy as np

try:
    from teacharm.config import load_settings
    from teacharm.kinematics import forward_kinematics, solve_ik
    from teacharm.materials import load_materials
    from teacharm.services.calibration import ArmCalibration
    from teacharm.services.marker_mapping import MarkerMapping
    from teacharm.services.arm import ArmService, ArmCommand, JointCommand
except ImportError:  # fallback when executed as a script
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from teacharm.config import load_settings
    from teacharm.kinematics import forward_kinematics, solve_ik
    from teacharm.materials import load_materials
    from teacharm.services.calibration import ArmCalibration
    from teacharm.services.marker_mapping import MarkerMapping
    from teacharm.services.arm import ArmService, ArmCommand, JointCommand


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move SO-101 joints")
    parser.add_argument(
        "--joints",
        nargs=6,
        type=float,
        metavar=("J1", "J2", "J3", "J4", "J5", "J6"),
        help="Target joint angles in degrees",
    )
    parser.add_argument(
        "--xyz",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help="Target end-effector position in meters",
    )
    parser.add_argument(
        "--xyz-relative",
        nargs=3,
        type=float,
        metavar=("DX", "DY", "DZ"),
        help="Target end-effector offset from current position in meters",
    )
    parser.add_argument(
        "--lock-wrist-roll",
        action="store_true",
        help="Keep wrist_roll angle fixed for xyz moves (may reduce reachability)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=0.2,
        help="Speed (0.0-1.0 normalized)",
    )
    parser.add_argument(
        "--safe-pose",
        action="store_true",
        help="Move to configured safe pose",
    )
    parser.add_argument(
        "--safe-init-safe",
        action="store_true",
        help="Move safe pose -> init pose -> safe pose in one run",
    )
    parser.add_argument(
        "--safe-init-forward-init-safe",
        action="store_true",
        help="Move safe -> init -> forward (robot +X) -> init -> safe",
    )
    parser.add_argument(
        "--forward-distance",
        type=float,
        default=0.05,
        help="Forward distance in meters for forward sequence (default: 0.05)",
    )
    parser.add_argument(
        "--forward-up",
        type=float,
        default=0.01,
        help="Upward distance in meters for forward sequence (default: 0.01)",
    )
    parser.add_argument(
        "--init-pose",
        action="store_true",
        help="Move to configured init pose",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1.5,
        help="Seconds to wait after movement before disconnecting",
    )
    parser.add_argument(
        "--hold",
        action="store_true",
        help="Keep torque enabled after exit (skip torque-off on disconnect)",
    )
    parser.add_argument(
        "--hold-forever",
        action="store_true",
        help="Keep torque enabled and keep process running until interrupted",
    )
    parser.add_argument(
        "--nudge-safe",
        action="store_true",
        help="Nudge shoulder_lift by a small angle, wait, then return to safe pose",
    )
    parser.add_argument(
        "--nudge-angle",
        type=float,
        default=20.0,
        help="Degrees to add to shoulder_lift for nudge (default: 20)",
    )
    parser.add_argument(
        "--nudge-speed",
        type=float,
        default=0.1,
        help="Speed for nudge movement (default: 0.1)",
    )
    parser.add_argument(
        "--nudge-wait",
        type=float,
        default=2.0,
        help="Seconds to wait between nudge and returning to safe pose",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read and print current joint angles",
    )
    parser.add_argument(
        "--current-xyz",
        action="store_true",
        help="Read current joint angles and print end-effector position (meters)",
    )
    parser.add_argument(
        "--point-paragraph",
        type=str,
        default=None,
        help="Point to a paragraph center: format MATERIAL_ID:NUM (e.g., A:1)",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=None,
        help="Override serial port",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=None,
        help="Override serial baudrate",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.hold_forever:
        args.hold = True
    settings = load_settings()
    arm_limits_path = settings.config_dir / "arm_limits.json"
    if not arm_limits_path.exists():
        raise FileNotFoundError(f"Missing config: {arm_limits_path}")
    arm_limits = json.loads(arm_limits_path.read_text(encoding="utf-8"))
    service = ArmService(
        arm_limits,
        port=args.port or settings.so101_port,
        baudrate=args.baudrate or settings.so101_baudrate,
        calibration_path=settings.so101_calibration_path,
    )

    try:
        if args.point_paragraph:
            try:
                material_id, paragraph_num = args.point_paragraph.split(":")
            except ValueError:
                raise ValueError("--point-paragraph must be MATERIAL_ID:NUM (e.g., A:1)")
            material_id = material_id.strip().upper()
            paragraph_num = paragraph_num.strip()
            region_id = f"paragraph{paragraph_num}"

            materials = load_materials(settings.materials_dir)
            material = materials.get(material_id)
            if not material:
                raise ValueError(f"Unknown material id: {material_id}")
            region = material.get_region(region_id)
            if not region:
                raise ValueError(f"Unknown region id: {region_id}")

            center = getattr(region, "center", None)
            if center:
                u, v = center.u, center.v
            else:
                u = region.bbox.x + (region.bbox.w / 2)
                v = region.bbox.y + (region.bbox.h / 2)

            marker_mapping = None
            marker_mapping_path = settings.arm_marker_mapping_path
            if marker_mapping_path is None:
                candidate = settings.config_dir / "arm_marker_mapping.json"
                if candidate.exists():
                    marker_mapping_path = candidate
            if marker_mapping_path:
                marker_mapping = MarkerMapping.from_file(marker_mapping_path)

            if marker_mapping and marker_mapping.is_complete():
                x, y, z = marker_mapping.uv_to_xyz(u, v)
            else:
                calibration_path = (
                    settings.arm_calibration_path
                    or settings.config_dir / "arm_calibration.json"
                )
                calibration = ArmCalibration.from_file(calibration_path)
                x, y, z = calibration.uv_to_xyz(u, v)

            scale = 1.0
            if max(abs(x), abs(y), abs(z)) > 10.0:
                scale = 1000.0  # treat as mm
            x = x + (0.05 * scale)
            z = 0.01 * scale

            await service.move_to(ArmCommand(x=float(x), y=float(y), z=float(z), speed=args.speed))
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.nudge_safe:
            positions = await service.get_joint_positions()
            target = list(positions)
            target[1] += args.nudge_angle
            await service.move_joints(
                JointCommand(angles=target, speed=args.nudge_speed)
            )
            if args.nudge_wait > 0:
                await asyncio.sleep(args.nudge_wait)
            await service.go_safe_pose()
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.safe_pose:
            await service.go_safe_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.safe_init_safe:
            await service.go_safe_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            await service.go_init_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            await service.go_safe_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.safe_init_forward_init_safe:
            await service.go_safe_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            positions = await service.get_joint_positions()
            transform, _, _ = forward_kinematics(
                np.deg2rad(np.array(positions[:5], dtype=float)).tolist(),
                return_chain=False,
            )
            current_xyz = transform[:3, 3]
            target = current_xyz + np.array(
                [args.forward_distance, 0.0, args.forward_up], dtype=float
            )
            await service.go_init_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)

            if args.lock_wrist_roll:
                ik_angles, _, _ = solve_ik(
                    (float(target[0]), float(target[1]), float(target[2])),
                    initial_angles_deg=positions[:5],
                )
                locked_angles = list(ik_angles)
                locked_angles[4] = positions[4]
                await service.move_joints(
                    JointCommand(
                        angles=locked_angles + [positions[5]],
                        speed=args.speed,
                    )
                )
            else:
                await service.move_to(
                    ArmCommand(
                        x=float(target[0]),
                        y=float(target[1]),
                        z=float(target[2]),
                        speed=args.speed,
                    )
                )

            if args.wait > 0:
                await asyncio.sleep(args.wait)
            await service.go_init_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            await service.go_safe_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.init_pose:
            await service.go_init_pose(speed=args.speed)
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.status:
            positions = await service.get_joint_positions()
            print(json.dumps({"joints": positions}, ensure_ascii=False))
            return 0
        positions = None
        if args.xyz_relative or args.lock_wrist_roll or args.current_xyz:
            positions = await service.get_joint_positions()
        if args.current_xyz:
            transform, _, _ = forward_kinematics(
                np.deg2rad(np.array(positions[:5], dtype=float)).tolist(),
                return_chain=False,
            )
            current_xyz = transform[:3, 3]
            print(json.dumps({"xyz": current_xyz.tolist()}, ensure_ascii=False))
            return 0
        if args.xyz_relative:
            transform, _, _ = forward_kinematics(
                np.deg2rad(np.array(positions[:5], dtype=float)).tolist(),
                return_chain=False,
            )
            current_xyz = transform[:3, 3]
            target = current_xyz + np.array(args.xyz_relative, dtype=float)
        elif args.xyz:
            target = np.array(args.xyz, dtype=float)

        if args.xyz_relative or args.xyz:
            if args.lock_wrist_roll:
                if positions is None:
                    positions = await service.get_joint_positions()
                ik_angles, error, converged = solve_ik(
                    (float(target[0]), float(target[1]), float(target[2])),
                    initial_angles_deg=positions[:5],
                )
                locked_angles = list(ik_angles)
                locked_angles[4] = positions[4]
                locked_transform, _, _ = forward_kinematics(
                    np.deg2rad(np.array(locked_angles, dtype=float)).tolist(),
                    return_chain=False,
                )
                locked_error = float(
                    np.linalg.norm(locked_transform[:3, 3] - target)
                )
                if locked_error > 0.01:
                    raise ValueError(
                        f"Locking wrist_roll prevents reaching target (error {locked_error:.4f} m)"
                    )
                await service.move_joints(
                    JointCommand(
                        angles=locked_angles + [positions[5]],
                        speed=args.speed,
                    )
                )
            else:
                await service.move_to(
                    ArmCommand(
                        x=float(target[0]),
                        y=float(target[1]),
                        z=float(target[2]),
                        speed=args.speed,
                    )
                )
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
        if args.joints:
            await service.move_joints(
                JointCommand(angles=list(args.joints), speed=args.speed)
            )
            if args.wait > 0:
                await asyncio.sleep(args.wait)
            if args.hold_forever:
                while True:
                    await asyncio.sleep(3600)
            return 0
    finally:
        await service.disconnect(stop=not args.hold)
    return 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not (
        args.xyz
        or args.xyz_relative
        or args.joints
        or args.safe_pose
        or args.safe_init_safe
        or args.safe_init_forward_init_safe
        or args.init_pose
        or args.status
        or args.current_xyz
        or args.point_paragraph
        or args.nudge_safe
    ):
        parser.error(
            "Specify --xyz, --xyz-relative, --joints, --safe-pose, --safe-init-safe, "
            "--safe-init-forward-init-safe, --init-pose, --status, --current-xyz, "
            "--point-paragraph, or --nudge-safe"
        )
    if args.xyz and args.xyz_relative:
        parser.error("Specify only one of --xyz or --xyz-relative")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
