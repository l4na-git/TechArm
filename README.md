# TeachArm プロトタイプ実行環境

本リポジトリは、TeachArm 展示デモのための FastAPI ベース実行環境と、管理 UI（Control Panel）をまとめたものです。`docs/` 以下の仕様書に沿って、Vision/Mapping/Dialogue/Arm を統合するサーバと、監視・手動操作用の React UI を提供します。

## 構成

- `teacharm/` – FastAPI サーバ側の Python パッケージ。設定読み込み、教材・スクリプト処理、各サービス stub を含む。
  - `services/router.py` – ルールベースルーティングサービス
  - `services/deepseek.py` – DeepSeek による文章生成専用サービス（必要時のみ呼び出し）
  - `services/dialogue.py` – Router → 台本 → DeepSeek の順で処理する対話オーケストレーション
  - `services/vision.py` – カメラ入力、ArUco検出、MediaPipe Handsによる手検出
  - `services/arm.py` – SO-101 ロボットアーム制御
  - `services/tts.py` – VOICEVOX 音声合成
  - `services/asr.py` – faster-whisper による音声認識
- `config/` – Arm 安全領域や VOICEVOX パラメータ、9 点キャリブレーション、カメラ設定などの JSON/YAML。
- `materials/` – 教材 A/B の領域定義ファイル。
- `scripts/common.yaml` – 先生ロール・台本コマンド・ネガティブルール・エラー復帰メッセージ。
- `.env.example` – 環境変数テンプレート（Tailscale IP、DeepSeek/VOICEVOX URL 等）。
- `control-panel/` – React + Vite 製のコントロールパネル UI。
- `docs/` – 各機能の詳細ドキュメント。
- `tools/` – ArUcoマーカー生成、座標変換、PDF抽出などのユーティリティ。

## 対話システムのアーキテクチャ

TeachArm の対話システムは、**ルールベースルーティング** と **DeepSeek（文章生成専用）** を組み合わせた設計です：

1. **ルールベースルーティング（ローカル処理）**
   - 入力：状態、ASRテキスト、候補領域など
   - 処理：キーワードマッチングでアクション決定
   - 出力：次に実行すべきアクション
   - メリット：高速・確実、ネットワーク不要

2. **台本優先**
   - Router が決定したアクションに従い、まず `scripts/common.yaml` の台本を確認
   - 台本がある場合はそれを使用

3. **DeepSeek（自宅サーバー、Tailscale 経由）**
   - 台本が無い場合や、言い換えが必要な場合のみ呼び出し
   - 1〜2文の短文生成
   - 教材外の質問は拒否して学習に戻す

この設計により、展示会での安定運用を実現しています。

## クイックスタート（サーバ側）

