"""Vision service for camera input, ArUco detection, and transforms."""

from __future__ import annotations

import platform
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import yaml
from pydantic import BaseModel

from ..config import Settings
from ..logger import get_logger

logger = get_logger(__name__)

# Optional MediaPipe import (gracefully handle if not available)
try:
    import mediapipe as mp

    if not hasattr(mp, "solutions"):
        raise ImportError("MediaPipe solutions API not available")
    MEDIAPIPE_AVAILABLE = True
except ImportError as exc:
    MEDIAPIPE_AVAILABLE = False
    logger.warning(
        "MediaPipe not available (%s), falling back to color-based detection",
        exc,
    )


class VisionFrame(BaseModel):
    """Vision processing result for a single frame."""

    timestamp: float
    markers_detected: List[int]
    markers_corners: Dict[int, List[List[float]]]
    is_calibrated: bool
    hand_detected: bool
    fingertip_u: Optional[float] = None
    fingertip_v: Optional[float] = None
    # Material mapping fields (populated by server)
    current_region_id: Optional[str] = None
    current_material_id: Optional[str] = None
    error_code: Optional[str] = None


class CameraConfig(BaseModel):
    """Camera configuration loaded from YAML."""

    device_index: int = 0
    device_path: Optional[str] = None
    width: int = 1280
    height: int = 720
    fps: int = 30
    autofocus: int = 0
    auto_exposure: int = 1
    exposure: int = 100
    auto_white_balance: int = 1
    aruco_dict: str = "DICT_4X4_50"
    marker_ids: List[int] = [0, 1, 2, 3]
    marker_size: float = 0.05
    auto_order_by_position: bool = True
    hand_detection_method: str = "mediapipe"  # mediapipe or color
    mediapipe_confidence: float = 0.5
    mediapipe_model_complexity: int = 0  # 0 or 1
    hand_detection_interval: int = 8  # Run hand detection every N frames
    hand_detection_scale: float = 0.25  # Downscale factor for hand detection
    smoothing_window: int = 5
    max_jump_threshold: int = 40
    debug_show_preview: bool = False


