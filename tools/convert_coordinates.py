#!/usr/bin/env python3
"""座標変換ツール - ピクセル座標を正規化座標に変換"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List


def pixel_to_normalized(
    px: float,
    py: float,
    pw: float,
    ph: float,
    image_width: int,
    image_height: int,
    precision: int = 3,
) -> Dict[str, float]:
    """
    ピクセル座標を正規化座標に変換

    Args:
        px: ピクセルx座標（左上）
        py: ピクセルy座標（左上）
        pw: ピクセル幅
        ph: ピクセル高さ
        image_width: 画像の幅（ピクセル）
        image_height: 画像の高さ（ピクセル）
        precision: 小数点精度（デフォルト: 3）

    Returns:
        正規化座標 {"x": 0.1, "y": 0.2, "w": 0.6, "h": 0.15}
    """
    return {
        "x": round(px / image_width, precision),
        "y": round(py / image_height, precision),
        "w": round(pw / image_width, precision),
        "h": round(ph / image_height, precision),
    }


def batch_convert(
    regions: List[Dict],
    image_width: int,
    image_height: int,
    precision: int = 3,
) -> List[Dict]:
    """
    複数の領域を一括変換

    Args:
        regions: ピクセル座標の領域リスト
        image_width: 画像幅
        image_height: 画像高さ
        precision: 小数点精度

    Returns:
        正規化座標の領域リスト
    """
    converted = []
    for region in regions:
        bbox = region.get("bbox_pixel", {})
        if not bbox:
            print(
                f"Warning: Region '{region.get('id')}' missing bbox_pixel",
                file=sys.stderr,
            )
            continue

        normalized_bbox = pixel_to_normalized(
            bbox["x"],
            bbox["y"],
            bbox["w"],
            bbox["h"],
            image_width,
            image_height,
            precision,
        )

        converted_region = {
            "id": region["id"],
            "type": region["type"],
            "bbox": normalized_bbox,
            "on_point": region.get("on_point", []),
        }

        if "on_help" in region:
            converted_region["on_help"] = region["on_help"]

        converted.append(converted_region)

    return converted


def main():
    parser = argparse.ArgumentParser(
        description="ピクセル座標を正規化座標に変換"
    )
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        required=True,
        help="画像の幅（ピクセル）",
    )
    parser.add_argument(
        "-h",
        "--height",
        type=int,
        required=True,
        dest="height",
        help="画像の高さ（ピクセル）",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        help="入力JSONファイル（省略時は標準入力）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="出力JSONファイル（省略時は標準出力）",
    )
    parser.add_argument(
        "-p",
        "--precision",
        type=int,
        default=3,
        help="小数点精度（デフォルト: 3）",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="単一座標の変換（--px --py --pw --ph を使用）",
    )
    parser.add_argument("--px", type=float, help="ピクセルx座標")
    parser.add_argument("--py", type=float, help="ピクセルy座標")
    parser.add_argument("--pw", type=float, help="ピクセル幅")
    parser.add_argument("--ph", type=float, help="ピクセル高さ")

    args = parser.parse_args()

    # 単一座標の変換
    if args.single:
        if not all([args.px, args.py, args.pw, args.ph]):
            parser.error(
                "--single requires --px, --py, --pw, --ph"
            )

        result = pixel_to_normalized(
            args.px,
            args.py,
            args.pw,
            args.ph,
            args.width,
            args.height,
            args.precision,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # 一括変換
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    # regions フィールドを変換
    if "regions" not in data:
        print(
            "Error: Input JSON must have 'regions' field",
            file=sys.stderr,
        )
        sys.exit(1)

    converted_regions = batch_convert(
        data["regions"], args.width, args.height, args.precision
    )

    output_data = {
        "material_id": data.get("material_id", ""),
        "regions": converted_regions,
    }

    output_json = json.dumps(
        output_data, indent=2, ensure_ascii=False
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(
            f"Converted {len(converted_regions)} regions → {args.output}",
            file=sys.stderr,
        )
    else:
        print(output_json)


if __name__ == "__main__":
    main()
