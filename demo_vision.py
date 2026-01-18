"""Interactive vision demo with live preview."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from teacharm.config import load_settings
from teacharm.services.vision import VisionService
from teacharm.logger import get_logger

logger = get_logger(__name__)


def run_demo() -> None:
    """Run interactive vision demo with live preview."""
    print("\n=== TeachArm Vision Interactive Demo ===\n")
    print("Controls:")
    print("  - Press 'q' to quit")
    print("  - Press 'c' to force calibration (immediate)")
    print("  - Press 'r' to reset calibration")
    print("  - Press 'a' to toggle auto-calibration")
    print("  - Press 's' to take screenshot")
    print()

    # Load settings
    settings = load_settings()
    vision = VisionService(settings)

    # Start camera
    print("Starting camera...")
    if not vision.start():
        print("❌ Failed to start camera")
        print("\nTroubleshooting:")
        print("  1. Check camera permissions (macOS: System Preferences)")
        print("  2. Make sure no other app is using the camera")
        print("  3. Try changing device.index in config/camera.yaml")
        return

    print("✓ Camera started")
    print(
        f"  Resolution: {vision.config.width}x{vision.config.height}"
    )
    print(
        f"  Hand detection: {vision.config.hand_detection_method}"
    )
    print(
        f"  MediaPipe: "
        f"{'Enabled' if vision.hands_detector else 'Disabled'}"
    )
    print("\nPress any key in the preview window to start...\n")

    # Create window
    window_name = "TeachArm Vision Demo"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    frame_count = 0
    screenshot_count = 0

    try:
        while True:
            # Capture and process frame
            frame = vision.capture_frame()
            if frame is None:
                print("Failed to capture frame")
                break

            # Detect ArUco markers
            marker_ids, marker_corners = vision.detect_aruco_markers(frame)

            # Draw markers (convert to proper format for OpenCV)
            if marker_ids:
                try:
                    import numpy as np
                    # Convert marker_corners dict to properly shaped list
                    # Each element should be a 4x2 numpy array
                    corners_list = []
                    for mid in marker_ids:
                        corners = marker_corners[mid]
                        # Ensure corners is a numpy array with shape (4, 2)
                        if not isinstance(corners, np.ndarray):
                            corners = np.array(corners)
                        if corners.shape != (4, 2):
                            corners = corners.reshape(4, 2)
                        # drawDetectedMarkers expects shape (1, 4, 2)
                        corners_list.append(corners.reshape(1, 4, 2))
                    
                    ids_array = np.array(marker_ids, dtype=np.int32).reshape(-1, 1)
                    cv2.aruco.drawDetectedMarkers(frame, corners_list, ids_array)
                    
                    # Draw marker centers and IDs for debugging
                    for mid in marker_ids:
                        corners = marker_corners[mid]
                        if not isinstance(corners, np.ndarray):
                            corners = np.array(corners)
                        center = corners.mean(axis=0)
                        cx, cy = int(center[0]), int(center[1])
                        
                        # Draw center point
                        cv2.circle(frame, (cx, cy), 5, (0, 255, 255), -1)
                        
                        # Draw ID label
                        cv2.putText(
                            frame,
                            f"ID:{mid}",
                            (cx + 10, cy - 10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 255, 255),
                            2,
                        )
                    
                    # If we have 4 markers, draw the quadrilateral they form
                    if len(marker_ids) == 4 and set(marker_ids) == {0, 1, 2, 3}:
                        centers = []
                        for mid in [0, 1, 2, 3]:  # Ordered
                            corners = marker_corners[mid]
                            if not isinstance(corners, np.ndarray):
                                corners = np.array(corners)
                            center = corners.mean(axis=0)
                            centers.append(center.astype(np.int32))
                        
                        # Draw quadrilateral
                        pts = np.array(centers, np.int32).reshape((-1, 1, 2))
                        cv2.polylines(frame, [pts], True, (255, 0, 255), 2)
                        
                except Exception as e:
                    # Don't crash on marker drawing errors
                    logger.warning("Failed to draw markers: %s", e)

            # Apply perspective transform if calibrated
            display_frame = frame.copy()
            if vision.perspective_matrix is not None:
                warped = vision.warp_frame(frame)
                if warped is not None:
                    display_frame = warped

            # Detect hand (with error handling)
            fingertip_px = None
            try:
                fingertip_px = vision.detect_hand(display_frame)
            except Exception as e:
                logger.warning("Hand detection failed: %s", e)
            
            smoothed = vision.smooth_fingertip(fingertip_px)

            # Draw hand detection
            if smoothed is not None:
                x, y = int(smoothed[0]), int(smoothed[1])
                # Draw fingertip
                cv2.circle(display_frame, (x, y), 15, (0, 255, 0), -1)
                cv2.circle(display_frame, (x, y), 20, (255, 255, 255), 2)

                # Draw crosshair
                cv2.line(
                    display_frame,
                    (x - 30, y),
                    (x + 30, y),
                    (0, 255, 0),
                    2,
                )
                cv2.line(
                    display_frame,
                    (x, y - 30),
                    (x, y + 30),
                    (0, 255, 0),
                    2,
                )

                # Show normalized coordinates
                u, v = vision.pixel_to_normalized(x, y)
                coord_text = f"({u:.3f}, {v:.3f})"
                cv2.putText(
                    display_frame,
                    coord_text,
                    (x + 25, y - 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

            # Draw status info
            status_y = 30
            line_height = 30

            # Calibration status
            calib_status = (
                "CALIBRATED"
                if vision.perspective_matrix is not None
                else "NOT CALIBRATED"
            )
            calib_color = (0, 255, 0) if vision.perspective_matrix is not None else (0, 0, 255)
            cv2.putText(
                display_frame,
                f"Status: {calib_status}",
                (10, status_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                calib_color,
                2,
            )
            status_y += line_height

            # Markers detected
            cv2.putText(
                display_frame,
                f"Markers: {marker_ids if marker_ids else 'None'}",
                (10, status_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            status_y += line_height

            # Hand detected
            hand_text = "Hand: Detected" if smoothed else "Hand: Not detected"
            hand_color = (0, 255, 0) if smoothed else (0, 165, 255)
            cv2.putText(
                display_frame,
                hand_text,
                (10, status_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                hand_color,
                2,
            )
            status_y += line_height

            # Detection method
            cv2.putText(
                display_frame,
                f"Method: {vision.config.hand_detection_method}",
                (10, status_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (200, 200, 200),
                1,
            )
            status_y += line_height
            
            # Frame count
            cv2.putText(
                display_frame,
                f"Frame: {frame_count}",
                (10, status_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (200, 200, 200),
                1,
            )

            # Instructions and tips at bottom
            h, w = display_frame.shape[:2]
            
            # Main instructions
            cv2.putText(
                display_frame,
                "q:quit | c:calibrate | r:reset | a:auto | s:screenshot",
                (10, h - 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            
            # Tips based on current state
            if vision.perspective_matrix is None:
                auto_status = "ON" if vision.auto_calibrate_enabled else "OFF"
                if len(marker_ids) >= 4:
                    frames_left = max(0, 10 - vision.calibration_frame_count)
                    tip = f"Auto-calibration {auto_status}: {frames_left} frames... (or press 'c' now)"
                else:
                    tip = f"Auto-calibration {auto_status}: Place 4 markers (ID 0-3) at corners"
                tip_color = (0, 165, 255)  # Orange
            elif not smoothed:
                tip = "TIP: Point your index finger at the camera for hand detection"
                tip_color = (0, 255, 255)  # Yellow
            else:
                tip = "All systems operational! Move your finger around."
                tip_color = (0, 255, 0)  # Green
            
            cv2.putText(
                display_frame,
                tip,
                (10, h - 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                tip_color,
                1,
            )

            # Show frame
            cv2.imshow(window_name, display_frame)

            # Handle keyboard
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                print("\nQuitting...")
                break
            elif key == ord("c"):
                print("\n🎯 Triggering manual calibration...")
                if len(marker_ids) >= 4:
                    # Show marker positions for debugging
                    print("Marker positions:")
                    for mid in sorted(marker_ids):
                        if mid in marker_corners:
                            import numpy as np
                            corners = marker_corners[mid]
                            if not isinstance(corners, np.ndarray):
                                corners = np.array(corners)
                            center = corners.mean(axis=0)
                            print(f"  ID {mid}: ({center[0]:.1f}, {center[1]:.1f})")
                    
                    success = vision.calibrate_perspective(
                        marker_corners, force=True
                    )
                    if success:
                        print("✓ Calibration successful!")
                    else:
                        print("❌ Calibration failed")
                        print("\nTroubleshooting:")
                        print("  1. Ensure markers form a proper quadrilateral (not a line)")
                        print("  2. Spread markers to cover at least 10% of the frame")
                        print("  3. Check that markers are on a flat surface")
                        print("  4. Try auto-calibration (10-frame average) instead")
                        print("  5. Use 'r' to reset, then wait for auto-calibration")
                else:
                    print(
                        f"❌ Need 4 markers, found {len(marker_ids)}: {marker_ids}"
                    )
            elif key == ord("r"):
                print("\n🔄 Resetting calibration...")
                vision.reset_calibration()
                print("✓ Calibration reset - reposition markers for auto-calibration")
            elif key == ord("a"):
                vision.auto_calibrate_enabled = not vision.auto_calibrate_enabled
                status = "enabled" if vision.auto_calibrate_enabled else "disabled"
                print(f"\n⚙️  Auto-calibration {status}")
            elif key == ord("s"):
                screenshot_path = f"screenshot_{screenshot_count:03d}.png"
                cv2.imwrite(screenshot_path, display_frame)
                screenshot_count += 1
                print(f"📸 Screenshot saved: {screenshot_path}")

            frame_count += 1

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        vision.stop()
        cv2.destroyAllWindows()
        print(f"\nProcessed {frame_count} frames")
        print("Demo ended.\n")


if __name__ == "__main__":
    try:
        run_demo()
    except Exception as e:
        logger.error("Demo failed: %s", e, exc_info=True)
        print(f"\n❌ Error: {e}")
        sys.exit(1)
