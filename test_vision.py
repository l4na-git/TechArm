"""Test script for Vision service."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from teacharm.config import load_settings
from teacharm.services.vision import VisionService
from teacharm.logger import get_logger

logger = get_logger(__name__)


def test_vision_service() -> None:
    """Test VisionService initialization and basic operations."""
    print("\n=== VisionService Test ===\n")

    # Load settings
    print("[1] Loading settings...")
    settings = load_settings()
    print(f"✓ Settings loaded: {settings.config_dir}")

    # Initialize vision service
    print("\n[2] Initializing VisionService...")
    vision = VisionService(settings)
    print(f"✓ VisionService initialized")
    print(f"  - Camera device: {vision.config.device_index}")
    print(f"  - Resolution: {vision.config.width}x{vision.config.height}")
    print(f"  - ArUco dict: {vision.config.aruco_dict}")
    print(f"  - Marker IDs: {vision.config.marker_ids}")
    print(
        f"  - Hand detection: {vision.config.hand_detection_method}"
    )
    print(
        f"  - MediaPipe available: "
        f"{'Yes' if vision.hands_detector else 'No (using color-based)'}"
    )

    # Try to start camera (may fail if no camera available)
    print("\n[3] Starting camera...")
    success = vision.start()
    
    if not success:
        print("⚠ Camera not available (this is expected on headless systems)")
        print("  Vision service is ready for deployment on hardware")
        return

    print("✓ Camera started successfully")

    # Process multiple frames for better testing
    print("\n[4] Processing test frames (5 frames)...")
    for i in range(5):
        frame_result = vision.process_frame()
        
        if frame_result:
            print(f"\n  Frame {i+1}:")
            print(f"    - Timestamp: {frame_result.timestamp:.2f}")
            print(f"    - Markers: {frame_result.markers_detected}")
            print(f"    - Calibrated: {frame_result.is_calibrated}")
            print(f"    - Hand detected: {frame_result.hand_detected}")
            if frame_result.fingertip_u is not None:
                print(
                    f"    - Fingertip: "
                    f"({frame_result.fingertip_u:.3f}, "
                    f"{frame_result.fingertip_v:.3f})"
                )
        else:
            print(f"  Frame {i+1}: Failed to process")
        
        # Small delay between frames
        import time
        time.sleep(0.2)

    # Stop camera
    print("\n[5] Stopping camera...")
    vision.stop()
    print("✓ Camera stopped")

    print("\n=== Test Complete ===\n")


if __name__ == "__main__":
    try:
        test_vision_service()
    except Exception as e:
        logger.error("Test failed: %s", e, exc_info=True)
        sys.exit(1)
