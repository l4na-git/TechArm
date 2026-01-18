"""Generate ArUco markers for TeachArm vision calibration."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def generate_markers(
    output_dir: Path,
    marker_size: int = 200,
    dictionary: str = "DICT_4X4_50",
) -> None:
    """
    Generate ArUco markers for the 4 corners.
    
    Args:
        output_dir: Directory to save marker images
        marker_size: Size of marker in pixels
        dictionary: ArUco dictionary name
    """
    # Get ArUco dictionary
    aruco_dict = cv2.aruco.getPredefinedDictionary(
        getattr(cv2.aruco, dictionary)
    )
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate markers for IDs 0-3
    marker_ids = [0, 1, 2, 3]
    positions = ["top-left", "top-right", "bottom-right", "bottom-left"]
    
    print(f"\nGenerating ArUco markers ({dictionary})...\n")
    
    for marker_id, position in zip(marker_ids, positions):
        # Generate marker image
        marker_image = cv2.aruco.generateImageMarker(
            aruco_dict, marker_id, marker_size
        )
        
        # Save image
        filename = f"aruco_marker_{marker_id}_{position}.png"
        output_path = output_dir / filename
        cv2.imwrite(str(output_path), marker_image)
        
        print(f"✓ Generated marker {marker_id} ({position}): {filename}")
    
    print(f"\n📁 Markers saved to: {output_dir.absolute()}")
    print("\nUsage:")
    print("  1. Print all 4 markers on white paper")
    print("  2. Arrange them at the corners of your material:")
    print()
    print("     ID 0 (top-left)      ID 1 (top-right)")
    print("         ┌──────────────────┐")
    print("         │                  │")
    print("         │   Material Area  │")
    print("         │                  │")
    print("         └──────────────────┘")
    print("     ID 3 (bottom-left)   ID 2 (bottom-right)")
    print()


def main() -> int:
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Generate ArUco markers for TeachArm"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("aruco_markers"),
        help="Output directory (default: aruco_markers)",
    )
    parser.add_argument(
        "--size",
        "-s",
        type=int,
        default=200,
        help="Marker size in pixels (default: 200)",
    )
    parser.add_argument(
        "--dict",
        "-d",
        type=str,
        default="DICT_4X4_50",
        help="ArUco dictionary (default: DICT_4X4_50)",
    )
    
    args = parser.parse_args()
    
    try:
        generate_markers(args.output, args.size, args.dict)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
