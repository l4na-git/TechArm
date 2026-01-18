# Vision機能 セットアップ & 使用ガイド

## 概要

TeachArmのVision機能は、カメラ入力から以下の処理を行います:

- **ArUcoマーカー検出**: 教材の位置を特定し、透視変換で正規化
- **手・指先検出**: MediaPipe Handsで人差し指の先端座標を検出
- **座標正規化**: 検出結果を0-1の正規化座標に変換
- **リアルタイム配信**: WebSocketで10fpsのフレーム情報を配信

## システム要件

### 対応OS
- **macOS**: 開発・テスト環境
- **Linux (Raspberry Pi)**: 展示・本番環境
- **Windows**: 未サポート（理論上は動作可能）

### ハードウェア
- Webカメラ (1280x720以上推奨)
- ArUcoマーカー4枚 (DICT_4X4_50, ID: 0, 1, 2, 3)

### ソフトウェア依存関係
```txt
opencv-python==4.9.0.80
opencv-contrib-python==4.9.0.80
numpy==1.26.4
mediapipe==0.10.9
```

## セットアップ

### 1. 依存関係のインストール

```bash
# プロジェクトルートで実行
uv pip install -r requirements.txt
```

MediaPipeのインストールには数分かかる場合があります（約45MB）。

### 2. カメラ設定

`config/camera.yaml` で設定をカスタマイズ:

```yaml
# カメラデバイス設定
device:
  index: 0  # macOSは0、Linuxは/dev/video0を自動選択
  # path: "/dev/video0"  # 明示的にデバイスパスを指定する場合

# 解像度設定
resolution:
  width: 1280
  height: 720

# 手検出設定
hand_detection:
  method: "mediapipe"  # "mediapipe" (推奨) or "color" (フォールバック)
  confidence_threshold: 0.5
  model_complexity: 0  # 0 (高速) or 1 (高精度)
  smoothing_window: 5  # 移動平均のフレーム数
  max_jump_threshold: 40  # 外れ値除去の閾値(px)
```

### 3. カメラアクセス権限 (macOS)

初回実行時、macOSがカメラアクセスを要求します:

1. ターミナルでテスト実行:
   ```bash
   python test_vision.py
   ```

2. システム環境設定 > セキュリティとプライバシー > カメラ
3. 使用するターミナルアプリ（例: iTerm2, Terminal.app）を許可

### 4. ArUcoマーカーの準備

4つのArUcoマーカーを印刷・配置:

```
ID 0 (左上)         ID 1 (右上)
    ┌─────────────┐
    │             │
    │   教材面    │
    │             │
    └─────────────┘
ID 3 (左下)         ID 2 (右下)
```

マーカー生成方法:
```python
# tools/generate_aruco_markers.py (作成推奨)
import cv2
import numpy as np

aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
for marker_id in [0, 1, 2, 3]:
    marker_image = cv2.aruco.generateImageMarker(aruco_dict, marker_id, 200)
    cv2.imwrite(f"marker_{marker_id}.png", marker_image)
```

## 使用方法

### 1. インタラクティブデモ（推奨）

リアルタイムでカメラ映像と検出結果を確認:

```bash
uv run python demo_vision.py
```

**デモ画面の機能:**
- リアルタイムカメラプレビュー
- 検出された指先の可視化（緑の円と十字）
- 正規化座標の表示
- ArUcoマーカーの検出状況
- キャリブレーション状態

**キーボード操作:**
- `q`: デモを終了
- `c`: ArUcoキャリブレーションを実行（4つのマーカーが必要）
- `s`: 現在のフレームをスクリーンショット保存

**表示内容:**
```
Status: CALIBRATED / NOT CALIBRATED (赤/緑)
Markers: [0, 1, 2, 3] (検出されたマーカーID)
Hand: Detected / Not detected
Method: mediapipe / color

画面上:
- 緑の円と十字: 検出された指先
- (u, v): 正規化座標
```

### 2. スタンドアロンテスト

プレビューなしで動作確認:

```bash
# Vision機能の単体テスト
uv run python test_vision.py
```

期待される出力:
```
=== VisionService Test ===

[1] Loading settings...
✓ Settings loaded: /path/to/config

[2] Initializing VisionService...
✓ VisionService initialized
  - Camera device: 0
  - Resolution: 1280x720
  - Hand detection: mediapipe
  - MediaPipe available: Yes

[3] Starting camera...
✓ Camera started successfully

[4] Processing test frames (5 frames)...
  Frame 1:
    - Timestamp: 1705599186.70
    - Markers: [0, 1, 2, 3]
    - Calibrated: True
    - Hand detected: True
    - Fingertip: (0.456, 0.321)
...
```

