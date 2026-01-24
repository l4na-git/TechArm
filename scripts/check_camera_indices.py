"""List available camera indices for OpenCV VideoCapture."""

from __future__ import annotations

import argparse
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List OpenCV camera indices and optionally preview them."
    )
    parser.add_argument(
        "max_index",
        nargs="?",
        type=int,
        default=6,
        help="Number of indices to check (default: 6).",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show a short preview window for each available camera.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=1200,
        help="Preview wait time per camera in ms (default: 1200).",
    )
    return parser.parse_args()


def main() -> int:
    try:
        import cv2
    except ImportError:
        print("OpenCV (cv2) is not installed. Install requirements/vision.txt first.")
        return 1

    args = _parse_args()

    for i in range(args.max_index):
        cap = cv2.VideoCapture(i)
        ok = cap.isOpened()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if ok and args.preview:
            for _ in range(5):
                cap.read()
            ret, frame = cap.read()
            if ret:
                cv2.putText(
                    frame,
                    f"index {i}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.1,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow(f"camera index {i}", frame)
                key = cv2.waitKey(args.wait) & 0xFF
                cv2.destroyWindow(f"camera index {i}")
                if key == ord("q"):
                    cap.release()
                    break
        cap.release()
        status = "OK" if ok else "NG"
        print(f"index {i}: {status} {width}x{height}")

    if args.preview:
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