TeachArm サーバは Python 3.11 + [uv](https://github.com/astral-sh/uv) を推奨。Python バージョンは `pyproject.toml` の `requires-python` に固定している。

```bash
UV_PYTHON_PREFERENCE=managed uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env  # Tailscale IP などを実値で記入
python -m teacharm.main
```

デフォルトで `http://0.0.0.0:8000` で待ち受けます。主なエンドポイント：

- `GET /health` – サーバヘルスチェック
- `GET /api/stats` – Router と DeepSeek の統計情報（リクエスト数、フォールバック数、平均時間など）
- `GET /api/materials` – 教材一覧
- `POST /api/materials/select` – 教材選択
- `POST /api/events/pointer` – ポインタイベント（指差し認識）
- `POST /api/dialogue` – テキスト入力による対話
- `POST /api/asr/transcribe` – 音声ファイルの文字起こし（faster-whisper）
- `POST /api/dialogue/audio` – 音声入力→対話→音声生成
- `POST /api/arm/move` – アーム移動
- `POST /api/arm/safe_pose` – アームをセーフポーズに戻す
- `GET /api/state` – 現在の状態取得
- `POST /api/vision/start` – カメラ起動
- `POST /api/vision/stop` – カメラ停止
- `POST /api/vision/calibrate` – ArUcoキャリブレーション実行
- `WebSocket /ws/vision` – リアルタイムビジョンフレーム配信（10fps）

## Vision機能のセットアップ

TeachArmはカメラを使用してArUcoマーカー検出と手・指先追跡を行います。

### クイックスタート

```bash
# 1. ArUcoマーカーを生成
python tools/generate_aruco_markers.py

# 2. 生成されたマーカーを印刷し、教材の四隅に配置

# 3. カメラアクセス許可 (macOS)
# システム環境設定 > セキュリティとプライバシー > カメラ

# 4. インタラクティブデモ（プレビュー付き）
uv run python demo_vision.py
# または基本テスト
uv run python test_vision.py
```

デモ画面では:
- リアルタイムでカメラ映像を確認
- 手・指先の検出結果を可視化（緑の円と十字）
- ArUcoマーカーの検出状況を表示
- `c`キーでキャリブレーション、`q`キーで終了

詳細は [Visionクイックスタート](docs/Visionクイックスタート.md) または [Vision機能ガイド](docs/Vision機能ガイド.md) を参照。

### 設定チェックリスト

- `.env`：Tailscale IP、DeepSeek モデル名、Control Panel URL を実値にする。
  - `DEEPSEEK_BASE_URL`：自宅サーバーの DeepSeek URL（Tailscale 経由）
  - `DEEPSEEK_MODEL`：文章生成用モデル（例: deepseek-r1:7b）
  - `ASR_MODEL` ほか：音声入力（faster-whisper）の設定
- `config/arm_limits.json`：SO-101 の関節制限・Safe Pose を設定。
  - SO-101 は 6 つの Feetech STS3215 サーボモーターを使用
  - 各関節のギア比と可動範囲を記録（詳細: [SO-101 Documentation](https://huggingface.co/docs/lerobot/en/so101)）
  - `safe_pose.angles` に6軸の安全姿勢を関節角度（度）で指定
- `config/arm_calibration.json`：9 点 (u,v)→(x,y,z) を入力。
- `materials/material_*.json`：教材領域（question/line）を実データで記入。
- `config/voicevox_params.yaml`：VOICEVOX の話速/抑揚などを調整（必要に応じて）。
- `config/camera.yaml`：カメラ解像度、MediaPipe設定などを調整（デフォルトで動作）。

### 実装状況

- ✅ **Dialogue/Router/DeepSeek**: 完全実装済み
- ✅ **Vision (Camera + MediaPipe Hands)**: 完全実装済み
- ✅ **TTS (VOICEVOX)**: スタブ実装（外部サーバー接続対応）
- ⚠️ **Arm (SO-101)**: スタブ実装（実機接続は未実装）

実機（カメラ、SO-101アーム）が揃い次第、該当サービスを有効化できます。

## Control Panel（React UI）

`control-panel/` ディレクトリにあるコントロールパネルは Node.js が必要です。

```bash
cd control-panel
npm install
npm run dev
```

デフォルトでは `http://localhost:8000` のサーバに接続します。別ホストへ向ける場合は `VITE_TEACHARM_API_URL` を指定してください。

```bash
VITE_TEACHARM_API_URL=http://100.xxx.xxx.xxx:8000 npm run dev
```

UI 上で以下の操作が可能です：

- サーバヘルスの確認
- Router / DeepSeek の統計情報表示（リクエスト数、フォールバック数、平均応答時間）
- 教材選択の切り替え
- 手動のポインタイベント送信（`on_point` / `on_help`）
- ダイアログテキスト送信（Router → 台本 → DeepSeek）
- アーム座標指定・Safe Pose 戻し
- ログの時系列確認（Router アクション、DeepSeek 呼び出し時間を含む）
- `scripts/common.yaml` の内容編集（YAML エディタで直接保存可能）

Control Panel は Tailscale 内でのみ公開し、`.env` の `CONTROL_PANEL_URL` にブラウザでアクセスする URL を記入してください。

## 自動デプロイ（GitHub Actions）

本プロジェクトは GitHub Actions を使用して、Tailscale 経由で自宅サーバーへ自動デプロイできます。

### 主な機能

- `main` ブランチへの push で自動デプロイ
- 環境変数（`.env`）は GitHub Secrets で安全に管理
- Tailscale ネットワーク経由で安全に転送
- バックエンドとフロントエンドの自動ビルド・再起動

### セットアップ

詳細な手順については [GitHub Actions デプロイガイド](docs/GitHub_Actions_デプロイガイド.md) を参照してください。

概要：
1. Tailscale OAuth Client を作成
2. SSH キーペアを生成
3. GitHub Secrets を設定（デプロイ設定 + 環境変数）
4. `main` ブランチに push

デプロイ後、サーバー上で自動的に以下が実行されます：
- 既存プロセスの停止
- Python 依存関係のインストール
- Control Panel のビルド
- バックエンドとフロントエンドの起動

