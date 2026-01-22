"""Compute SO-101 forward kinematics from joint angles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    from teacharm.kinematics import forward_kinematics
except ImportError:  # fallback when executed as a script
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from teacharm.kinematics import forward_kinematics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SO-101 FK helper")
    parser.add_argument(
        "--joints",
        nargs=5,
        type=float,
        metavar=("J1", "J2", "J3", "J4", "J5"),
        required=True,
        help="Joint angles in degrees (shoulder_pan..wrist_roll)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    angles_rad = np.deg2rad(args.joints).tolist()
    transform, _, _ = forward_kinematics(angles_rad, return_chain=False)
    position = transform[:3, 3].tolist()
    if args.json:
        print(json.dumps({"position": position}, ensure_ascii=False))
        return
    print(
        f"x={position[0]:.4f} m, y={position[1]:.4f} m, z={position[2]:.4f} m"
    )


if __name__ == "__main__":
    main()
