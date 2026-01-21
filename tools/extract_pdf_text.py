#!/usr/bin/env python3
"""PDF→テキスト抽出ツール（座標付き）

PDFからテキストを抽出し、materials/{material_id}_text.json に保存します。
各region bboxに含まれるテキストもマッピングします。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    import pymupdf  # PyMuPDF
except ImportError:
    print("Error: pymupdf not installed. Install with: pip install pymupdf")
    exit(1)


def extract_text_from_pdf(
    pdf_path: Path, material_data: Dict[str, Any]
) -> Dict[str, Any]:
    """PDFからテキストと座標を抽出し、region情報とマッピング"""
    doc = pymupdf.open(pdf_path)
    
    result = {
        "material_id": material_data["material_id"],
        "pdf_file": material_data["pdf_file"],
        "pages": [],
        "regions": []
    }
    
    # 各ページのテキストを抽出
    for page_num, page in enumerate(doc):
        page_dict = page.get_text("dict")  # 座標付きテキスト取得
        page_width = page.rect.width
        page_height = page.rect.height
        
        # ブロック単位でテキストと座標を収集
        blocks = []
        for block in page_dict["blocks"]:
            if block["type"] == 0:  # テキストブロック
                block_bbox = block["bbox"]  # (x0, y0, x1, y1)
                
                # 正規化座標に変換
                normalized_bbox = {
                    "x": block_bbox[0] / page_width,
                    "y": block_bbox[1] / page_height,
                    "w": (block_bbox[2] - block_bbox[0]) / page_width,
                    "h": (block_bbox[3] - block_bbox[1]) / page_height
                }
                
                # テキスト取得（縦書き対応: 改行除去）
                lines = []
                for line in block["lines"]:
                    line_text = "".join(
                        [span["text"] for span in line["spans"]]
                    )
                    lines.append(line_text)
                
                # 改行を除去して連結
                full_text = "\n".join(lines)
                clean_text = full_text.replace("\n", "")
                
                blocks.append({
                    "bbox": normalized_bbox,
                    "text": clean_text
                })
        
        result["pages"].append({
            "page_num": page_num,
            "width": page_width,
            "height": page_height,
            "blocks": blocks
        })
    
    # 各regionに該当するテキストを抽出
    for region in material_data["regions"]:
        region_bbox = region["bbox"]
        extracted_text = extract_region_text(
            result["pages"], region_bbox, page_num=0  # TODO: 複数ページ対応
        )
        
        result["regions"].append({
            "id": region["id"],
            "type": region["type"],
            "bbox": region_bbox,
            "extracted_text": extracted_text
        })
    
    doc.close()
    return result


def extract_region_text(
    pages: List[Dict], region_bbox: Dict[str, float], page_num: int = 0
) -> str:
    """指定された領域(bbox)に含まれるテキストを抽出"""
    if page_num >= len(pages):
        return ""
    
    page = pages[page_num]
    region_x = region_bbox["x"]
    region_y = region_bbox["y"]
    region_w = region_bbox["w"]
    region_h = region_bbox["h"]
    
    # 領域に重なるブロックを収集
    matched_blocks = []
    for block in page["blocks"]:
        bbox = block["bbox"]
        
        # bbox重なり判定（簡易版：中心点が領域内にあるか）
        block_center_x = bbox["x"] + bbox["w"] / 2
        block_center_y = bbox["y"] + bbox["h"] / 2
        
        if (
            region_x <= block_center_x <= region_x + region_w
            and region_y <= block_center_y <= region_y + region_h
        ):
            matched_blocks.append(block)
    
    # Y座標順にソート（上から下）
    matched_blocks.sort(key=lambda b: b["bbox"]["y"])
    
    # 縦書き対応: 改行を削除して連結
    raw_text = "\n".join([b["text"] for b in matched_blocks])
    # 改行を空文字列に置換（縦書きの1文字ごとの改行を削除）
    clean_text = raw_text.replace("\n", "")
    
    return clean_text


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from PDF with coordinates"
    )
    parser.add_argument(
        "material_json",
        type=Path,
        help="Path to material JSON file (e.g., materials/material_A.json)"
    )
    parser.add_argument(
        "--materials-dir",
        type=Path,
        default=Path("materials"),
        help="Directory containing PDFs and materials (default: materials/)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output JSON file "
            "(default: {material_id}_text.json in materials dir)"
        ),
    )
    
    args = parser.parse_args()
    
    # Material JSONを読み込み
    with open(args.material_json, "r", encoding="utf-8") as f:
        material_data = json.load(f)
    
    material_id = material_data["material_id"]
    pdf_file = material_data.get("pdf_file")
    
    if not pdf_file:
        print(f"Error: 'pdf_file' not found in {args.material_json}")
        exit(1)
    
    pdf_path = args.materials_dir / pdf_file
    if not pdf_path.exists():
        print(f"Error: PDF not found at {pdf_path}")
        exit(1)
    
    print(f"Extracting text from {pdf_path}...")
    extracted_data = extract_text_from_pdf(pdf_path, material_data)
    
    # 出力ファイル決定
    if args.output:
        output_path = args.output
    else:
        output_path = args.materials_dir / f"{material_id}_text.json"
    
    # 保存
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Saved to {output_path}")
    print(f"  - Pages: {len(extracted_data['pages'])}")
    print(f"  - Regions: {len(extracted_data['regions'])}")
    
    # 簡易プレビュー
    for region in extracted_data["regions"][:3]:
        print(f"\n[{region['id']} ({region['type']})]")
        preview = region["extracted_text"][:100].replace("\n", " ")
        print(f"  {preview}...")


if __name__ == "__main__":
    main()
