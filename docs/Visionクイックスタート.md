# TeachArm Vision機能 クイックスタート

## 5分でセットアップ

### 1. 依存関係をインストール (初回のみ)

```bash
cd /path/to/TechArm
pip install -r requirements/vision.txt

MediaPipe の `solutions` を使いたい場合は Python 3.10 の venv で
`requirements/vision-py310.txt` を使う:

```bash
/opt/homebrew/opt/python@3.10/bin/python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements/vision-py310.txt
```
```

> ⏱️ MediaPipeのインストールに数分かかります（約45MB）

### 2. ArUcoマーカーを生成

```bash
python tools/generate_aruco_markers.py
```

生成されたマーカー（`aruco_markers/` フォルダ内）を印刷し、教材の四隅に配置:

```
marker_0 (左上)    marker_1 (右上)
    ┌──────────┐
    │  教材面  │
    └──────────┘
marker_3 (左下)    marker_2 (右下)
```

### 3. カメラアクセスを許可 (macOSのみ)

初回起動時、システム環境設定でカメラアクセスを許可してください。

### 4. 動作確認

**基本テスト（プレビューなし）:**
```bash
python test_vision.py
```

**インタラクティブデモ（プレビュー付き）:**
```bash
python demo_vision.py
```

デモ画面の操作:
- `q`: 終了
- `c`: キャリブレーション実行（4つのマーカーが必要）
- `s`: スクリーンショット保存

期待される表示:
- 緑の円と十字: 検出された指先
- 座標表示: 正規化座標 (u, v)
- ステータス: CALIBRATED / NOT CALIBRATED
- マーカー検出状況

## トラブルシューティング

### ❌ カメラが開けない

```bash
# システム環境設定 > セキュリティとプライバシー > カメラ
# ターミナルアプリを許可
```

### ⚠️ MediaPipeが使えない

`config/camera.yaml` で色ベース検出に切り替え:
```yaml
hand_detection:
  method: "color"
```

### 🔍 マーカーが検出されない

- 4つ全てのマーカーがカメラ視野内にあるか確認
- 照明を明るくする
- デバッグモードで確認: `config/camera.yaml` の `debug.show_preview: true`

## 次のステップ

サーバーを起動してWebSocket経由で使用:

```bash
python -m teacharm.main

# 別ターミナルで
curl -X POST http://localhost:8000/api/vision/start
```

詳細は [Vision機能ガイド](./Vision機能ガイド.md) を参照。
