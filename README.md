# TeachArm プロトタイプ実行環境

本リポジトリは、TeachArm 展示デモのための FastAPI ベース実行環境と、管理 UI（Control Panel）をまとめたものです。`docs/` 以下の仕様書に沿って、Vision/Mapping/Dialogue/Arm を統合するサーバと、監視・手動操作用の React UI を提供します。

## 構成

- `teacharm/` – FastAPI サーバ側の Python パッケージ。設定読み込み、教材・スクリプト処理、各サービス stub を含む。
  - `services/router.py` – FunctionGemma によるルーティング専用サービス（JSON 出力のみ）
  - `services/deepseek.py` – DeepSeek による文章生成専用サービス（必要時のみ呼び出し）
  - `services/dialogue.py` – Router → 台本 → DeepSeek の順で処理する対話オーケストレーション
- `config/` – Arm 安全領域や VOICEVOX パラメータ、9 点キャリブレーションなどの JSON/YAML。
- `materials/` – 教材 A/B の領域定義ファイル。
- `scripts/common.yaml` – 先生ロール・台本コマンド・ネガティブルール・エラー復帰メッセージ。
- `.env.example` – 環境変数テンプレート（Tailscale IP、FunctionGemma/DeepSeek/VOICEVOX URL 等）。
- `control-panel/` – React + Vite 製のコントロールパネル UI。

## 対話システムのアーキテクチャ

TeachArm の対話システムは、**FunctionGemma（ルーティング専用）** と **DeepSeek（文章生成専用）** を分離した設計です：

1. **FunctionGemma（ローカル推論）**
   - 入力：状態、ASRテキスト、候補領域など
   - 出力：次に実行すべきアクション（JSON のみ）
   - ホワイトリスト検証でアクションを確定
   - JSON パース失敗時はルールベースにフォールバック

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
- `POST /api/arm/move` – アーム移動
- `POST /api/arm/safe_pose` – アームをセーフポーズに戻す
- `GET /api/state` – 現在の状態取得

### 設定チェックリスト

- `.env`：Tailscale IP、FunctionGemma/DeepSeek モデル名、Control Panel URL を実値にする。
  - `FUNCTION_GEMMA_BASE_URL`：ローカルで動作する FunctionGemma の URL（デフォルト: http://127.0.0.1:11434）
  - `FUNCTION_GEMMA_MODEL`：ルーティング用モデル（推奨: functiongemma:latest）
  - `DEEPSEEK_BASE_URL`：自宅サーバーの DeepSeek URL（Tailscale 経由）
  - `DEEPSEEK_MODEL`：文章生成用モデル（例: deepseek-r1:7b）
- `config/arm_limits.json`：so-101 の安全領域・Safe Pose を測定値で設定。
- `config/arm_calibration.json`：9 点 (u,v)→(x,y,z) を入力。
- `materials/material_*.json`：教材領域（question/line）を実データで記入。
- `config/voicevox_params.yaml`：VOICEVOX の話速/抑揚などを調整（必要に応じて）。

現時点では Vision/Arm 実装にスタブを含んでおり、ログ出力で動作を確認できます。実機が揃い次第、該当サービスを差し替えてください。

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
