# ツール集 (tools/)

TeachArmの開発・セットアップに使用するユーティリティツールです。

## ツール一覧

### 1. ArUcoマーカー生成 (generate_aruco_markers.py)

Vision機能のキャリブレーション用ArUcoマーカーを生成します。

**使用方法:**
```bash
# デフォルト設定で生成
python tools/generate_aruco_markers.py

# カスタム設定
python tools/generate_aruco_markers.py \
  --output my_markers \
  --size 300 \
  --dict DICT_4X4_50
```

**出力:**
- `aruco_marker_0_top-left.png`
- `aruco_marker_1_top-right.png`
- `aruco_marker_2_bottom-right.png`
- `aruco_marker_3_bottom-left.png`

印刷して教材の四隅に配置してください。

### 2. マイク録音 + ASR送信 (mic_record_send.py)

マイクから録音して `/api/dialogue/audio` に送信します。

**使用方法:**
```bash
python tools/mic_record_send.py --duration 4
```

**オプション例:**
```bash
python tools/mic_record_send.py \
  --duration 3 \
  --samplerate 16000 \
  --endpoint http://localhost:8000/api/asr/transcribe
```

### 3. 押している間だけ録音（キーボード） (mic_record_send_keyboard.py)

Macなどで、キーを押している間だけ録音して送信します。

**使用方法:**
```bash
python tools/mic_record_send_keyboard.py --key space
```

### 4. 押している間だけ録音（GPIOボタン） (mic_record_send_gpio.py)

Raspberry Piのボタン入力で、押している間だけ録音して送信します。

**使用方法:**
```bash
python tools/mic_record_send_gpio.py --pin 17 --pull-up
```

### 5. 座標変換ツール (convert_coordinates.py)

教材の座標をピクセル値から正規化座標（0.0~1.0）に変換します。

#### 単一座標の変換

```bash
python tools/convert_coordinates.py \
  --width 1920 \
  --height 1080 \
  --single \
  --px 192 \
  --py 108 \
  --pw 1152 \
  --ph 162
```

**出力:**
```json
{
  "x": 0.1,
  "y": 0.1,
  "w": 0.6,
  "h": 0.15
}
```

### 5. 一括変換（JSONファイル）

**入力ファイル（example_pixel_coordinates.json）:**
```json
{
  "material_id": "C",
  "regions": [
    {
      "id": "q1",
      "type": "question",
      "bbox_pixel": {
        "x": 96,
        "y": 54,
        "w": 1728,
        "h": 216
      },
      "on_point": ["Q1_INTRO"]
    }
  ]
}
```

**変換実行:**
```bash
python tools/convert_coordinates.py \
  --width 1920 \
  --height 1080 \
  -i tools/example_pixel_coordinates.json \
  -o materials/material_C.json
```

**出力（materials/material_C.json）:**
```json
{
  "material_id": "C",
  "regions": [
    {
      "id": "q1",
      "type": "question",
      "bbox": {
        "x": 0.05,
        "y": 0.05,
        "w": 0.9,
        "h": 0.2
      },
      "on_point": ["Q1_INTRO"]
    }
  ]
}
```

### 6. 標準入力/出力

```bash
cat tools/example_pixel_coordinates.json | \
  python tools/convert_coordinates.py -w 1920 -h 1080 > output.json
```

## オプション

| オプション | 短縮 | 必須 | 説明 | デフォルト |
|----------|------|------|------|-----------|
| `--width` | `-w` | ✅ | 画像の幅（ピクセル） | - |
| `--height` | `-h` | ✅ | 画像の高さ（ピクセル） | - |
| `--input` | `-i` | ❌ | 入力JSONファイル | 標準入力 |
| `--output` | `-o` | ❌ | 出力JSONファイル | 標準出力 |
| `--precision` | `-p` | ❌ | 小数点精度 | 3 |
| `--single` | - | ❌ | 単一座標モード | false |
| `--px` | - | ⚠️ | ピクセルx座標（単一モード時） | - |
| `--py` | - | ⚠️ | ピクセルy座標（単一モード時） | - |
| `--pw` | - | ⚠️ | ピクセル幅（単一モード時） | - |
| `--ph` | - | ⚠️ | ピクセル高さ（単一モード時） | - |

## よくある画像サイズ

| 解像度 | 幅 | 高さ | 用途 |
|--------|-----|------|------|
| Full HD | 1920 | 1080 | 一般的なWebカメラ |
| HD | 1280 | 720 | Raspberry Pi Camera V2 |
| 4K | 3840 | 2160 | 高解像度カメラ |
| VGA | 640 | 480 | 低解像度カメラ |

## サンプルワークフロー

1. **カメラ映像をキャプチャ**
   ```bash
   # TeachArmサーバーのControl Panelからスクリーンショット保存
   ```

2. **画像サイズを確認**
   ```bash
   file screenshot.png
   # → PNG image data, 1920 x 1080, 8-bit/color RGB
   ```

3. **画像編集ツールでピクセル座標を測定**
   - GIMP / Photoshop / Preview.app 等で矩形選択
   - x, y, width, height をメモ

4. **JSONファイルを作成**
   ```json
   {
     "material_id": "MyMaterial",
     "regions": [
       {
         "id": "region1",
         "type": "question",
         "bbox_pixel": {"x": 100, "y": 200, "w": 800, "h": 150},
         "on_point": ["COMMAND_1"]
       }
     ]
   }
   ```

5. **変換実行**
   ```bash
   python tools/convert_coordinates.py \
     -w 1920 -h 1080 \
     -i my_pixel_coords.json \
     -o materials/material_MyMaterial.json
   ```

6. **サーバー再起動して確認**
   ```bash
   uv run python -m teacharm.main
   # ログで "Loaded material 'MyMaterial'" を確認
   ```

### 3. PDF抽出ツール (extract_pdf_text.py)

教材PDFから領域ごとにテキストを抽出します。

**使用方法:**
```bash
python tools/extract_pdf_text.py materials/material_A.json
# 出力: materials/A_text.json
```

詳細は [PDF抽出とDeepSeek統合ガイド](../docs/PDF抽出とDeepSeek統合ガイド.md) を参照。

## トラブルシューティング

### エラー: "Input JSON must have 'regions' field"

**原因:** JSONファイルに `regions` フィールドがない

**解決策:**
```json
{
  "material_id": "...",
  "regions": [...]  // ← 必須
}
```

### エラー: "--single requires --px, --py, --pw, --ph"

**原因:** 単一モード時に座標パラメータが不足

**解決策:** すべてのパラメータを指定
```bash
python tools/convert_coordinates.py \
  -w 1920 -h 1080 --single \
  --px 100 --py 200 --pw 800 --ph 150
```

### 座標がずれる

**原因:** 画像サイズが間違っている

**解決策:** 実際のカメラ解像度を確認
```bash
# Control Panel のカメラ設定で解像度を確認
# または ffmpeg で確認:
ffmpeg -i /dev/video0 -frames:v 1 test.png
file test.png
```
