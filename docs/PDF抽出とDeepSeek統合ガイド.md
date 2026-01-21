# PDF抽出とDeepSeek統合ガイド

## 概要

TeachArmでは、PDFから座標付きテキストを事前抽出し、DeepSeekに教材全文とポインター情報を送ることで、より精度の高い回答生成を実現しています。

## アーキテクチャ

```
PDF → pymupdf → {material_id}_text.json → Material.full_text
                                        → Region.extracted_text
                                               ↓
ユーザー操作 → 座標 + region type → DeepSeek → 回答生成
```

### 入力情報の強化

| 項目 | 内容 | 効果 |
|------|------|------|
| **PDF全文** | 教材全ページのテキスト | 文脈理解、全体の流れ把握 |
| **Region抽出テキスト** | 指定領域の実テキスト | 該当箇所の正確な内容 |
| **Region type** | instruction/question/choice等 | 問題構造の理解 |
| **Pointer座標** | (x, y) 正規化座標 | ユーザーが何を指しているか |
| **Region bbox** | 領域範囲 | 周辺コンテキスト推定 |
| **ユーザー発話** | 音声認識テキスト | 質問の意図把握 |

## 使用手順

### 1. PDF→テキスト抽出

新しい教材を追加したら、まずPDFからテキストを抽出します。

```bash
# pymupdfがインストールされているか確認
pip install pymupdf

# Material Aのテキストを抽出
python tools/extract_pdf_text.py materials/material_A.json

# 出力: materials/A_text.json
```

**抽出されるデータ構造:**

```json
{
  "material_id": "A",
  "pdf_file": "japanese3article-1608-01.pdf",
  "pages": [
    {
      "page_num": 0,
      "width": 842.0,
      "height": 595.0,
      "blocks": [
        {
          "bbox": {"x": 0.59, "y": 0.05, "w": 0.22, "h": 0.44},
          "text": "段落のテキスト内容..."
        }
      ]
    }
  ],
  "regions": [
    {
      "id": "paragraph1",
      "type": "paragraph",
      "bbox": {...},
      "extracted_text": "この段落に含まれるテキスト"
    }
  ]
}
```

### 2. 起動時の自動読み込み

`teacharm/materials.py` の `load_materials()` が自動的に:
1. `material_*.json` を読み込み
2. 同名の `{material_id}_text.json` があれば読み込み
3. `Material.full_text` に全文を設定
4. 各 `Region.extracted_text` に該当テキストを設定

### 3. DeepSeekへの送信

`teacharm/services/dialogue.py` から呼び出し例:

```python
from teacharm.services.deepseek import DeepSeekService

# Materialオブジェクトを取得（full_text, extracted_text含む）
material = materials.get("A")
region = material.get_region("paragraph1")

# ポインター座標とユーザー発話を含めて生成
response = await deepseek_service.generate_explanation(
    region=region,
    material_id="A",
    style="hint",
    pointer_coords={"x": 0.59, "y": 0.05},
    pdf_full_text=material.full_text,  # PDF全文
    user_speech="これなに?"
)
```

### 4. DeepSeekが受け取る情報

**システムプロンプト:**
- 役割、制約、スタイル指示
- PDF全文（最大3000文字、背景情報として）

**ユーザーメッセージ:**
```
教材ID: A
対象: paragraph1 (paragraph)
ポインター座標: (x=0.590, y=0.049)
領域範囲: x=0.590~0.812, y=0.049~0.491
領域タイプ: paragraph

【この領域の内容】
（PDF抽出テキスト）

【参考: 既存の説明】
（スクリプトがあれば）

【ユーザーの質問】
これなに?

上記の質問に対して、教材内容を踏まえて1~2文で答えてください。
```

## メリット

### 精度向上のポイント

1. **Region type情報**
   - `instruction` → 問題文の説明が必要
   - `question` → 設問への回答ヒント
   - `choice` → 選択肢の理解支援

2. **座標情報**
   - どこを指しているか正確に伝わる
   - bboxで周辺テキストも参照可能

3. **PDF全文**
   - 教材全体の文脈を理解
   - 前後の問題とのつながりを把握

4. **抽出テキスト**
   - OCR不要、正確なテキスト
   - 座標と内容が完全一致

## トラブルシューティング

### テキストが抽出されない

```bash
# PDFファイルの確認
ls -la materials/*.pdf

# 手動実行でエラー確認
python tools/extract_pdf_text.py materials/material_A.json --materials-dir materials
```

### 領域テキストがずれる

座標登録時の問題の可能性。Control Panelで再登録:
1. ブラウザで `http://localhost:5173` を開く
2. Material Coordinate Editor でPDFプレビュー確認
3. 矩形を調整して Save

### DeepSeekが教材外の質問に答える

`teacharm/services/deepseek.py` の `_build_system_prompt()` を調整:
- 制約をより厳格に記述
- 拒否時のテンプレート文言を追加

## 今後の拡張

- [ ] 複数ページPDFのサポート
- [ ] 図表領域の画像抽出
- [ ] 縦書きテキストの正確な座標マッピング
- [ ] マルチモーダルモデル（Vision）への対応

## 関連ファイル

- [tools/extract_pdf_text.py](../tools/extract_pdf_text.py) - PDF抽出スクリプト
- [teacharm/materials.py](../teacharm/materials.py) - Material/Region モデル定義
- [teacharm/services/deepseek.py](../teacharm/services/deepseek.py) - DeepSeek統合
- [materials/](../materials/) - 教材JSONとPDFファイル