class VisionService:
    """
    Vision service for TeachArm.
    
    Handles camera input, ArUco marker detection, perspective transformation,
    and hand/fingertip detection.
    """

    def __init__(self, settings: Settings):
        """Initialize vision service with settings."""
        self.settings = settings
        self.config = self._load_config()
        self.cap: Optional[cv2.VideoCapture] = None
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(
            getattr(cv2.aruco, self.config.aruco_dict)
        )
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.perspective_matrix: Optional[np.ndarray] = None
        self.fingertip_buffer: deque = deque(
            maxlen=self.config.smoothing_window
        )
        self.last_fingertip: Optional[Tuple[float, float]] = None
        self._running = False
        self._hand_detection_counter = 0
        self._last_hand_px: Optional[Tuple[int, int]] = None
        
        # Calibration stability tracking
        self.calibration_buffer: deque = deque(maxlen=10)
        self.calibration_frame_count = 0
        self.auto_calibrate_enabled = True
        
        # Store last processed frame for preview
        self.last_frame: Optional[np.ndarray] = None
        self.last_display_frame: Optional[np.ndarray] = None
        
        # Initialize MediaPipe Hands if available
        self.mp_hands = None
        self.hands_detector = None
        if (
            MEDIAPIPE_AVAILABLE
            and self.config.hand_detection_method == "mediapipe"
        ):
            self.mp_hands = mp.solutions.hands
            # Lower tracking confidence significantly for better re-detection
            # This allows MediaPipe to re-detect quickly after losing track
            tracking_confidence = max(0.3, self.config.mediapipe_confidence - 0.3)
            self.hands_detector = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                model_complexity=self.config.mediapipe_model_complexity,
                min_detection_confidence=self.config.mediapipe_confidence,
                min_tracking_confidence=tracking_confidence,
            )
            logger.info(
                "MediaPipe Hands initialized (detection=%.2f, tracking=%.2f)",
                self.config.mediapipe_confidence,
                tracking_confidence,
            )
        else:
            logger.info(
                "Using color-based hand detection (MediaPipe not available)"
            )

    def _load_config(self) -> CameraConfig:
        """Load camera configuration from YAML file."""
        config_path = self.settings.config_dir / "camera.yaml"
        if not config_path.exists():
            logger.warning(
                "Camera config not found at %s, using defaults", config_path
            )
            return CameraConfig()

        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            # Flatten nested structure
            device_cfg = data.get("device", {})
            resolution_cfg = data.get("resolution", {})
            params_cfg = data.get("parameters", {})
            aruco_cfg = data.get("aruco", {})
            hand_cfg = data.get("hand_detection", {})
            debug_cfg = data.get("debug", {})

            return CameraConfig(
                device_index=device_cfg.get("index", 0),
                device_path=device_cfg.get("path"),
                width=resolution_cfg.get("width", 1280),
                height=resolution_cfg.get("height", 720),
                fps=params_cfg.get("fps", 30),
                autofocus=params_cfg.get("autofocus", 0),
                auto_exposure=params_cfg.get("auto_exposure", 1),
                exposure=params_cfg.get("exposure", 100),
                auto_white_balance=params_cfg.get("auto_white_balance", 1),
                aruco_dict=aruco_cfg.get("dictionary", "DICT_4X4_50"),
                marker_ids=aruco_cfg.get("marker_ids", [0, 1, 2, 3]),
                marker_size=aruco_cfg.get("marker_size", 0.05),
                auto_order_by_position=aruco_cfg.get(
                    "auto_order_by_position", True
                ),
                hand_detection_method=hand_cfg.get("method", "mediapipe"),
                mediapipe_confidence=hand_cfg.get(
                    "confidence_threshold", 0.5
                ),
                mediapipe_model_complexity=hand_cfg.get(
                    "model_complexity", 0
                ),
                hand_detection_interval=hand_cfg.get(
                    "interval", 8
                ),
                hand_detection_scale=hand_cfg.get(
                    "scale", 0.25
                ),
                smoothing_window=hand_cfg.get("smoothing_window", 5),
                max_jump_threshold=hand_cfg.get("max_jump_threshold", 40),
                debug_show_preview=debug_cfg.get("show_preview", False),
            )
        except Exception as e:
            logger.error("Failed to load camera config: %s", e)
            return CameraConfig()

    def start(self) -> bool:
        """Start camera capture."""
        if self.cap is not None:
            logger.warning("Camera already started")
            return True

        try:
            # Determine camera device based on platform
            device = self._get_camera_device()
            self.cap = cv2.VideoCapture(device)

            if not self.cap.isOpened():
                logger.error("Failed to open camera device: %s", device)
                return False

            # Set camera parameters (platform-specific handling)
            self._set_camera_parameters()

            self._running = True
            logger.info(
                "Camera started: %dx%d @ %dfps (device: %s, OS: %s)",
                self.config.width,
                self.config.height,
                self.config.fps,
                device,
                platform.system(),
            )
            return True

        except Exception as e:
            logger.error("Failed to start camera: %s", e)
            return False

    def _get_camera_device(self) -> int | str:
        """Get camera device based on configuration and platform."""
        if self.config.device_path:
            return self.config.device_path
        
        # On macOS, default camera is usually 0
        # On Linux (Raspberry Pi), might be /dev/video0
        if platform.system() == "Linux" and self.config.device_index == 0:
            # Try /dev/video0 first on Linux
            import os
            if os.path.exists("/dev/video0"):
                return "/dev/video0"
        
        return self.config.device_index

    def _set_camera_parameters(self) -> None:
        """Set camera parameters with platform-specific handling."""
        if self.cap is None:
            return
        
        # Resolution is usually safe across platforms
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.config.fps)
        
        # These settings may not work on all platforms
        try:
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, self.config.autofocus)
            self.cap.set(
                cv2.CAP_PROP_AUTO_EXPOSURE, self.config.auto_exposure
            )
            if self.config.auto_exposure == 1:
                self.cap.set(cv2.CAP_PROP_EXPOSURE, self.config.exposure)
            self.cap.set(
                cv2.CAP_PROP_AUTO_WB, self.config.auto_white_balance
            )
        except Exception as e:
            logger.warning(
                "Some camera parameters not supported on this platform: %s",
                e,
            )
        self._refresh_camera_properties()

    def _refresh_camera_properties(self) -> None:
        """Sync config with actual camera properties."""
        if self.cap is None:
            return
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (
            actual_width > 0
            and actual_height > 0
            and (actual_width != self.config.width
                 or actual_height != self.config.height)
        ):
            logger.warning(
                "Camera resolution differs from config (%dx%d -> %dx%d), updating",
                self.config.width,
                self.config.height,
                actual_width,
                actual_height,
            )
            self.config.width = actual_width
            self.config.height = actual_height
            self.reset_calibration()

    def stop(self) -> None:
        """Stop camera capture and cleanup resources."""
        self._running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.hands_detector is not None:
            self.hands_detector.close()
        logger.info("Camera stopped")

    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture a single frame from camera."""
        if self.cap is None or not self._running:
            return None

        ret, frame = self.cap.read()
        if not ret:
            logger.warning("Failed to capture frame")
            return None

        return frame

    def detect_aruco_markers(
        self, frame: np.ndarray
    ) -> Tuple[List[int], Dict[int, np.ndarray]]:
        """
        Detect ArUco markers in frame.
        
        Returns:
            Tuple of (marker_ids, marker_corners_dict)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = cv2.aruco.detectMarkers(
            gray, self.aruco_dict, parameters=self.aruco_params
        )

        if ids is None:
            return [], {}

        marker_ids = ids.flatten().tolist()
        marker_corners = {}
        for i, marker_id in enumerate(marker_ids):
            # Convert corner coordinates to list format
            corner_array = corners[i][0]
            marker_corners[marker_id] = corner_array

        return marker_ids, marker_corners

    def _validate_marker_layout(
        self, centers: List[np.ndarray]
    ) -> Tuple[bool, str]:
        """
        Validate that markers form a reasonable quadrilateral.
        
        Returns (is_valid, error_message)
        """
        # Check if markers form a convex quadrilateral
        # Calculate cross products to check convexity
        def cross_product_sign(p1, p2, p3):
            return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
        
        signs = []
        for i in range(4):
            p1 = centers[i]
            p2 = centers[(i + 1) % 4]
            p3 = centers[(i + 2) % 4]
            signs.append(cross_product_sign(p1, p2, p3))
        
        # All cross products should have the same sign for convex quadrilateral
        if not (all(s > 0 for s in signs) or all(s < 0 for s in signs)):
            return False, "Markers don't form a convex quadrilateral (check placement)"
        
        # Check minimum area using Shoelace formula
        def polygon_area(points):
            n = len(points)
            area = 0.0
            for i in range(n):
                j = (i + 1) % n
                area += points[i][0] * points[j][1]
                area -= points[j][0] * points[i][1]
            return abs(area) / 2.0
        
        area = polygon_area(centers)
        frame_area = self.config.width * self.config.height
        area_ratio = area / frame_area
        
        if area_ratio < 0.1:
            return False, f"Marker area too small ({area_ratio*100:.1f}% of frame, need >10%)"
        
        # Check aspect ratio (should be roughly rectangular)
        p0, p1, p2, p3 = centers
        width1 = np.linalg.norm(np.array(p1) - np.array(p0))
        width2 = np.linalg.norm(np.array(p2) - np.array(p3))
        height1 = np.linalg.norm(np.array(p3) - np.array(p0))
        height2 = np.linalg.norm(np.array(p2) - np.array(p1))
        
        avg_width = (width1 + width2) / 2
        avg_height = (height1 + height2) / 2
        
        if avg_width < 50 or avg_height < 50:
            return False, "Markers too close together (spread them out)"
        
        aspect_ratio = max(avg_width, avg_height) / min(avg_width, avg_height)
        if aspect_ratio > 4.0:
            return False, f"Aspect ratio too extreme ({aspect_ratio:.1f}:1, max 4:1)"
        
        return True, "OK"

    def _order_markers(
        self, marker_corners: Dict[int, np.ndarray], required_ids: List[int]
    ) -> Optional[List[Tuple[int, np.ndarray, np.ndarray]]]:
        if not all(mid in marker_corners for mid in required_ids):
            return None
        entries: List[Tuple[int, np.ndarray, np.ndarray]] = []
        for marker_id in required_ids:
            corners = marker_corners[marker_id]
            center = np.mean(corners, axis=0)
            entries.append((marker_id, corners, center))
        if not self.config.auto_order_by_position:
            return entries
        sums = [entry[2][0] + entry[2][1] for entry in entries]
        diffs = [entry[2][0] - entry[2][1] for entry in entries]
        tl = entries[int(np.argmin(sums))]
        br = entries[int(np.argmax(sums))]
        tr = entries[int(np.argmax(diffs))]
        bl = entries[int(np.argmin(diffs))]
        ordered = [tl, tr, br, bl]
        if len({id(entry) for entry in ordered}) < 4:
            entries_sorted = sorted(
                entries, key=lambda item: (item[2][1], item[2][0])
            )
            top = sorted(entries_sorted[:2], key=lambda item: item[2][0])
            bottom = sorted(entries_sorted[2:], key=lambda item: item[2][0])
            tl, tr = top
            bl, br = bottom
            ordered = [tl, tr, br, bl]
        return ordered

    @staticmethod
    def _inner_corner(corners: np.ndarray, target: np.ndarray) -> np.ndarray:
        distances = [np.linalg.norm(c - target) for c in corners]
        return corners[int(np.argmin(distances))]

    def calibrate_perspective(
        self, marker_corners: Dict[int, np.ndarray], force: bool = False
    ) -> bool:
        """
        Calculate perspective transformation matrix from 4 ArUco markers.
        
        Uses multi-frame averaging for stability unless force=True.
        
        Expected marker layout (normalized coordinates):
        ID 0: top-left (0, 0)
        ID 1: top-right (1, 0)
        ID 2: bottom-right (1, 1)
        ID 3: bottom-left (0, 1)
        
        Args:
            marker_corners: Dictionary of detected marker corners
            force: If True, calibrate immediately without averaging
        """
        required_ids = self.config.marker_ids[:4]
        ordered = self._order_markers(marker_corners, required_ids)
        if not ordered:
            logger.warning(
                "Missing markers for calibration. Found: %s, Required: %s",
                list(marker_corners.keys()),
                required_ids,
            )
            return False

        centers = [entry[2] for entry in ordered]
        # Validate marker layout
        is_valid, error_msg = self._validate_marker_layout(centers)
        if not is_valid:
            logger.warning("Invalid marker layout: %s", error_msg)
            return False

        try:
            src_points = []
            quad_center = np.mean(centers, axis=0)
            for marker_id, corners, center in ordered:
                # Debug: Log all corners for this marker
                logger.debug(f"Marker ID {marker_id} corners:")
                for ci, corner in enumerate(corners):
                    logger.debug(f"  Corner {ci}: ({corner[0]:.1f}, {corner[1]:.1f})")

                inner_corner = self._inner_corner(corners, quad_center)
                src_points.append(inner_corner)
                logger.debug(
                    "  Using inner corner: (%.1f, %.1f)",
                    inner_corner[0],
                    inner_corner[1],
                )

            src_points = np.array(src_points, dtype=np.float32)
            
            # Debug: Log marker corner positions
            logger.debug("Calibration corner positions:")
            ordered_ids = [entry[0] for entry in ordered]
            for i, (mid, pos) in enumerate(zip(ordered_ids, src_points)):
                logger.debug(f"  ID {mid}: ({pos[0]:.1f}, {pos[1]:.1f})")

            # Add to calibration buffer for stability
            self.calibration_buffer.append(src_points)
            
            # Use averaged points if we have enough samples and not forcing
            if len(self.calibration_buffer) >= 5 and not force:
                # Average the last 5 calibration samples
                avg_points = np.mean(list(self.calibration_buffer), axis=0)
                src_points = avg_points.astype(np.float32)
                logger.info(
                    "Using averaged calibration from %d frames",
                    len(self.calibration_buffer)
                )
            elif force:
                logger.info("Force calibration (single frame)")

            # Define destination points in normalized coordinates
            # Then scale to frame size
            w, h = self.config.width, self.config.height
            # Map markers directly to normalized coordinates:
            # ID 0 -> (0, 0) left-top
            # ID 1 -> (w, 0) right-top
            # ID 2 -> (w, h) right-bottom
            # ID 3 -> (0, h) left-bottom
            dst_points = np.array(
                [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
            )

            # Calculate perspective transform
            matrix = cv2.getPerspectiveTransform(src_points, dst_points)
            
            # Validate the transformation matrix
            if not self._validate_perspective_matrix(matrix):
                logger.warning("Perspective matrix validation failed")
                return False
            
            self.perspective_matrix = matrix
            logger.info("Perspective calibration successful")
            return True

        except Exception as e:
            logger.error("Failed to calibrate perspective: %s", e)
            return False

    def _validate_perspective_matrix(
        self, matrix: np.ndarray
    ) -> bool:
        """
        Validate that perspective transformation matrix is reasonable.
        
        Checks for extreme transformations that might indicate errors.
        """
        try:
            # Test transformation on corner points instead of condition number
            # Condition number can be very high for trapezoid shapes (oblique camera angle)
            # which are actually valid for perspective transformation
            
            test_points = np.array([
                [[0, 0]], [[100, 0]], [[100, 100]], [[0, 100]]
            ], dtype=np.float32)
            
            transformed = cv2.perspectiveTransform(test_points, matrix)
            
            # Check if transformation produces reasonable coordinates
            max_coord = max(self.config.width, self.config.height) * 5
            for pt in transformed:
                x, y = pt[0]
                if not (-max_coord <= x <= max_coord and 
                       -max_coord <= y <= max_coord):
                    logger.warning(
                        "Perspective transform produces extreme coordinates: (%.1f, %.1f)",
                        x, y
                    )
                    return False
            
            # Check that transformation is not degenerate (area should be preserved reasonably)
            # Calculate area of transformed quadrilateral
            pts = transformed.reshape(4, 2)
            def quad_area(points):
                # Shoelace formula
                n = len(points)
                area = 0.0
                for i in range(n):
                    j = (i + 1) % n
                    area += points[i][0] * points[j][1]
                    area -= points[j][0] * points[i][1]
                return abs(area) / 2.0
            
            original_area = 100 * 100  # 100x100 test square
            transformed_area = quad_area(pts)
            
            # Area should not change by more than factor of 100
            area_ratio = transformed_area / original_area
            if area_ratio < 0.01 or area_ratio > 100:
                logger.warning(
                    "Perspective transform changes area too much: ratio=%.2f",
                    area_ratio
                )
                return False
            
            # Log condition number for information but don't fail on it
            cond = np.linalg.cond(matrix)
            if cond > 100000:
                logger.info(
                    "High condition number (%.1f) - this is normal for oblique camera angles",
                    cond
                )
            
            return True
            
        except Exception as e:
            logger.warning("Matrix validation error: %s", e)
            return False

    def reset_calibration(self) -> None:
        """Reset calibration state."""
        self.perspective_matrix = None
        self.calibration_buffer.clear()
        self.calibration_frame_count = 0
        logger.info("Calibration reset")

    def warp_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Apply perspective transformation to frame."""
        if self.perspective_matrix is None:
            return None

        try:
            warped = cv2.warpPerspective(
                frame,
                self.perspective_matrix,
                (self.config.width, self.config.height),
            )
            return warped
        except Exception as e:
            logger.error("Failed to warp frame: %s", e)
            return None

    def pixel_to_normalized(
        self, x: int, y: int
    ) -> Tuple[float, float]:
        """Convert pixel coordinates to normalized (0-1) coordinates.

        Applies perspective calibration when available so mapping matches
        the warped preview/material coordinate space.
        """
        raw_u = x / self.config.width
        raw_v = y / self.config.height

        warped_x = float(x)
        warped_y = float(y)
        if self.perspective_matrix is not None:
            try:
                point = np.array([[[x, y]]], dtype=np.float32)
                warped = cv2.perspectiveTransform(point, self.perspective_matrix)
                warped_x, warped_y = warped[0][0]
            except Exception as e:
                logger.warning("Failed to warp point for normalization: %s", e)

        u = warped_x / self.config.width
        v = warped_y / self.config.height

        if self.perspective_matrix is not None:
            margin = 0.2
            if not (-margin <= u <= 1 + margin and -margin <= v <= 1 + margin):
                logger.debug(
                    "Warped point out of range (u=%.3f, v=%.3f); using raw coords",
                    u,
                    v,
                )
                u = raw_u
                v = raw_v

        # Clamp to [0, 1] to avoid out-of-bounds mapping after warp.
        u = max(0.0, min(1.0, u))
        v = max(0.0, min(1.0, v))
        return u, v

    def detect_hand_color_based(
        self, frame: np.ndarray
    ) -> Optional[Tuple[int, int]]:
        """
        Detect hand using simple color-based method (fallback).
        
        Returns fingertip pixel coordinates or None.
        """
        try:
            # Convert to HSV for skin color detection
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Define skin color range (adjust as needed)
            lower_skin = np.array([0, 20, 70], dtype=np.uint8)
            upper_skin = np.array([20, 255, 255], dtype=np.uint8)

            # Create mask
            mask = cv2.inRange(hsv, lower_skin, upper_skin)

            # Apply morphological operations to clean up
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

            # Find contours
            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            if not contours:
                return None

            # Find largest contour (hand)
            largest_contour = max(contours, key=cv2.contourArea)

            # Get the topmost point as fingertip approximation
            topmost_idx = largest_contour[:, :, 1].argmin()
            topmost = tuple(largest_contour[topmost_idx][0])

            return topmost

        except Exception as e:
            logger.error("Color-based hand detection failed: %s", e)
            return None

    def detect_hand_mediapipe(
        self, frame: np.ndarray
    ) -> Optional[Tuple[int, int]]:
        """
        Detect hand using MediaPipe Hands.
        
        Returns fingertip pixel coordinates (index finger tip) or None.
        """
        if self.hands_detector is None:
            logger.warning("MediaPipe Hands not initialized")
            return None

        try:
            detection_frame = frame
            scale = self.config.hand_detection_scale
            if scale != 1.0:
                detection_frame = cv2.resize(
                    frame,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_AREA,
                )

            # Convert BGR to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2RGB)
            
            # Make frame writeable=False for better performance
            rgb_frame.flags.writeable = False
            
            # Process frame
            results = self.hands_detector.process(rgb_frame)
            
            # Make frame writeable again
            rgb_frame.flags.writeable = True
            
            if not results.multi_hand_landmarks:
                # No hands detected (this is normal, not an error)
                return None
            
            # Get first hand landmarks
            hand_landmarks = results.multi_hand_landmarks[0]
            
            # Index finger tip is landmark 8
            index_tip = hand_landmarks.landmark[8]
            
            # Convert normalized coordinates to pixel coordinates
            h, w = frame.shape[:2]
            x = int(index_tip.x * w)
            y = int(index_tip.y * h)
            
            logger.debug("Hand detected at (%d, %d)", x, y)
            return (x, y)

        except Exception as e:
            logger.error("MediaPipe hand detection error: %s", e)
            return None

    def detect_hand(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Detect hand using configured method.
        
        Automatically falls back to color-based if MediaPipe fails.
        """
        if (
            self.config.hand_detection_method == "mediapipe"
            and self.hands_detector is not None
        ):
            result = self.detect_hand_mediapipe(frame)
            if result is not None:
                return result
            # Fall through to color-based if MediaPipe fails
        
        return self.detect_hand_color_based(frame)

    def smooth_fingertip(
        self, current: Optional[Tuple[int, int]]
    ) -> Optional[Tuple[float, float]]:
        """
        Apply smoothing to fingertip coordinates.
        
        Uses moving average and outlier rejection.
        """
        if current is None:
            # Clear buffer when no hand detected for clean re-detection
            if len(self.fingertip_buffer) > 0:
                self.fingertip_buffer.clear()
                self.last_fingertip = None
            return None

        # Check for outlier jumps (but allow large jumps after re-detection)
        if self.last_fingertip is not None and len(self.fingertip_buffer) > 1:
            last_x, last_y = self.last_fingertip
            curr_x, curr_y = current
            distance = np.sqrt(
                (curr_x - last_x) ** 2 + (curr_y - last_y) ** 2
            )

            if distance > self.config.max_jump_threshold:
                logger.debug(
                    "Fingertip jump detected: %.1f px (threshold: %d), accepting as re-detection",
                    distance,
                    self.config.max_jump_threshold,
                )
                # Clear buffer and start fresh to avoid pulling average
                self.fingertip_buffer.clear()

        # Add to buffer
        self.fingertip_buffer.append(current)

        # Calculate moving average
        if len(self.fingertip_buffer) > 0:
            avg_x = np.mean([p[0] for p in self.fingertip_buffer])
            avg_y = np.mean([p[1] for p in self.fingertip_buffer])
            smoothed = (float(avg_x), float(avg_y))
            self.last_fingertip = smoothed
            return smoothed

        return None

    def process_frame_from_image(
        self, frame: np.ndarray, force_calibrate: bool = False
    ) -> Optional[VisionFrame]:
        """Process a provided frame (used for offload mode)."""
        height, width = frame.shape[:2]
        if width != self.config.width or height != self.config.height:
            self.config.width = width
            self.config.height = height
        return self._process_frame(frame, force_calibrate=force_calibrate)

    def process_frame(self) -> Optional[VisionFrame]:
        """
        Process a single frame: capture, detect markers, detect hand.
        
        Returns VisionFrame with all detection results.
        """
        frame = self.capture_frame()
        if frame is None:
            return None
        height, width = frame.shape[:2]
        if width != self.config.width or height != self.config.height:
            logger.warning(
                "Camera resolution differs from config (%dx%d -> %dx%d), updating",
                self.config.width,
                self.config.height,
                width,
                height,
            )
            self.config.width = width
            self.config.height = height
            self.reset_calibration()
        return self._process_frame(frame, force_calibrate=False)

    def _process_frame(
        self, frame: np.ndarray, force_calibrate: bool
    ) -> Optional[VisionFrame]:
        """Shared vision pipeline for captured or provided frames."""
        timestamp = time.time()

        # Detect ArUco markers
        marker_ids, marker_corners = self.detect_aruco_markers(frame)

        # Auto-calibrate if enabled and 4 markers detected (keep updating even after calibrated)
        is_calibrated = self.perspective_matrix is not None
        if force_calibrate and len(marker_ids) >= 4:
            recalibrated = self.calibrate_perspective(
                marker_corners, force=True
            )
            if recalibrated:
                self.calibration_frame_count = 0
            is_calibrated = self.perspective_matrix is not None
        elif len(marker_ids) >= 4 and self.auto_calibrate_enabled:
            # Accumulate calibration data
            self.calibration_frame_count += 1

            # Auto-calibrate after seeing markers for multiple frames
            if self.calibration_frame_count >= 10:
                log_msg = (
                    "Auto-calibrating (seen markers for 10 frames)"
                    if not is_calibrated
                    else "Auto-recalibrating (seen markers for 10 frames)"
                )
                logger.info(log_msg)
                recalibrated = self.calibrate_perspective(
                    marker_corners, force=False
                )
                if recalibrated:
                    self.calibration_frame_count = 0
                # Keep current calibration if recalibration fails.
                is_calibrated = self.perspective_matrix is not None
        else:
            # Reset counter if we lose markers
            self.calibration_frame_count = 0

        # Detect hand on original frame (before warping)
        # This gives MediaPipe the full context to detect hands
        hand_detected = False
        fingertip_u = None
        fingertip_v = None

        interval = max(1, int(self.config.hand_detection_interval))
        self._hand_detection_counter = (self._hand_detection_counter + 1) % interval
        if self._hand_detection_counter == 0:
            fingertip_px = self.detect_hand(frame)
            self._last_hand_px = fingertip_px
        else:
            fingertip_px = self._last_hand_px
        smoothed = self.smooth_fingertip(fingertip_px)

        # Draw visualizations on original frame BEFORE warping
        display_frame = frame.copy()
        
        # Draw markers on original frame
        if marker_ids:
            for mid in marker_ids:
                if mid in marker_corners:
                    corners = marker_corners[mid]
                    center = np.mean(corners, axis=0).astype(int)
                    cv2.circle(display_frame, tuple(center), 5, (0, 255, 255), -1)
                    cv2.putText(
                        display_frame,
                        f"ID:{mid}",
                        (center[0] + 10, center[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 255),
                        2,
                    )
            
            # Draw calibration boundary if we have all 4 markers
            required_ids = self.config.marker_ids[:4]
            ordered = self._order_markers(marker_corners, required_ids)
            if ordered:
                outer_corners = []
                quad_center = np.mean([entry[2] for entry in ordered], axis=0)
                for _, corners, _ in ordered:
                    inner_corner = self._inner_corner(corners, quad_center).astype(
                        np.int32
                    )
                    outer_corners.append(inner_corner)
                
                # Draw yellow quadrilateral showing calibration area
                pts = np.array(outer_corners, np.int32).reshape((-1, 1, 2))
                cv2.polylines(display_frame, [pts], True, (0, 255, 255), 3)

        # Compute warped fingertip for calibrated preview (if available)
        warped_fingertip = None
        if smoothed is not None and self.perspective_matrix is not None:
            try:
                point = np.array([[[smoothed[0], smoothed[1]]]], dtype=np.float32)
                warped = cv2.perspectiveTransform(point, self.perspective_matrix)
                warped_x, warped_y = warped[0][0]
                warped_fingertip = (int(warped_x), int(warped_y))
            except Exception as e:
                logger.warning("Failed to warp fingertip for preview: %s", e)

        # Draw hand detection on original frame before warping (when not calibrated)
        if smoothed is not None and not is_calibrated:
            x, y = int(smoothed[0]), int(smoothed[1])
            cv2.circle(display_frame, (x, y), 15, (0, 255, 0), -1)
            cv2.circle(display_frame, (x, y), 20, (255, 255, 255), 2)

            # Draw crosshair
            cv2.line(display_frame, (x - 30, y), (x + 30, y), (0, 255, 0), 2)
            cv2.line(display_frame, (x, y - 30), (x, y + 30), (0, 255, 0), 2)

        # Warp frame if calibrated (for visualization)
        if is_calibrated:
            warped = self.warp_frame(display_frame)
            if warped is not None:
                display_frame = warped

                # Draw fingertip on calibrated preview in warped coordinates
                if warped_fingertip is not None:
                    x, y = warped_fingertip
                    if 0 <= x < self.config.width and 0 <= y < self.config.height:
                        cv2.circle(display_frame, (x, y), 15, (0, 255, 0), -1)
                        cv2.circle(display_frame, (x, y), 20, (255, 255, 255), 2)
                        cv2.line(display_frame, (x - 30, y), (x + 30, y), (0, 255, 0), 2)
                        cv2.line(display_frame, (x, y - 30), (x, y + 30), (0, 255, 0), 2)

        # Store frames for preview
        self.last_frame = frame
        self.last_display_frame = display_frame

        if smoothed is not None:
            hand_detected = True
            fingertip_u, fingertip_v = self.pixel_to_normalized(
                int(smoothed[0]), int(smoothed[1])
            )

        # Convert marker corners to serializable format
        serializable_corners = {}
        for mid, corners in marker_corners.items():
            serializable_corners[mid] = corners.tolist()

        # Show preview if debug enabled
        if self.config.debug_show_preview:
            self._show_debug_preview(working_frame, smoothed)

        return VisionFrame(
            timestamp=timestamp,
            markers_detected=marker_ids,
            markers_corners=serializable_corners,
            is_calibrated=is_calibrated,
            hand_detected=hand_detected,
            fingertip_u=fingertip_u,
            fingertip_v=fingertip_v,
        )

    def _show_debug_preview(
        self, frame: np.ndarray, fingertip: Optional[Tuple[float, float]]
    ) -> None:
        """Show debug preview window with detections."""
        preview = frame.copy()

        # Draw fingertip if detected
        if fingertip is not None:
            cv2.circle(
                preview,
                (int(fingertip[0]), int(fingertip[1])),
                10,
                (0, 255, 0),
                -1,
            )

        cv2.imshow("TeachArm Vision Debug", preview)
        cv2.waitKey(1)

    def get_preview_frame(self) -> Optional[np.ndarray]:
        """Get the last processed frame with visualizations for preview."""
        return self.last_display_frame