### 2. サーバー統合での使用

### 2. サーバー統合での使用

#### サーバー起動

```bash
uv run python -m teacharm.main
```

#### API エンドポイント

**カメラ起動**
```bash
curl -X POST http://localhost:8000/api/vision/start
# Response: {"status": "started"}
```

**カメラ停止**
```bash
curl -X POST http://localhost:8000/api/vision/stop
# Response: {"status": "stopped"}
```

**ArUcoキャリブレーション実行**
```bash
curl -X POST http://localhost:8000/api/vision/calibrate
# Response: {"status": "calibrated", "markers_detected": [0, 1, 2, 3]}
```

#### WebSocket ストリーミング

JavaScriptでの接続例:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/vision');

ws.onmessage = (event) => {
  const frame = JSON.parse(event.data);
  console.log('Vision frame:', {
    timestamp: frame.timestamp,
    markers: frame.markers_detected,
    calibrated: frame.is_calibrated,
    hand: frame.hand_detected,
    fingertip: frame.fingertip_u && frame.fingertip_v 
      ? `(${frame.fingertip_u.toFixed(3)}, ${frame.fingertip_v.toFixed(3)})`
      : null
  });
};
```

## トラブルシューティング

### カメラが開けない (macOS)

**症状**: `Failed to open camera device: 0`

**解決策**:
1. カメラアクセス権限を確認
2. 他のアプリ（Zoom、FaceTime等）でカメラが使用中でないか確認
3. `device.index` を変更してみる (0 → 1)

### MediaPipeが利用できない

**症状**: `MediaPipe not available, falling back to color-based detection`

**解決策**:
```bash
# MediaPipeを再インストール
uv pip uninstall mediapipe
uv pip install mediapipe==0.10.9
```

**回避策**: `config/camera.yaml` で色ベース検出に切り替え:
```yaml
hand_detection:
  method: "color"
```

### 手検出の精度が低い

**MediaPipe使用時**:
- 照明を改善（明るい環境で使用）
- `confidence_threshold` を下げる (0.5 → 0.3)
- `model_complexity` を1に変更（処理は重くなる）

**色ベース使用時**:
- 背景色と肌色のコントラストを高める
- 照明条件を安定させる
- MediaPipeに切り替えることを推奨

### ArUcoマーカーが検出されない

**チェックリスト**:
- [ ] 4つ全てのマーカーがカメラ視野内にある
- [ ] マーカーが明瞭に印刷されている（ぼやけていない）
- [ ] マーカーが平面に配置されている（歪んでいない）
- [ ] 照明が十分（影がマーカーを覆っていない）

**デバッグモード**:
```yaml
# config/camera.yaml
debug:
  show_preview: true  # プレビューウィンドウを表示
```

## プラットフォーム固有の注意事項

### macOS
- カメラデバイスは通常 `index: 0`
- アクセス権限の許可が必須
- 開発・テストに最適

### Linux (Raspberry Pi)
- カメラデバイスは `/dev/video0` を自動選択
- `libcamera` 使用の場合は追加設定が必要な場合あり
- パフォーマンス最適化:
  ```yaml
  hand_detection:
    model_complexity: 0  # 軽量モデル推奨
  resolution:
    width: 640  # 解像度を下げる
    height: 480
  ```

## パフォーマンスチューニング

### 高速化
```yaml
resolution:
  width: 640
  height: 480
  fps: 15

hand_detection:
  model_complexity: 0
  smoothing_window: 3
```

### 高精度化
```yaml
resolution:
  width: 1920
  height: 1080
  fps: 30

hand_detection:
  model_complexity: 1
  confidence_threshold: 0.7
  smoothing_window: 10
```

## 次のステップ

- Control Panelからのリアルタイムモニタリング
- 複数の手検出（現在は1本の手のみ）
- ジェスチャー認識の追加
- YOLOベースの手検出との比較

## 参考リンク

- [MediaPipe Hands](https://google.github.io/mediapipe/solutions/hands.html)
- [OpenCV ArUco](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html)
- [TeachArm開発仕様書](./開発仕様書.md)
